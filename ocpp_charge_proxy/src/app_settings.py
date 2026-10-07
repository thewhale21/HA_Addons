"""Settings made on the web page that used to be add-on options: the log
level (Diagnostics › Debug) and continuing a session after a restart
(Settings › Controls). Saved in settings.json in the data folder. The max
current is saved separately (src/persistence.py, current_setting.json)."""
from __future__ import annotations

import logging
from typing import Callable, Optional

LEVELS = ("debug", "info", "warning", "error")
DEFAULTS = {"log_level": "info", "continue_session": True}


class AppSettings:
    def __init__(self, persistence=None, on_change: Optional[Callable[[dict], None]] = None) -> None:
        self._persistence = persistence
        self.on_change = on_change  # called with what changed
        self.data = dict(DEFAULTS)
        saved = persistence.load_app_settings() if persistence is not None else {}
        for key, value in (saved or {}).items():
            try:
                self.data.update(self._valid({key: value}))
            except ValueError:
                pass

    @property
    def log_level(self) -> str:
        return self.data["log_level"]

    @property
    def continue_session(self) -> bool:
        return self.data["continue_session"]

    def apply_log_level(self) -> None:
        logging.getLogger().setLevel(getattr(logging, self.log_level.upper()))

    @staticmethod
    def _valid(body: dict) -> dict:
        out = {}
        if "log_level" in body:
            level = str(body["log_level"] or "").lower()
            if level not in LEVELS:
                raise ValueError("Log level must be one of: " + ", ".join(LEVELS))
            out["log_level"] = level
        if "continue_session" in body:
            if not isinstance(body["continue_session"], bool):
                raise ValueError("continue_session must be true or false")
            out["continue_session"] = body["continue_session"]
        return out

    def update(self, body) -> dict:
        if not isinstance(body, dict):
            raise ValueError("Send a JSON object")
        changes = self._valid(body)
        if not changes:
            raise ValueError("Nothing to change: log_level or continue_session")
        self.data.update(changes)
        if self._persistence is not None:
            self._persistence.save_app_settings(self.data)
        if self.on_change is not None:
            self.on_change(changes)
        return dict(self.data)
