from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
import json

from config import CLAUDE_DIR, HISTORY_FILE, PROJECTS_DIR, CODEX_DIR, GEMINI_DIR, OPENCODE_DIR

IDLE_GAP_MS     = 30 * 60 * 1000   # 30 min gap → new focus block
TRAIL_BUFFER_MS =  5 * 60 * 1000   # 5 min credit after last message


# ── Shared timezone + parsing helpers ─────────────────────────────────────────

def _local_tz():
    return datetime.now().astimezone().tzinfo


def _local_date_to_utc_ms_range(target: date) -> tuple[int, int]:
    tz = _local_tz()
    local_start = datetime(target.year, target.month, target.day, tzinfo=tz)
    local_end   = local_start + timedelta(days=1)
    start_ms = int(local_start.astimezone(timezone.utc).timestamp() * 1000)
    end_ms   = int(local_end.astimezone(timezone.utc).timestamp()   * 1000)
    return start_ms, end_ms


def _ms_to_local_hour(ms: int) -> int:
    return datetime.fromtimestamp(ms / 1000, tz=_local_tz()).hour


def _iso_to_ms(ts_raw: str) -> int | None:
    try:
        return int(datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, AttributeError):
        return None


def _sessions_to_focus_blocks(sessions: dict[str, list[int]]) -> list[tuple[int, int]]:
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
    total = 0
    for s, e in merged:
        cs, ce = max(s, lo), min(e, hi)
        if cs < ce:
            total += ce - cs
    return total


def _read_history_sessions(history_file: Path, start_ms: int, end_ms: int,
                            filter_slashcmds: bool = False) -> dict[str, list[int]]:
    """Parse a history.jsonl-style file into {sessionId: [epoch_ms, ...]}."""
    sessions: dict[str, list[int]] = {}
    if not history_file.exists():
        return sessions
    try:
        for raw_line in history_file.read_text(errors="ignore").splitlines():
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
            if filter_slashcmds:
                display = entry.get("display", "")
                if isinstance(display, str) and display.strip().startswith("/"):
                    continue
            sid = entry.get("sessionId") or "__nosid__"
            sessions.setdefault(sid, []).append(ts)
    except OSError:
        pass
    return sessions


def _focus_from_sessions(sessions: dict[str, list[int]], start_ms: int, end_ms: int) -> float:
    if not sessions:
        return 0.0
    blocks = _sessions_to_focus_blocks(sessions)
    merged = _merge_intervals(blocks)
    return _interval_ms_in_range(merged, start_ms, end_ms) / 60_000


def _focus_hourly_from_sessions(sessions: dict[str, list[int]],
                                 start_ms: int, end_ms: int) -> list[float]:
    if not sessions:
        return [0.0] * 24
    blocks = _sessions_to_focus_blocks(sessions)
    merged = _merge_intervals(blocks)
    hour_ms = 3_600_000
    return [
        _interval_ms_in_range(merged, start_ms + h * hour_ms, start_ms + (h + 1) * hour_ms) / 60_000
        for h in range(24)
    ]


# ── Abstract base ─────────────────────────────────────────────────────────────

class AgentProvider(ABC):
    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def collect_tokens_and_tools(self, target: date) -> tuple[int, int]: ...

    @abstractmethod
    def collect_focus_minutes(self, target: date) -> float: ...

    @abstractmethod
    def collect_hourly(self, target: date) -> dict[str, list]: ...


# ── Claude Code provider ──────────────────────────────────────────────────────

class ClaudeCodeProvider(AgentProvider):

    def is_available(self) -> bool:
        return CLAUDE_DIR.exists()

    def _mtime_bounds(self, start_ms: int, end_ms: int) -> tuple[float, float]:
        return (start_ms / 1000) - 2 * 86_400, (end_ms / 1000) + 2 * 86_400

    def collect_tokens_and_tools(self, target: date) -> tuple[int, int]:
        start_ms, end_ms = _local_date_to_utc_ms_range(target)
        tokens = 0
        tool_calls = 0
        if not PROJECTS_DIR.exists():
            return tokens, tool_calls
        mtime_lo, mtime_hi = self._mtime_bounds(start_ms, end_ms)
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

    def collect_focus_minutes(self, target: date) -> float:
        start_ms, end_ms = _local_date_to_utc_ms_range(target)
        sessions = _read_history_sessions(HISTORY_FILE, start_ms, end_ms, filter_slashcmds=True)
        return _focus_from_sessions(sessions, start_ms, end_ms)

    def collect_hourly(self, target: date) -> dict[str, list]:
        start_ms, end_ms = _local_date_to_utc_ms_range(target)
        tokens_h = [0] * 24
        tools_h  = [0] * 24

        if PROJECTS_DIR.exists():
            mtime_lo, mtime_hi = self._mtime_bounds(start_ms, end_ms)
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
                        hour  = _ms_to_local_hour(ts_ms)
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

        sessions = _read_history_sessions(HISTORY_FILE, start_ms, end_ms, filter_slashcmds=True)
        focus_h  = _focus_hourly_from_sessions(sessions, start_ms, end_ms)
        return {"tokens": tokens_h, "tools": tools_h, "focus": focus_h}


# ── Codex provider ────────────────────────────────────────────────────────────

class CodexProvider(AgentProvider):
    """
    Provider for OpenAI Codex CLI / Codex Desktop (~/.codex/).
    Schema: rollout-*.jsonl with top-level {timestamp, type, payload}.
      - tokens  : event_msg / token_count → payload.info.last_token_usage.total_tokens (per-turn delta)
      - tools   : response_item / {function_call, custom_tool_call, web_search_call}
      - focus   : event_msg / user_message timestamps grouped by session_meta.id
                  (Codex Desktop no longer writes ~/.codex/history.jsonl)
    """

    TOOL_PAYLOAD_TYPES = {"function_call", "custom_tool_call", "web_search_call"}

    def is_available(self) -> bool:
        return CODEX_DIR.exists()

    def _iter_session_files(self, start_ms: int, end_ms: int):
        mtime_lo = (start_ms / 1000) - 2 * 86_400
        mtime_hi = (end_ms / 1000) + 2 * 86_400
        sessions_root = CODEX_DIR / "sessions"
        if not sessions_root.exists():
            return
        for f in sessions_root.rglob("*.jsonl"):
            try:
                if mtime_lo <= f.stat().st_mtime <= mtime_hi:
                    yield f
            except OSError:
                continue

    def _classify(self, entry: dict) -> tuple[str, int, int]:
        """Return (kind, tokens, tools_count). kind in {'token','tool',''}."""
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            return ("", 0, 0)
        ptype = payload.get("type")
        if entry.get("type") == "event_msg" and ptype == "token_count":
            info = payload.get("info")
            if isinstance(info, dict):
                last = info.get("last_token_usage") or {}
                if isinstance(last, dict):
                    return ("token", int(last.get("total_tokens", 0) or 0), 0)
            return ("", 0, 0)
        if entry.get("type") == "response_item" and ptype in self.TOOL_PAYLOAD_TYPES:
            return ("tool", 0, 1)
        return ("", 0, 0)

    def _collect_focus_sessions(self, start_ms: int, end_ms: int) -> dict[str, list[int]]:
        sessions: dict[str, list[int]] = {}
        for f in self._iter_session_files(start_ms, end_ms):
            sid = f.stem  # fallback: filename stem if session_meta missing
            try:
                for raw_line in f.read_text(errors="ignore").splitlines():
                    if not raw_line.strip():
                        continue
                    try:
                        entry = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    payload = entry.get("payload") or {}
                    if not isinstance(payload, dict):
                        continue
                    if entry.get("type") == "session_meta":
                        meta_id = payload.get("id")
                        if isinstance(meta_id, str) and meta_id:
                            sid = meta_id
                        continue
                    if entry.get("type") != "event_msg" or payload.get("type") != "user_message":
                        continue
                    ts_raw = entry.get("timestamp", "")
                    if not isinstance(ts_raw, str):
                        continue
                    ts_ms = _iso_to_ms(ts_raw)
                    if ts_ms is None or not (start_ms <= ts_ms < end_ms):
                        continue
                    sessions.setdefault(sid, []).append(ts_ms)
            except OSError:
                continue
        return sessions

    def collect_tokens_and_tools(self, target: date) -> tuple[int, int]:
        start_ms, end_ms = _local_date_to_utc_ms_range(target)
        tokens = 0
        tool_calls = 0
        for f in self._iter_session_files(start_ms, end_ms):
            try:
                for raw_line in f.read_text(errors="ignore").splitlines():
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
                    kind, t, c = self._classify(entry)
                    tokens     += t
                    tool_calls += c
            except OSError:
                continue
        return tokens, tool_calls

    def collect_focus_minutes(self, target: date) -> float:
        start_ms, end_ms = _local_date_to_utc_ms_range(target)
        sessions = self._collect_focus_sessions(start_ms, end_ms)
        return _focus_from_sessions(sessions, start_ms, end_ms)

    def collect_hourly(self, target: date) -> dict[str, list]:
        start_ms, end_ms = _local_date_to_utc_ms_range(target)
        tokens_h = [0] * 24
        tools_h  = [0] * 24
        for f in self._iter_session_files(start_ms, end_ms):
            try:
                for raw_line in f.read_text(errors="ignore").splitlines():
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
                    kind, t, c = self._classify(entry)
                    if not kind:
                        continue
                    hour = _ms_to_local_hour(ts_ms)
                    tokens_h[hour] += t
                    tools_h[hour]  += c
            except OSError:
                continue
        sessions = self._collect_focus_sessions(start_ms, end_ms)
        focus_h  = _focus_hourly_from_sessions(sessions, start_ms, end_ms)
        return {"tokens": tokens_h, "tools": tools_h, "focus": focus_h}


# ── Gemini CLI provider ───────────────────────────────────────────────────────

class GeminiProvider(AgentProvider):
    """
    Best-effort provider for Google Gemini CLI (~/.gemini/).
    Token usage from usageMetadata.totalTokenCount;
    tool calls from parts[].functionCall.
    """

    def is_available(self) -> bool:
        return GEMINI_DIR.exists()

    def _iter_session_files(self, start_ms: int, end_ms: int):
        mtime_lo = (start_ms / 1000) - 2 * 86_400
        mtime_hi = (end_ms / 1000) + 2 * 86_400
        for f in GEMINI_DIR.rglob("*.jsonl"):
            try:
                if mtime_lo <= f.stat().st_mtime <= mtime_hi:
                    yield f
            except OSError:
                continue

    def _parse_ts(self, entry: dict) -> int | None:
        for key in ("timestamp", "created_at", "createTime"):
            val = entry.get(key)
            if isinstance(val, str):
                ms = _iso_to_ms(val)
                if ms is not None:
                    return ms
            elif isinstance(val, (int, float)) and val > 1_000_000_000:
                ts = int(val)
                return ts * 1000 if ts < 1e12 else ts
        return None

    def _extract_tokens(self, entry: dict) -> int:
        meta = entry.get("usageMetadata") or {}
        total = meta.get("totalTokenCount", 0)
        if total:
            return total
        return meta.get("promptTokenCount", 0) + meta.get("candidatesTokenCount", 0)

    def _extract_tool_calls(self, entry: dict) -> int:
        count = 0
        for candidate in entry.get("candidates", []):
            content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
            for part in (content.get("parts", []) if isinstance(content, dict) else []):
                if isinstance(part, dict) and "functionCall" in part:
                    count += 1
        for part in entry.get("parts", []):
            if isinstance(part, dict) and "functionCall" in part:
                count += 1
        return count

    def _is_model_response(self, entry: dict) -> bool:
        return (entry.get("role") in ("model", "assistant")
                or "candidates" in entry
                or "usageMetadata" in entry)

    def collect_tokens_and_tools(self, target: date) -> tuple[int, int]:
        start_ms, end_ms = _local_date_to_utc_ms_range(target)
        tokens = 0
        tool_calls = 0
        for f in self._iter_session_files(start_ms, end_ms):
            try:
                for raw_line in f.read_text(errors="ignore").splitlines():
                    if not raw_line.strip():
                        continue
                    try:
                        entry = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    if not self._is_model_response(entry):
                        continue
                    ts_ms = self._parse_ts(entry)
                    if ts_ms is None or not (start_ms <= ts_ms < end_ms):
                        continue
                    tokens     += self._extract_tokens(entry)
                    tool_calls += self._extract_tool_calls(entry)
            except OSError:
                continue
        return tokens, tool_calls

    def collect_focus_minutes(self, target: date) -> float:
        start_ms, end_ms = _local_date_to_utc_ms_range(target)
        for name in ("history.jsonl", "history"):
            history = GEMINI_DIR / name
            if history.exists():
                sessions = _read_history_sessions(history, start_ms, end_ms)
                result = _focus_from_sessions(sessions, start_ms, end_ms)
                if result > 0:
                    return result
        return 0.0

    def collect_hourly(self, target: date) -> dict[str, list]:
        start_ms, end_ms = _local_date_to_utc_ms_range(target)
        tokens_h = [0] * 24
        tools_h  = [0] * 24
        for f in self._iter_session_files(start_ms, end_ms):
            try:
                for raw_line in f.read_text(errors="ignore").splitlines():
                    if not raw_line.strip():
                        continue
                    try:
                        entry = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    if not self._is_model_response(entry):
                        continue
                    ts_ms = self._parse_ts(entry)
                    if ts_ms is None or not (start_ms <= ts_ms < end_ms):
                        continue
                    hour = _ms_to_local_hour(ts_ms)
                    tokens_h[hour] += self._extract_tokens(entry)
                    tools_h[hour]  += self._extract_tool_calls(entry)
            except OSError:
                continue
        focus_h = [0.0] * 24
        for name in ("history.jsonl", "history"):
            history = GEMINI_DIR / name
            if history.exists():
                sessions = _read_history_sessions(history, start_ms, end_ms)
                focus_h  = _focus_hourly_from_sessions(sessions, start_ms, end_ms)
                break
        return {"tokens": tokens_h, "tools": tools_h, "focus": focus_h}


# ── OpenCode provider ─────────────────────────────────────────────────────────

class OpenCodeProvider(AgentProvider):
    """
    Best-effort provider for OpenCode (SST, opencode.ai) (~/.opencode/).
    OpenCode proxies the Anthropic API and uses an identical JSONL schema.
    """

    def is_available(self) -> bool:
        return OPENCODE_DIR.exists()

    def _iter_session_files(self, start_ms: int, end_ms: int):
        mtime_lo = (start_ms / 1000) - 2 * 86_400
        mtime_hi = (end_ms / 1000) + 2 * 86_400
        for f in OPENCODE_DIR.rglob("*.jsonl"):
            try:
                if mtime_lo <= f.stat().st_mtime <= mtime_hi:
                    yield f
            except OSError:
                continue

    def collect_tokens_and_tools(self, target: date) -> tuple[int, int]:
        start_ms, end_ms = _local_date_to_utc_ms_range(target)
        tokens = 0
        tool_calls = 0
        for f in self._iter_session_files(start_ms, end_ms):
            try:
                for raw_line in f.read_text(errors="ignore").splitlines():
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

    def collect_focus_minutes(self, target: date) -> float:
        start_ms, end_ms = _local_date_to_utc_ms_range(target)
        sessions = _read_history_sessions(OPENCODE_DIR / "history.jsonl", start_ms, end_ms)
        return _focus_from_sessions(sessions, start_ms, end_ms)

    def collect_hourly(self, target: date) -> dict[str, list]:
        start_ms, end_ms = _local_date_to_utc_ms_range(target)
        tokens_h = [0] * 24
        tools_h  = [0] * 24
        for f in self._iter_session_files(start_ms, end_ms):
            try:
                for raw_line in f.read_text(errors="ignore").splitlines():
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
                    hour  = _ms_to_local_hour(ts_ms)
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
        sessions = _read_history_sessions(OPENCODE_DIR / "history.jsonl", start_ms, end_ms)
        focus_h  = _focus_hourly_from_sessions(sessions, start_ms, end_ms)
        return {"tokens": tokens_h, "tools": tools_h, "focus": focus_h}
