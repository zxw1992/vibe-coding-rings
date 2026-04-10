"""
Vibe Coding Rings — system tray / menubar app

macOS         : python menubar.py   (requires: pip install rumps)
Windows/Linux : python menubar.py   (requires: pip install pystray pillow)
"""
from __future__ import annotations
import platform
import sys
import threading
import webbrowser
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import uvicorn
from config import load_config
from data_collector import collect_day_metrics, collect_history, calc_streak

PORT = 8765
REFRESH_INTERVAL = 60  # seconds
_PLATFORM = platform.system()


# ── Formatters (shared) ──────────────────────────────────────────────────────

def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        v = n / 1_000_000
        return f"{v:.1f}M" if v % 1 else f"{v:.0f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _fmt_goal_tokens(n: int) -> str:
    return _fmt_tokens(n)


def _fmt_pct(pct: float) -> str:
    return f"{round(pct * 100)}%"


# ── Server (shared) ──────────────────────────────────────────────────────────

def _start_server() -> None:
    from main import app
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


# ═══════════════════════════════════════════════════════════════════════════════
# macOS — rumps (native menubar, custom NSView rings)
# ═══════════════════════════════════════════════════════════════════════════════

if _PLATFORM == "Darwin":
    import rumps
    from AppKit import NSView, NSColor, NSBezierPath

    # (radius, sRGB r, g, b) — colours match style.css
    _RING_DEFS = [
        (25.0, 1.000, 0.216, 0.373),   # outer  — red   #FF375F  (consume)
        (17.5, 0.188, 0.820, 0.345),   # middle — green #30D158  (focus)
        (10.0, 0.039, 0.518, 1.000),   # inner  — blue  #0A84FF  (action)
    ]
    _TRACK_W = 5.5
    _VIEW_H  = 68
    _VIEW_W  = 300

    class _RingsMenuView(NSView):
        """Custom NSView drawn as three concentric activity rings inside a menu item."""

        _pcts: tuple = (0.0, 0.0, 0.0)

        def drawRect_(self, rect):
            NSColor.clearColor().set()
            NSBezierPath.fillRect_(rect)
            cx = self.bounds().size.width  / 2
            cy = self.bounds().size.height / 2
            for (radius, r, g, b), pct in zip(_RING_DEFS, self._pcts):
                capped = min(pct, 1.0)
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    r * 0.18, g * 0.18, b * 0.18, 1.0
                ).set()
                track = NSBezierPath.bezierPath()
                track.setLineWidth_(_TRACK_W)
                track.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
                    (cx, cy), radius, 0, 360
                )
                track.stroke()
                if capped <= 0.001:
                    continue
                NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0).set()
                arc = NSBezierPath.bezierPath()
                arc.setLineWidth_(_TRACK_W)
                arc.setLineCapStyle_(1)   # NSRoundLineCapStyle
                if capped >= 1.0:
                    arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
                        (cx, cy), radius, 0, 360
                    )
                else:
                    arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                        (cx, cy), radius, 90, 90 - capped * 360, True
                    )
                arc.stroke()

    class _MacMenubarApp(rumps.App):
        def __init__(self):
            super().__init__(
                name="Vibe Coding Rings",
                title="⭕",
                quit_button=None,
            )
            self._item_header = rumps.MenuItem("VIBE CODING RINGS")
            self._item_header.enabled = False

            self._item_rings = rumps.MenuItem("")
            self._item_rings.enabled = False
            self._rings_view = _RingsMenuView.alloc().initWithFrame_(
                ((0, 0), (_VIEW_W, _VIEW_H))
            )
            self._item_rings._menuitem.setView_(self._rings_view)

            self._item_tokens = rumps.MenuItem("—", callback=lambda _: self._open_detail("tokens"))
            self._item_focus  = rumps.MenuItem("—", callback=lambda _: self._open_detail("focus"))
            self._item_tools  = rumps.MenuItem("—", callback=lambda _: self._open_detail("tools"))

            self._item_streak = rumps.MenuItem("—")
            self._item_streak.enabled = False

            self._item_open = rumps.MenuItem("—", callback=lambda _: webbrowser.open(f"http://localhost:{PORT}"))
            self._item_quit = rumps.MenuItem("—", callback=rumps.quit_application)

            self.menu = [
                self._item_header,
                None,
                self._item_rings,
                None,
                self._item_tokens,
                self._item_focus,
                self._item_tools,
                None,
                self._item_streak,
                None,
                self._item_open,
                None,
                self._item_quit,
            ]

            threading.Thread(target=_start_server, daemon=True).start()
            threading.Timer(1.2, self._register_goal_callback).start()
            threading.Timer(1.5, self._refresh_stats).start()

        def _register_goal_callback(self) -> None:
            try:
                from main import register_goals_changed
                register_goals_changed(self._refresh_stats)
            except Exception as e:
                print(f"[VCR] Could not register goal callback: {e}", file=sys.stderr)

        @rumps.timer(REFRESH_INTERVAL)
        def _timer_refresh(self, _sender) -> None:
            self._refresh_stats()

        def _refresh_stats(self) -> None:
            try:
                goals   = load_config()
                zh      = (goals.lang == "zh")
                today   = date.today()
                metrics = collect_day_metrics(today, goals)
                history = collect_history(goals, days=7)
                streak  = calc_streak(history)

                lowest = min(metrics.token_pct, metrics.focus_pct, metrics.tool_pct)
                self.title = "⬤" if lowest >= 1.0 else f"{round(lowest * 100)}%"

                self._rings_view._pcts = (metrics.token_pct, metrics.focus_pct, metrics.tool_pct)

                tok_str  = _fmt_tokens(metrics.tokens)
                tok_goal = _fmt_goal_tokens(goals.tokens)
                foc_str  = f"{round(metrics.focus_min)}"
                tol_str  = str(metrics.tool_calls)

                if zh:
                    self._item_tokens.title = f"消耗   {tok_str} / {tok_goal}  ({_fmt_pct(metrics.token_pct)})"
                    self._item_focus.title  = f"专注   {foc_str} / {goals.focus_min} 分钟  ({_fmt_pct(metrics.focus_pct)})"
                    self._item_tools.title  = f"行动   {tol_str} / {goals.tool_calls} 次  ({_fmt_pct(metrics.tool_pct)})"
                    self._item_streak.title = f"🔥  连续达标 {streak} 天"
                    self._item_open.title   = "打开看板 ↗"
                    self._item_quit.title   = "退出"
                else:
                    self._item_tokens.title = f"Consume   {tok_str} / {tok_goal}  ({_fmt_pct(metrics.token_pct)})"
                    self._item_focus.title  = f"Focus   {foc_str} / {goals.focus_min} min  ({_fmt_pct(metrics.focus_pct)})"
                    self._item_tools.title  = f"Action   {tol_str} / {goals.tool_calls} calls  ({_fmt_pct(metrics.tool_pct)})"
                    self._item_streak.title = f"🔥  {streak}-day streak"
                    self._item_open.title   = "Open Dashboard ↗"
                    self._item_quit.title   = "Quit"

            except Exception as e:
                self.title = "⭕"
                print(f"[VCR] Stats refresh error: {e}", file=sys.stderr)

        def _open_detail(self, metric: str) -> None:
            webbrowser.open(f"http://localhost:{PORT}/#detail={metric}")

    _AppClass = _MacMenubarApp


# ═══════════════════════════════════════════════════════════════════════════════
# Windows / Linux — pystray
# ═══════════════════════════════════════════════════════════════════════════════

else:
    import pystray
    from PIL import Image, ImageDraw

    def _make_icon_image() -> Image.Image:
        """Three concentric ring outlines — matches the app colour palette."""
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.arc([ 2,  2, 62, 62], 0, 360, fill=(255,  55,  95), width=7)  # red outer
        d.arc([14, 14, 50, 50], 0, 360, fill=( 48, 209,  88), width=7)  # green mid
        d.arc([24, 24, 40, 40], 0, 360, fill=( 10, 132, 255), width=7)  # blue inner
        return img

    class _CrossTrayApp:
        def __init__(self):
            self._tokens_text = "—"
            self._focus_text  = "—"
            self._tools_text  = "—"
            self._streak_text = "—"
            self._open_text   = "Open Dashboard ↗"
            self._quit_text   = "Quit"

            self._icon = pystray.Icon(
                "Vibe Coding Rings",
                _make_icon_image(),
                "Vibe Coding Rings",
                menu=pystray.Menu(
                    pystray.MenuItem(lambda item: self._tokens_text, lambda icon, item: self._open_detail("tokens")),
                    pystray.MenuItem(lambda item: self._focus_text,  lambda icon, item: self._open_detail("focus")),
                    pystray.MenuItem(lambda item: self._tools_text,  lambda icon, item: self._open_detail("tools")),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(lambda item: self._streak_text, None, enabled=False),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(lambda item: self._open_text,   lambda icon, item: webbrowser.open(f"http://localhost:{PORT}")),
                    pystray.MenuItem(lambda item: self._quit_text,   lambda icon, item: self._icon.stop()),
                ),
            )

            threading.Thread(target=_start_server, daemon=True).start()
            threading.Timer(1.2, self._register_goal_callback).start()
            threading.Timer(1.5, self._refresh_stats).start()
            threading.Thread(target=self._refresh_loop, daemon=True).start()

        def _refresh_loop(self) -> None:
            import time
            while True:
                time.sleep(REFRESH_INTERVAL)
                self._refresh_stats()

        def _register_goal_callback(self) -> None:
            try:
                from main import register_goals_changed
                register_goals_changed(self._refresh_stats)
            except Exception as e:
                print(f"[VCR] Could not register goal callback: {e}", file=sys.stderr)

        def _refresh_stats(self) -> None:
            try:
                goals   = load_config()
                zh      = (goals.lang == "zh")
                today   = date.today()
                metrics = collect_day_metrics(today, goals)
                history = collect_history(goals, days=7)
                streak  = calc_streak(history)

                tok_str  = _fmt_tokens(metrics.tokens)
                tok_goal = _fmt_goal_tokens(goals.tokens)
                foc_str  = f"{round(metrics.focus_min)}"
                tol_str  = str(metrics.tool_calls)

                if zh:
                    self._tokens_text = f"消耗   {tok_str} / {tok_goal}  ({_fmt_pct(metrics.token_pct)})"
                    self._focus_text  = f"专注   {foc_str} / {goals.focus_min} 分钟  ({_fmt_pct(metrics.focus_pct)})"
                    self._tools_text  = f"行动   {tol_str} / {goals.tool_calls} 次  ({_fmt_pct(metrics.tool_pct)})"
                    self._streak_text = f"🔥  连续达标 {streak} 天"
                    self._open_text   = "打开看板 ↗"
                    self._quit_text   = "退出"
                else:
                    self._tokens_text = f"Consume   {tok_str} / {tok_goal}  ({_fmt_pct(metrics.token_pct)})"
                    self._focus_text  = f"Focus   {foc_str} / {goals.focus_min} min  ({_fmt_pct(metrics.focus_pct)})"
                    self._tools_text  = f"Action   {tol_str} / {goals.tool_calls} calls  ({_fmt_pct(metrics.tool_pct)})"
                    self._streak_text = f"🔥  {streak}-day streak"
                    self._open_text   = "Open Dashboard ↗"
                    self._quit_text   = "Quit"

                self._icon.update_menu()

            except Exception as e:
                print(f"[VCR] Stats refresh error: {e}", file=sys.stderr)

        def _open_detail(self, metric: str) -> None:
            webbrowser.open(f"http://localhost:{PORT}/#detail={metric}")

        def run(self) -> None:
            self._icon.run()

    _AppClass = _CrossTrayApp


if __name__ == "__main__":
    _AppClass().run()
