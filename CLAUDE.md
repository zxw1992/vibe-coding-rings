# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A local macOS dashboard that visualises Claude Code usage as three animated concentric rings — inspired by Apple Activity Rings. All data is read passively from `~/.claude/` with no external services or API keys required.

**Three rings:**
- ⚡ 消耗 / Consume (red) — tokens consumed today
- ⏱ 专注 / Focus (green) — active AI session minutes today
- ⚙️ 行动 / Action (blue) — tool calls executed today

## Running the app

```bash
# Web dashboard only (opens browser automatically at http://localhost:8765)
python main.py

# macOS menubar app (shows stats in system tray, also serves the web UI)
python menubar.py
```

## Testing the data layer

```bash
# Print today's metrics and 7-day history to stdout — fast sanity check
python data_collector.py
```

## API endpoints

All served by FastAPI on port 8765, must be defined **before** the static file mount in `main.py`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/today` | Today's metrics + streak + goals |
| GET | `/api/history` | Last 7 days of `DayMetrics` |
| GET | `/api/goals` | Current goal values |
| POST | `/api/goals` | Save new goal values |
| POST | `/api/lang` | Save language preference (`{"lang": "zh"\|"en"}`) |
| GET | `/api/hourly?metric=tokens\|tools\|focus&d=YYYY-MM-DD` | 24-bucket hourly breakdown |

## Architecture

```
config.py          Goals dataclass + load/save config.json
data_collector.py  All ~/.claude/ parsing — no FastAPI imports
main.py            FastAPI server + browser auto-launch
menubar.py         rumps menubar app; starts FastAPI in a daemon thread
static/
  index.html       Single-page app; two "pages" (main + detail overlay)
  style.css        Dark theme, Apple Fitness colour palette
  rings.js         All frontend logic: rings, history, tooltip, detail page, goals
```

### Data flow

`data_collector.py` reads two sources:

1. **`~/.claude/projects/**/*.jsonl`** — session files, one per conversation. Each `assistant` entry has a `message.usage` field (tokens) and `tool_use` content blocks (tool calls). Filtered by mtime (±2 days) then by UTC ms range.

2. **`~/.claude/history.jsonl`** — one entry per user message with epoch-ms `timestamp` and `sessionId`. Used for focus-time calculation: messages are grouped by session, consecutive pairs with gap >30 min start a new "focus block", each block gets +5 min trail credit.

### Critical timezone invariant

**All session JSONL timestamps are UTC** (`"2026-04-03T16:37Z"`), but the app deals in **local calendar dates**. Every filtering function converts the local date to a UTC ms range via `_local_date_to_utc_ms_range()` in `data_collector.py`. Never use `date.isoformat()` as a string prefix to filter session timestamps — it will silently miss data for UTC+N timezones.

Similarly, in the frontend, always use `new Date().toLocaleDateString('en-CA')` (local YYYY-MM-DD) — never `new Date().toISOString().slice(0,10)` (UTC date).

### Caching

`collect_day_metrics()` caches by `(minute_bucket, date, goals_tuple)`. Goals are part of the key so changing a goal immediately produces updated percentages on the next request — no manual cache invalidation needed.

### Language system

Language preference (`zh` / `en`) is stored in three places that must stay in sync:
- `localStorage` key `vcc_lang` — read on page load
- `config.json` field `lang` — persisted via `POST /api/lang`
- `Goals.lang` in Python — read by `menubar.py` on every stats refresh

`applyLang(lang, syncServer)` in `rings.js` toggles `display:none` on all `.zh` / `.en` sibling spans and, when `syncServer=true`, calls `POST /api/lang`. The server fires `_goals_changed_callbacks` so the menubar updates immediately without waiting for its 60-second timer.

All bilingual HTML uses the `<span class="zh">` / `<span class="en">` sibling pattern — never `data-zh`/`data-en` attributes, which `applyLang()` does not handle.

### Detail page (hourly drill-down)

Clicking any ring-stat row slides in `#page-detail` (CSS `translateX` transition). It fetches `/api/hourly`, then `renderHourlyChart()` builds the SVG bar chart programmatically with staggered entrance animation (12 ms delay per bar). The chart x-axis is in **local time** hours because `collect_hourly()` uses `_ms_to_local_hour()`.

## Dependencies

```
fastapi>=0.100
uvicorn>=0.20
rumps>=0.4.0    # macOS menubar only — not needed for web-only mode
```

`rumps` depends on `pyobjc` and is macOS-only. For cross-platform system tray support, replace `menubar.py` with `pystray` (same FastAPI server thread pattern).

## User-configurable goals

Stored in `config.json` (project root, git-ignored). Defaults: 1 M tokens / 120 min focus / 50 tool calls per day. Goals are editable via sliders or number inputs in the "每日目标 / Daily Goals" panel; changes POST to `/api/goals` on slider release or Enter key in the number input.

The token goal number input displays in **M units** (millions). `_numDisplay(raw, scale)` and `_numParse(display, scale)` in `rings.js` handle the conversion (scale=1_000_000 for tokens, scale=1 for others). The slider range for tokens extends to 50 M raw, while the number input allows any value ≥ 0.1 M.

### Menubar–WebUI goal sync

Both `POST /api/goals` and `POST /api/lang` call every function registered via `register_goals_changed()` in `main.py`. `menubar.py` registers `self._refresh_stats` during startup so goal or language changes in the web UI propagate to the menubar immediately. Menubar metric items are clickable and open `http://localhost:8765/#detail={metric}` directly to the detail page.

### Menubar display

Menu item text is single-language (zh or en) based on `Goals.lang` from `config.json`. Item labels are rebuilt on every `_refresh_stats()` call — no pre-built string constants. Metric lines format: `消耗   1.4M / 1M  (140%)` (plain text, no leading symbols).
