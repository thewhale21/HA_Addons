"""Settings made on the web page rather than in the add-on's options: the
device to follow and how often to read it (Settings), and the log level
(Diagnostics › Debug). Saved
in /data/settings.json. Add your own: a default in DEFAULTS, a check in
_valid, a property."""
from __future__ import annotations

import json
import logging
import os
from typing import Callable, Optional

logger = logging.getLogger(__name__)

LEVELS = ("debug", "info", "warning", "error")
DEFAULTS = {"log_level": "info", "device_id": "", "poll_seconds": 60,  # device_id "": not picked yet
            "calendar": True}  # keep a Home Assistant calendar of the dispatches
DEVICE_ID_MAX = 100
POLL_MIN_S, POLL_MAX_S = 30, 3600


class AppSettings:
    def __init__(self, data_dir: Optional[str] = None, on_change: Optional[Callable[[dict], None]] = None) -> None:
        self._path = os.path.join(data_dir, "settings.json") if data_dir else None
        self.on_change = on_change  # called with what changed
        self.data = dict(DEFAULTS)
        saved = self._load()
        if saved.get("options_adopted"):
            self.data["options_adopted"] = True  # kept, so the options are only copied once
        for key, value in saved.items():
            try:
                self.data.update(self._valid({key: value}))
            except ValueError:
                pass  # an old or bad value: the default stays

    @property
    def log_level(self) -> str:
        return self.data["log_level"]

    @property
    def device_id(self) -> str:
        return self.data["device_id"]

    @property
    def poll_seconds(self) -> int:
        return self.data["poll_seconds"]

    @property
    def calendar(self) -> bool:
        return bool(self.data["calendar"])

    def adopt_options(self, config) -> None:
        """Once: a device_id or poll_seconds set in the add-on's options before 0.3.0 (when they
        moved to the page) is copied here, so it isn't lost."""
        if self.data.get("options_adopted"):
            return
        changes = {}
        if getattr(config, "device_id", "") and not self.device_id:
            changes["device_id"] = config.device_id
        if getattr(config, "poll_seconds", None) and config.poll_seconds != DEFAULTS["poll_seconds"]:
            changes["poll_seconds"] = config.poll_seconds
        self.data.update(self._valid(changes))
        self.data["options_adopted"] = True
        self._save()

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
        if "device_id" in body:
            device = body["device_id"]
            if device is not None and not isinstance(device, str):
                raise ValueError("device_id must be text")
            device = (device or "").strip()
            if len(device) > DEVICE_ID_MAX or any(c.isspace() for c in device):
                raise ValueError("That isn't a device ID")
            out["device_id"] = device
        if "poll_seconds" in body:
            try:
                seconds = int(body["poll_seconds"])
            except (TypeError, ValueError):
                raise ValueError("poll_seconds must be a number of seconds") from None
            if not POLL_MIN_S <= seconds <= POLL_MAX_S:
                raise ValueError(f"Read every {POLL_MIN_S} to {POLL_MAX_S} seconds")
            out["poll_seconds"] = seconds
        if "calendar" in body:
            if not isinstance(body["calendar"], bool):
                raise ValueError("calendar must be true or false")
            out["calendar"] = body["calendar"]
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
