"""Settings made on the web page rather than in the add-on's options: the
statistics' settings (Settings tab) and the log level (Diagnostics › Debug).
Saved in /data/settings.json."""
from __future__ import annotations

import json
import logging
import os
from typing import Callable, Optional

logger = logging.getLogger(__name__)

LEVELS = ("debug", "info", "warning", "error")
DEFAULTS = {
    "log_level": "info",
    "min_trip_mi": 2.0,  # shorter trips aren't counted in the efficiency (src/evstats.py)
    "usable_kwh": 0.0,  # the battery's usable capacity; 0 = measured, or the car's sensor
}
NUMBERS = {"min_trip_mi": (0.1, 50), "usable_kwh": (0, 250)}


class AppSettings:
    def __init__(self, data_dir: Optional[str] = None, on_change: Optional[Callable[[dict], None]] = None) -> None:
        self._path = os.path.join(data_dir, "settings.json") if data_dir else None
        self.on_change = on_change  # called with what changed
        self.data = dict(DEFAULTS)
        for key, value in self._load().items():
            try:
                self.data.update(self._valid({key: value}))
            except ValueError:
                pass  # an old or bad value: the default stays

    @property
    def log_level(self) -> str:
        return self.data["log_level"]

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
        for key, (low, high) in NUMBERS.items():
            if key in body:
                try:
                    value = float(body[key])
                except (TypeError, ValueError):
                    raise ValueError(f"{key} must be a number") from None
                if not low <= value <= high:
                    raise ValueError(f"{key} must be between {low:g} and {high:g}")
                out[key] = value
        return out

    def update(self, body) -> dict:
        if not isinstance(body, dict):
            raise ValueError("Send a JSON object")
        changes = self._valid(body)
        if not changes:
            raise ValueError("Nothing to change: " + ", ".join(DEFAULTS))
        self.data.update(changes)
        self._save()
        if "log_level" in changes:
            self.apply_log_level()  # straight away, from the web page or the API
        if self.on_change is not None:
            self.on_change(changes)
        return dict(self.data)

    def _load(self) -> dict:
        if not self._path:
            return {}
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception:
            logger.warning("Settings %s are unreadable: using the defaults", self._path)
            return {}

    def _save(self) -> None:
        if not self._path:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, self._path)
        except Exception:
            logger.warning("Could not save the settings", exc_info=True)
