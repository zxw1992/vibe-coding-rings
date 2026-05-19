from __future__ import annotations
import argparse
import json as _json
import sys
import threading
import time
import webbrowser
from datetime import date, timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import Goals, load_config, save_config
from data_collector import collect_day_metrics, collect_history, calc_streak, collect_hourly, collect_agent_breakdown, _PROVIDERS

# When running as a py2app bundle, Resources/ is two levels above the binary.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.parent / "Resources"
else:
    BASE_DIR = Path(__file__).parent
PORT = 8765

app = FastAPI(title="Vibe Coding Rings")

# Callbacks invoked after goals are saved (used by menubar.py for instant refresh)
_goals_changed_callbacks: list = []

def register_goals_changed(fn) -> None:
    _goals_changed_callbacks.append(fn)


# ---------- Pydantic models ----------

class GoalsIn(BaseModel):
    tokens: int
    focus_min: int
    tool_calls: int

class LangIn(BaseModel):
    lang: str

class AgentsIn(BaseModel):
    enabled: list[str]


AGENT_META: dict[str, dict] = {
    "claude_code": {"label": "Claude Code", "dir": "~/.claude"},
    "codex":       {"label": "Codex",       "dir": "~/.codex"},
    "gemini":      {"label": "Gemini CLI",  "dir": "~/.gemini"},
    "opencode":    {"label": "OpenCode",    "dir": "~/.opencode"},
}


# ---------- API routes (must be before static mount) ----------

@app.get("/api/today")
def api_today():
    goals = load_config()
    today = date.today()
    metrics = collect_day_metrics(today, goals)
    history = collect_history(goals, days=7)
    streak = calc_streak(history)
    breakdown = collect_agent_breakdown(today, goals)
    for item in breakdown:
        item["label"] = AGENT_META.get(item["id"], {}).get("label", item["id"])
    return {
        "metrics": {
            "date": metrics.date,
            "tokens": metrics.tokens,
            "tool_calls": metrics.tool_calls,
            "focus_min": metrics.focus_min,
            "token_pct": metrics.token_pct,
            "tool_pct": metrics.tool_pct,
            "focus_pct": metrics.focus_pct,
        },
        "streak": streak,
        "goals": {
            "tokens": goals.tokens,
            "focus_min": goals.focus_min,
            "tool_calls": goals.tool_calls,
        },
        "breakdown": breakdown,
    }


@app.get("/api/history")
def api_history():
    goals = load_config()
    history = collect_history(goals, days=7)
    return [
        {
            "date": m.date,
            "tokens": m.tokens,
            "tool_calls": m.tool_calls,
            "focus_min": m.focus_min,
            "token_pct": m.token_pct,
            "tool_pct": m.tool_pct,
            "focus_pct": m.focus_pct,
        }
        for m in history
    ]


@app.get("/api/goals")
def api_get_goals():
    goals = load_config()
    return {"tokens": goals.tokens, "focus_min": goals.focus_min, "tool_calls": goals.tool_calls}


@app.post("/api/goals")
def api_set_goals(body: GoalsIn):
    if body.tokens < 10_000 or body.focus_min < 1 or body.tool_calls < 1:
        raise HTTPException(status_code=400, detail="Invalid goal values")
    goals = load_config()   # preserve lang and enabled_agents
    goals.tokens    = body.tokens
    goals.focus_min = body.focus_min
    goals.tool_calls = body.tool_calls
    save_config(goals)
    for fn in _goals_changed_callbacks:
        try:
            fn()
        except Exception:
            pass
    return {"tokens": goals.tokens, "focus_min": goals.focus_min, "tool_calls": goals.tool_calls}


@app.get("/api/agents")
def api_get_agents():
    goals = load_config()
    return [
        {
            "id":        aid,
            "label":     meta["label"],
            "dir":       meta["dir"],
            "enabled":   aid in goals.enabled_agents,
            "available": _PROVIDERS[aid].is_available(),
        }
        for aid, meta in AGENT_META.items()
    ]


@app.post("/api/agents")
def api_set_agents(body: AgentsIn):
    valid = set(AGENT_META.keys())
    enabled = [a for a in body.enabled if a in valid]
    if not enabled:
        raise HTTPException(status_code=400, detail="At least one agent must be enabled")
    goals = load_config()
    goals.enabled_agents = enabled
    save_config(goals)
    for fn in _goals_changed_callbacks:
        try:
            fn()
        except Exception:
            pass
    return {"enabled": enabled}


@app.post("/api/lang")
def api_set_lang(body: LangIn):
    if body.lang not in ("zh", "en"):
        raise HTTPException(status_code=400, detail="lang must be zh|en")
    goals = load_config()
    goals.lang = body.lang
    save_config(goals)
    for fn in _goals_changed_callbacks:
        try:
            fn()
        except Exception:
            pass
    return {"lang": body.lang}


@app.get("/api/hourly")
def api_hourly(metric: str = "tokens", d: str = ""):
    """Hourly breakdown for a metric on a given date (defaults to today)."""
    if metric not in ("tokens", "tools", "focus"):
        raise HTTPException(status_code=400, detail="metric must be tokens|tools|focus")
    try:
        target = date.fromisoformat(d) if d else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid date")

    goals = load_config()
    hourly_data = collect_hourly(target, goals)
    day_metrics = collect_day_metrics(target, goals)

    goal_map  = {"tokens": goals.tokens, "tools": goals.tool_calls, "focus": goals.focus_min}
    total_map = {"tokens": day_metrics.tokens, "tools": day_metrics.tool_calls, "focus": day_metrics.focus_min}

    return {
        "metric": metric,
        "date": target.isoformat(),
        "hourly": hourly_data[metric],
        "total": total_map[metric],
        "goal": goal_map[metric],
    }


@app.get("/api/weekly")
def api_weekly():
    """
    Weekly recap: this-week-so-far totals + same-period last week comparison,
    best day per metric, most active hour, per-agent breakdown, streak.
    Week is Mon-Sun in local time (today.weekday() == 0 for Monday).
    """
    goals = load_config()
    today = date.today()
    this_mon = today - timedelta(days=today.weekday())
    last_mon = this_mon - timedelta(days=7)

    days_so_far = (today - this_mon).days + 1
    this_days = [this_mon + timedelta(days=i) for i in range(days_so_far)]
    # Same-weekday slice of last week for like-for-like delta
    prev_days = [last_mon + timedelta(days=i) for i in range(days_so_far)]

    this_metrics = [collect_day_metrics(d, goals) for d in this_days]
    prev_metrics = [collect_day_metrics(d, goals) for d in prev_days]

    totals = {
        "tokens":     sum(m.tokens     for m in this_metrics),
        "tool_calls": sum(m.tool_calls for m in this_metrics),
        "focus_min":  round(sum(m.focus_min for m in this_metrics), 1),
    }
    prev_totals = {
        "tokens":     sum(m.tokens     for m in prev_metrics),
        "tool_calls": sum(m.tool_calls for m in prev_metrics),
        "focus_min":  round(sum(m.focus_min for m in prev_metrics), 1),
    }

    def _delta(curr, prev):
        if prev <= 0:
            return None
        return round((curr - prev) / prev, 4)

    deltas = {
        "tokens":     _delta(totals["tokens"],     prev_totals["tokens"]),
        "tool_calls": _delta(totals["tool_calls"], prev_totals["tool_calls"]),
        "focus_min":  _delta(totals["focus_min"],  prev_totals["focus_min"]),
    }

    def _best(metric_key):
        if not this_metrics:
            return None
        best = max(this_metrics, key=lambda m: getattr(m, metric_key))
        val = getattr(best, metric_key)
        if val <= 0:
            return None
        return {"date": best.date, "value": val}

    best_days = {
        "tokens":     _best("tokens"),
        "focus_min":  _best("focus_min"),
        "tool_calls": _best("tool_calls"),
    }

    # Most active hour: aggregate hourly tokens across the week
    hour_sum = [0] * 24
    for d in this_days:
        h = collect_hourly(d, goals)
        for i in range(24):
            hour_sum[i] += h["tokens"][i]
    most_active_hour = max(range(24), key=lambda i: hour_sum[i]) if any(hour_sum) else None

    # Per-agent totals for the week
    agent_acc: dict[str, dict] = {}
    for d in this_days:
        for item in collect_agent_breakdown(d, goals):
            acc = agent_acc.setdefault(item["id"], {
                "id": item["id"],
                "label": AGENT_META.get(item["id"], {}).get("label", item["id"]),
                "tokens": 0,
                "tool_calls": 0,
                "focus_min": 0.0,
            })
            acc["tokens"]     += item["tokens"]
            acc["tool_calls"] += item["tool_calls"]
            acc["focus_min"]  += item["focus_min"]
    for acc in agent_acc.values():
        acc["focus_min"] = round(acc["focus_min"], 1)
    breakdown = sorted(agent_acc.values(), key=lambda x: -x["tokens"])

    streak = calc_streak(collect_history(goals, days=7))

    return {
        "week_start":         this_mon.isoformat(),
        "week_end_so_far":    today.isoformat(),
        "days_so_far":        days_so_far,
        "totals":             totals,
        "prev_totals":        prev_totals,
        "deltas":             deltas,
        "best_days":          best_days,
        "most_active_hour":   most_active_hour,
        "breakdown":          breakdown,
        "streak":             streak,
        "goals": {
            "tokens":     goals.tokens,
            "focus_min":  goals.focus_min,
            "tool_calls": goals.tool_calls,
        },
        "days": [
            {
                "date":       m.date,
                "tokens":     m.tokens,
                "tool_calls": m.tool_calls,
                "focus_min":  m.focus_min,
                "token_pct":  round(m.token_pct, 4),
                "tool_pct":   round(m.tool_pct, 4),
                "focus_pct":  round(m.focus_pct, 4),
            }
            for m in this_metrics
        ],
    }


# ---------- Static files (after API routes) ----------

static_dir = BASE_DIR / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


# ---------- CLI handlers ----------

def _cli_summary() -> None:
    goals = load_config()
    m = collect_day_metrics(date.today(), goals)
    tokens_m = m.tokens / 1_000_000
    if goals.lang == "zh":
        print(f"今日: {tokens_m:.1f}M · {m.focus_min:.0f}min · {m.tool_calls}次")
    else:
        print(f"Today: {tokens_m:.1f}M · {m.focus_min:.0f}min · {m.tool_calls} calls")


def _cli_json() -> None:
    goals = load_config()
    today = date.today()
    m = collect_day_metrics(today, goals)
    history = collect_history(goals, days=7)
    streak = calc_streak(history)
    breakdown = collect_agent_breakdown(today, goals)
    for item in breakdown:
        item["label"] = AGENT_META.get(item["id"], {}).get("label", item["id"])
    print(_json.dumps({
        "date": m.date,
        "metrics": {
            "tokens": m.tokens,
            "tool_calls": m.tool_calls,
            "focus_min": m.focus_min,
            "token_pct": round(m.token_pct, 4),
            "tool_pct":  round(m.tool_pct,  4),
            "focus_pct": round(m.focus_pct, 4),
        },
        "goals": {
            "tokens": goals.tokens,
            "focus_min": goals.focus_min,
            "tool_calls": goals.tool_calls,
        },
        "streak": streak,
        "breakdown": breakdown,
    }))


# ---------- Entry point ----------

def _open_browser():
    time.sleep(0.8)
    webbrowser.open(f"http://localhost:{PORT}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="vibe-coding-rings",
        description="Local dashboard for AI coding agent usage. "
                    "Without flags, starts the web UI at http://localhost:8765.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--summary", action="store_true",
                       help="print today's metrics as a single line and exit")
    group.add_argument("--json", action="store_true",
                       help="print today's metrics as JSON and exit (for scripts)")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    if args.summary:
        _cli_summary()
        sys.exit(0)
    if args.json:
        _cli_json()
        sys.exit(0)
    print(f"Starting Vibe Coding Rings at http://localhost:{PORT}")
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
