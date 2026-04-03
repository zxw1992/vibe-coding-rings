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


# ── Focus time parsing (history.jsonl) ───────────────────────────────────────

def _calc_focus_minutes(target: date) -> float:
    """
    Calculate focused AI work time for the given LOCAL date using history.jsonl.
    Uses 30-min idle gap to split sessions into focus blocks.
    Timestamps in history.jsonl are epoch milliseconds (no timezone issue).
    """
    if not HISTORY_FILE.exists():
        return 0.0

    start_ms, end_ms = _local_date_to_utc_ms_range(target)

    sessions: dict[str, list[int]] = {}
    no_session_ts: list[int] = []

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
            sid = entry.get("sessionId")
            if sid:
                sessions.setdefault(sid, []).append(ts)
            else:
                no_session_ts.append(ts)
    except OSError:
        return 0.0

    def _sum_session(timestamps: list[int]) -> int:
        if not timestamps:
            return 0
        ts_sorted = sorted(timestamps)
        block_start = block_end = ts_sorted[0]
        accumulated = 0
        for ts in ts_sorted[1:]:
            if ts - block_end > IDLE_GAP_MS:
                accumulated += (block_end - block_start) + TRAIL_BUFFER_MS
                block_start = ts
            block_end = ts
        accumulated += (block_end - block_start) + TRAIL_BUFFER_MS
        return accumulated

    total_ms = sum(_sum_session(v) for v in sessions.values())
    if no_session_ts:
        total_ms += _sum_session(no_session_ts)

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
    focus_h = [0.0] * 24

    if HISTORY_FILE.exists():
        hour_sid_ts: dict[int, dict[str, list[int]]] = {h: {} for h in range(24)}
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
                hour = _ms_to_local_hour(ts)
                sid  = entry.get("sessionId", "__nosid__")
                hour_sid_ts[hour].setdefault(sid, []).append(ts)
        except OSError:
            pass

        hour_ms = 3_600_000
        for h in range(24):
            hour_start_ms = start_ms + h * hour_ms
            hour_end_ms   = hour_start_ms + hour_ms
            total = 0
            for ts_list in hour_sid_ts[h].values():
                if not ts_list:
                    continue
                ts_sorted = sorted(ts_list)
                span  = ts_sorted[-1] - ts_sorted[0]
                trail = min(TRAIL_BUFFER_MS, max(0, hour_end_ms - ts_sorted[-1]))
                total += span + trail
            focus_h[h] = total / 60_000

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
