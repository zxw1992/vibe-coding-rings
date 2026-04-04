from __future__ import annotations
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

from config import CLAUDE_DIR, HISTORY_FILE, PROJECTS_DIR, Goals

IDLE_GAP_MS = 30 * 60 * 1000     # 30 min gap = new focus block
TRAIL_BUFFER_MS = 5 * 60 * 1000  # 5 min credit after last message

# ── Timezone helpers ──────────────────────────────────────────────────────────

def _local_tz() -> timezone:
    """Return the system's current local timezone (handles DST correctly)."""
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def _local_date_to_utc_ms_range(target: date) -> tuple[int, int]:
    """
    Convert a LOCAL calendar date to a UTC millisecond epoch range [start, end).

    Example (UTC+8): April 4 local → UTC Apr 3 16:00:00 .. Apr 4 16:00:00
    This is the correct range to scan in files that store UTC timestamps.
    """
    tz = _local_tz()
    local_start = datetime(target.year, target.month, target.day, tzinfo=tz)
    local_end   = local_start + timedelta(days=1)
    start_ms = int(local_start.astimezone(timezone.utc).timestamp() * 1000)
    end_ms   = int(local_end.astimezone(timezone.utc).timestamp()   * 1000)
    return start_ms, end_ms


def _ms_to_local_hour(ms: int) -> int:
    """Convert epoch milliseconds to the local hour-of-day (0-23)."""
    return datetime.fromtimestamp(ms / 1000, tz=_local_tz()).hour


def _iso_to_ms(ts_raw: str) -> int | None:
    """
    Parse a session JSONL ISO timestamp like '2026-04-03T16:37:55.432Z'
    and return epoch milliseconds, or None on failure.
    """
    try:
        return int(
            datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp() * 1000
        )
    except (ValueError, AttributeError):
        return None


# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DayMetrics:
    date: str
    tokens: int
    tool_calls: int
    focus_min: float
    token_pct: float = 0.0
    tool_pct: float = 0.0
    focus_pct: float = 0.0


def _with_goals(m: DayMetrics, goals: Goals) -> DayMetrics:
    m.token_pct = m.tokens / goals.tokens if goals.tokens else 0
    m.tool_pct  = m.tool_calls / goals.tool_calls if goals.tool_calls else 0
    m.focus_pct = m.focus_min / goals.focus_min if goals.focus_min else 0
    return m


# ── Token + Tool Call parsing (session JSONL files) ──────────────────────────

def _collect_tokens_and_tools(target: date) -> tuple[int, int]:
    """
    Scan session JSONL files for tokens and tool call counts on the given
    LOCAL date.  Uses a UTC ms range to correctly handle any timezone.
    """
    start_ms, end_ms = _local_date_to_utc_ms_range(target)

    tokens     = 0
    tool_calls = 0

    if not PROJECTS_DIR.exists():
        return tokens, tool_calls

    # mtime filter: ±2 days to safely cover any UTC offset
    mtime_lo = (start_ms / 1000) - 2 * 86_400
    mtime_hi = (end_ms   / 1000) + 2 * 86_400

    for session_file in PROJECTS_DIR.rglob("*.jsonl"):
        try:
            if not (mtime_lo <= session_file.stat().st_mtime <= mtime_hi):
                continue
        except OSError:
            continue
        try:
            for raw_line in session_file.read_text(errors="ignore").splitlines():
                if not raw_line.strip():
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                ts_raw = entry.get("timestamp", "")
                if not isinstance(ts_raw, str):
                    continue
                ts_ms = _iso_to_ms(ts_raw)
                if ts_ms is None or not (start_ms <= ts_ms < end_ms):
                    continue
                if entry.get("type") != "assistant":
                    continue

                msg   = entry.get("message", {})
                usage = msg.get("usage", {})
                tokens += (
                    usage.get("input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                )
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_calls += 1
        except OSError:
            continue

    return tokens, tool_calls


# ── Focus time helpers ────────────────────────────────────────────────────────

def _read_history_sessions(start_ms: int, end_ms: int) -> dict[str, list[int]]:
    """
    Read history.jsonl and return {sessionId: [epoch_ms, ...]} for timestamps
    in [start_ms, end_ms).  Missing sessionId is grouped under '__nosid__'.
    """
    sessions: dict[str, list[int]] = {}
    if not HISTORY_FILE.exists():
        return sessions
    try:
        for raw_line in HISTORY_FILE.read_text(errors="ignore").splitlines():
            if not raw_line.strip():
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            ts = entry.get("timestamp")
            if not isinstance(ts, (int, float)):
                continue
            ts = int(ts)
            if not (start_ms <= ts < end_ms):
                continue
            # Exclude slash-command-only entries (e.g. automated /usage polling)
            # These are not interactive conversational focus work.
            display = entry.get("display", "")
            if isinstance(display, str) and display.strip().startswith("/"):
                continue
            sid = entry.get("sessionId") or "__nosid__"
            sessions.setdefault(sid, []).append(ts)
    except OSError:
        pass
    return sessions


def _sessions_to_focus_blocks(sessions: dict[str, list[int]]) -> list[tuple[int, int]]:
    """
    Convert session timestamp lists to a list of (start_ms, end_ms) focus blocks.
    Gaps > IDLE_GAP_MS within a session start a new block.
    Each block's end gets TRAIL_BUFFER_MS added.
    """
    blocks: list[tuple[int, int]] = []
    for ts_list in sessions.values():
        if not ts_list:
            continue
        ts_sorted = sorted(ts_list)
        blk_start = blk_end = ts_sorted[0]
        for ts in ts_sorted[1:]:
            if ts - blk_end > IDLE_GAP_MS:
                blocks.append((blk_start, blk_end + TRAIL_BUFFER_MS))
                blk_start = ts
            blk_end = ts
        blocks.append((blk_start, blk_end + TRAIL_BUFFER_MS))
    return blocks


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sort and merge overlapping [start, end) intervals."""
    if not intervals:
        return []
    result = [sorted(intervals)[0]]
    for s, e in sorted(intervals)[1:]:
        if s <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], e))
        else:
            result.append((s, e))
    return result


def _interval_ms_in_range(merged: list[tuple[int, int]], lo: int, hi: int) -> int:
    """Sum the milliseconds of merged intervals that fall within [lo, hi)."""
    total = 0
    for s, e in merged:
        cs, ce = max(s, lo), min(e, hi)
        if cs < ce:
            total += ce - cs
    return total


# ── Focus time parsing (history.jsonl) ───────────────────────────────────────

def _calc_focus_minutes(target: date) -> float:
    """
    Calculate focused AI work time for the given LOCAL date using history.jsonl.
    Uses 30-min idle gap to split sessions into focus blocks, then merges
    overlapping blocks so parallel sessions are never double-counted.
    """
    start_ms, end_ms = _local_date_to_utc_ms_range(target)
    sessions = _read_history_sessions(start_ms, end_ms)
    if not sessions:
        return 0.0

    blocks = _sessions_to_focus_blocks(sessions)
    merged = _merge_intervals(blocks)
    total_ms = _interval_ms_in_range(merged, start_ms, end_ms)
    return total_ms / 60_000


# ── Hourly breakdown ──────────────────────────────────────────────────────────

def collect_hourly(target: date) -> dict[str, list]:
    """
    Returns 24-bucket arrays keyed by LOCAL hour for tokens, tool_calls,
    and focus_min.  Used for the detail/drill-down page.
    """
    start_ms, end_ms = _local_date_to_utc_ms_range(target)

    tokens_h = [0] * 24
    tools_h  = [0] * 24

    # --- tokens + tools from session JSONL ---
    if PROJECTS_DIR.exists():
        mtime_lo = (start_ms / 1000) - 2 * 86_400
        mtime_hi = (end_ms   / 1000) + 2 * 86_400

        for session_file in PROJECTS_DIR.rglob("*.jsonl"):
            try:
                if not (mtime_lo <= session_file.stat().st_mtime <= mtime_hi):
                    continue
                for raw_line in session_file.read_text(errors="ignore").splitlines():
                    if not raw_line.strip():
                        continue
                    try:
                        entry = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    ts_raw = entry.get("timestamp", "")
                    if not isinstance(ts_raw, str):
                        continue
                    ts_ms = _iso_to_ms(ts_raw)
                    if ts_ms is None or not (start_ms <= ts_ms < end_ms):
                        continue
                    if entry.get("type") != "assistant":
                        continue
                    hour = _ms_to_local_hour(ts_ms)
                    msg   = entry.get("message", {})
                    usage = msg.get("usage", {})
                    tokens_h[hour] += (
                        usage.get("input_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                    )
                    for block in msg.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tools_h[hour] += 1
            except OSError:
                continue

    # --- focus minutes from history.jsonl (local hours) ---
    # Build merged focus-block intervals for the whole day, then intersect each
    # hour bucket.  This prevents >60 min/hour and double-counting of sessions.
    focus_h = [0.0] * 24

    sessions = _read_history_sessions(start_ms, end_ms)
    if sessions:
        blocks = _sessions_to_focus_blocks(sessions)
        merged = _merge_intervals(blocks)
        hour_ms = 3_600_000
        for h in range(24):
            hour_lo = start_ms + h * hour_ms
            hour_hi = hour_lo + hour_ms
            focus_h[h] = _interval_ms_in_range(merged, hour_lo, hour_hi) / 60_000

    return {"tokens": tokens_h, "tools": tools_h, "focus": focus_h}


# ── Public API ────────────────────────────────────────────────────────────────

_cache: dict[tuple, DayMetrics] = {}


def collect_day_metrics(target: date, goals: Goals) -> DayMetrics:
    cache_key = (round(time.time() / 60), target.isoformat(),
                 goals.tokens, goals.focus_min, goals.tool_calls)
    if cache_key in _cache:
        return _cache[cache_key]

    tokens, tool_calls = _collect_tokens_and_tools(target)
    focus_min = _calc_focus_minutes(target)

    m = DayMetrics(
        date=target.isoformat(),
        tokens=tokens,
        tool_calls=tool_calls,
        focus_min=round(focus_min, 1),
    )
    _with_goals(m, goals)
    _cache[cache_key] = m
    return m


def collect_history(goals: Goals, days: int = 7) -> list[DayMetrics]:
    today = date.today()
    return [collect_day_metrics(today - timedelta(days=i), goals) for i in range(days)]


def calc_streak(history: list[DayMetrics]) -> int:
    streak = 0
    for day in history:
        if day.token_pct >= 1.0 and day.focus_pct >= 1.0 and day.tool_pct >= 1.0:
            streak += 1
        else:
            break
    return streak


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from config import load_config
    goals = load_config()
    today = date.today()
    tz    = _local_tz()
    start_ms, end_ms = _local_date_to_utc_ms_range(today)
    print(f"Local date:  {today}  (tz: {tz})")
    print(f"UTC range:   {datetime.fromtimestamp(start_ms/1000, tz=timezone.utc).isoformat()}")
    print(f"          →  {datetime.fromtimestamp(end_ms/1000, tz=timezone.utc).isoformat()}")
    print()
    m = collect_day_metrics(today, goals)
    print(f"Tokens:      {m.tokens:,}  ({m.token_pct:.1%})")
    print(f"Focus time:  {m.focus_min:.1f} min  ({m.focus_pct:.1%})")
    print(f"Tool calls:  {m.tool_calls}  ({m.tool_pct:.1%})")
    history = collect_history(goals, days=7)
    streak  = calc_streak(history)
    print(f"Streak:      {streak} day(s)")
    print("\n7-day history:")
    for d in history:
        ok = all([d.token_pct >= 1, d.focus_pct >= 1, d.tool_pct >= 1])
        print(f"  {d.date}  tokens={d.tokens:,}  focus={d.focus_min:.0f}min  tools={d.tool_calls}  {'✓' if ok else '○'}")
