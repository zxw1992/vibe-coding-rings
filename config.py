from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass, asdict

PROJECT_DIR = Path(__file__).parent
CONFIG_FILE = PROJECT_DIR / "config.json"

CLAUDE_DIR = Path.home() / ".claude"
HISTORY_FILE = CLAUDE_DIR / "history.jsonl"
PROJECTS_DIR = CLAUDE_DIR / "projects"

DEFAULT_GOALS = {
    "tokens": 1_000_000,
    "focus_min": 120,
    "tool_calls": 50,
}


@dataclass
class Goals:
    tokens: int = 1_000_000
    focus_min: int = 120
    tool_calls: int = 50
    lang: str = "zh"


def load_config() -> Goals:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            return Goals(
                tokens=int(data.get("tokens", DEFAULT_GOALS["tokens"])),
                focus_min=int(data.get("focus_min", DEFAULT_GOALS["focus_min"])),
                tool_calls=int(data.get("tool_calls", DEFAULT_GOALS["tool_calls"])),
                lang=str(data.get("lang", "zh")),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    return Goals()


def save_config(goals: Goals) -> None:
    CONFIG_FILE.write_text(json.dumps(asdict(goals), indent=2))
