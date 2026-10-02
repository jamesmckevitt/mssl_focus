"""Small per-user settings file: last folder, recent sessions, window layout."""

import json
import os
import sys
from pathlib import Path

MAX_RECENT = 8


def config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "mssl_focus"


class Config:
    def __init__(self, path=None):
        self.path = Path(path) if path else config_dir() / "config.json"
        self.data = {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data = loaded
        except (OSError, ValueError):
            pass

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        if self.data.get(key) == value:
            return
        self.data[key] = value
        self.save()

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass  # settings are a convenience; never block the app on them

    def add_recent(self, session_path):
        path = os.path.abspath(session_path)
        recent = [p for p in self.data.get("recent_sessions", []) if p != path]
        recent.insert(0, path)
        self.set("recent_sessions", recent[:MAX_RECENT])

    def recent(self):
        return [p for p in self.data.get("recent_sessions", []) if os.path.isfile(p)]
