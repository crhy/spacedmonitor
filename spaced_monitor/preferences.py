"""Small per-user preferences; failure to save never interrupts monitoring."""
import json
import os
from pathlib import Path


def path():
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "spaced-monitor" / "preferences.json"


def load_celsius():
    try:
        return json.loads(path().read_text()).get("celsius") is True
    except (OSError, ValueError, AttributeError):
        return False


def save_celsius(value):
    try:
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps({"celsius": bool(value)}) + "\n")
        temporary.replace(target)
        return True
    except OSError:
        return False
