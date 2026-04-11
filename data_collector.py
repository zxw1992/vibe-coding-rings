from __future__ import annotations
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta

from config import Goals
from agent_providers import (
    ClaudeCodeProvider, CodexProvider, GeminiProvider, OpenCodeProvider,
    AgentProvider, _local_tz, _local_date_to_utc_ms_range,
)

# ── Provider registry ─────────────────────────────────────────────────────────

_PROVIDERS: dict[str, AgentProvider] = {
    "claude_code": ClaudeCodeProvider(),
    "codex":       CodexProvider(),
    "gemini":      GeminiProvider(),
    "opencode":    OpenCodeProvider(),
}


def _active_providers(goals: Goals) -> list[AgentProvider]:
    return [p for k, p in _PROVIDERS.items()
            if k in goals.enabled_agents and p.is_available()]


# ── Day metrics ───────────────────────────────────────────────────────────────

@dataclass
class DayMetrics:
    date: str
    tokens: int
    tool_calls: int
    focus_min: float
    token_pct: float = 0.0
    tool_pct:  float = 0.0
    focus_pct: float = 0.0


def _with_goals(m: DayMetrics, goals: Goals) -> DayMetrics:
    m.token_pct = m.tokens    / goals.tokens    if goals.tokens    else 0
    m.tool_pct  = m.tool_calls / goals.tool_calls if goals.tool_calls else 0
    m.focus_pct = m.focus_min  / goals.focus_min  if goals.focus_min  else 0
    return m


# ── Cache ─────────────────────────────────────────────────────────────────────

_cache: dict[tuple, DayMetrics] = {}


# ── Public API ────────────────────────────────────────────────────────────────

def collect_day_metrics(target: date, goals: Goals) -> DayMetrics:
    cache_key = (
        round(time.time() / 60), target.isoformat(),
        goals.tokens, goals.focus_min, goals.tool_calls,
        tuple(sorted(goals.enabled_agents)),
    )
    if cache_key in _cache:
        return _cache[cache_key]

    providers = _active_providers(goals)
    tokens = 0
    tool_calls = 0
    focus_min = 0.0
    for p in providers:
        t, tc = p.collect_tokens_and_tools(target)
        tokens     += t
        tool_calls += tc
        focus_min  += p.collect_focus_minutes(target)

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


def collect_hourly(target: date, goals: Goals) -> dict[str, list]:
    """
    Returns 24-bucket arrays keyed by LOCAL hour for tokens, tool_calls,
    and focus_min, aggregated across all active providers.
    """
    providers = _active_providers(goals)
    tokens_h = [0]   * 24
    tools_h  = [0]   * 24
    focus_h  = [0.0] * 24

    for p in providers:
        hourly = p.collect_hourly(target)
        for h in range(24):
            tokens_h[h] += hourly["tokens"][h]
            tools_h[h]  += hourly["tools"][h]
            focus_h[h]  += hourly["focus"][h]

    return {"tokens": tokens_h, "tools": tools_h, "focus": focus_h}


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from config import load_config
    goals = load_config()
    today = date.today()
    tz    = _local_tz()
    start_ms, end_ms = _local_date_to_utc_ms_range(today)
    print(f"Local date:  {today}  (tz: {tz})")
    print(f"UTC range:   {datetime.fromtimestamp(start_ms/1000, tz=timezone.utc).isoformat()}")
    print(f"          →  {datetime.fromtimestamp(end_ms/1000,   tz=timezone.utc).isoformat()}")
    print(f"Agents:      {goals.enabled_agents}")
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
