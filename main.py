from __future__ import annotations
import threading
import time
import webbrowser
from datetime import date
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import Goals, load_config, save_config
from data_collector import collect_day_metrics, collect_history, calc_streak, collect_hourly

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


# ---------- API routes (must be before static mount) ----------

@app.get("/api/today")
def api_today():
    goals = load_config()
    today = date.today()
    metrics = collect_day_metrics(today, goals)
    history = collect_history(goals, days=7)
    streak = calc_streak(history)
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
    goals = Goals(tokens=body.tokens, focus_min=body.focus_min, tool_calls=body.tool_calls)
    save_config(goals)
    for fn in _goals_changed_callbacks:
        try:
            fn()
        except Exception:
            pass
    return {"tokens": goals.tokens, "focus_min": goals.focus_min, "tool_calls": goals.tool_calls}


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
    hourly_data = collect_hourly(target)
    day_metrics = collect_day_metrics(target, goals)

    goal_map = {"tokens": goals.tokens, "tools": goals.tool_calls, "focus": goals.focus_min}
    total_map = {"tokens": day_metrics.tokens, "tools": day_metrics.tool_calls, "focus": day_metrics.focus_min}

    return {
        "metric": metric,
        "date": target.isoformat(),
        "hourly": hourly_data[metric],
        "total": total_map[metric],
        "goal": goal_map[metric],
        "goal_per_hour": round(goal_map[metric] / 24, 2),
    }


# ---------- Static files (after API routes) ----------

static_dir = BASE_DIR / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


# ---------- Entry point ----------

def _open_browser():
    time.sleep(0.8)
    webbrowser.open(f"http://localhost:{PORT}")


if __name__ == "__main__":
    print(f"Starting Vibe Coding Rings at http://localhost:{PORT}")
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
