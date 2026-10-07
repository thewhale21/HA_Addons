"""Settings made on the web page (Settings and Diagnostics › Debug): the
tuning, notifications, "watch only" and the log level. Saved in
/data/settings.json. Add your own: a default in DEFAULTS and a check in
_valid (NUMBERS, BOOLS or LISTS cover most)."""
from __future__ import annotations

import json
import logging
import os
from typing import Callable, Optional

logger = logging.getLogger(__name__)

from src.controller import TUNING_DEFAULTS
from src.manager import LIST_DEFAULTS
from src.rates import RATE_DEFAULTS
from src.stats import STATS_DEFAULTS

LEVELS = ("debug", "info", "warning", "error")
# key -> (lowest, highest)
NUMBERS = {
    "restart_wait_s": (0, 3600),
    "house_battery_kw": (0, 20),
    "house_grid_kw": (0, 20),
    "export_kw": (0, 50),
    "export_hold_s": (0, 600),
    "margin_pct": (0, 20),
    "press_gap_s": (10, 600),
    "rate_kw": (0, 100),
    "rate_full_kw": (0, 100),
    "rate_full_soc_pct": (0, 100),
    "house_rate_kw": (0, 100),
    "car_rate_kw": (0, 100),
    "capacity_min_span_pct": (2, 100),
    "clean_share_pct": (0, 100),
    "inverter_efficiency_pct": (50, 100),
    "dropout_alert": (0, 50),
}
BOOLS = ("observe_only", "flip_inverter_power")
LISTS = tuple(LIST_DEFAULTS)
DEFAULTS = {
    "log_level": "info",
    **TUNING_DEFAULTS,
    **RATE_DEFAULTS,
    **STATS_DEFAULTS,
    "observe_only": False,  # decide and log, but don't press the buttons
    "notify_service": "",  # e.g. notify.mobile_app_phone: told when it starts or stops the charger
    "dropout_alert": 0,  # ...and when the car stops discharging by itself this many times in a day (0: never)
    **{k: list(v) for k, v in LIST_DEFAULTS.items()},
}


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
        unknown = [k for k in body if k not in DEFAULTS]
        if unknown:
            raise ValueError("Unknown setting: " + ", ".join(unknown))
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
                out[key] = int(value) if value.is_integer() and key.endswith("_s") else value
        for key in BOOLS:
            if key in body:
                if not isinstance(body[key], bool):
                    raise ValueError(f"{key} must be true or false")
                out[key] = body[key]
        if "notify_service" in body:
            name = str(body["notify_service"] or "").strip()
            if name and not name.startswith("notify."):
                name = "notify." + name
            if name and not name[7:].replace("_", "a").isalnum():
                raise ValueError("The notify service looks like notify.mobile_app_your_phone")
            out["notify_service"] = name
        for key in LISTS:
            if key in body:
                value = body[key]
                if isinstance(value, str):
                    value = value.split(",")
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raise ValueError(f"{key} must be a list of states")
                value = [v.strip() for v in value if v.strip()]
                if not value:
                    raise ValueError(f"{key} needs at least one state")
                out[key] = value
        return out

    def update(self, body) -> dict:
        if not isinstance(body, dict):
            raise ValueError("Send a JSON object")
        changes = self._valid(body)
        if not changes:
            raise ValueError("Nothing to change")
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
