from __future__ import annotations

import json
import logging
import os
import random

logger = logging.getLogger(__name__)

_ENERGY_FILE = "energy_register.json"
_SERIAL_FILE = "serial_number.json"
_QUEUE_FILE = "offline_queue.json"
_TRANSACTION_FILE = "active_transaction.json"
_CURRENT_FILE = "current_setting.json"
_PLUG_FILE = "plugged_in.json"
_RAMP_FILE = "ramp_setting.json"


class Persistence:
    def __init__(self, data_dir: str = "/data"):
        self._data_dir = data_dir

    @property
    def data_dir(self) -> str:
        return self._data_dir

    # Files are written atomically: the data goes to a temp file which is
    # flushed to disk and then renamed over the target in one step, so a
    # power cut mid-write leaves the old file or the new one, never half of
    # one. A ".bak" copy of the previous good version is kept as well; if the
    # main file is still unreadable, the backup is used instead of the
    # default (for the energy register, the default would be 0).

    def _read(self, filename: str, key: str, default):
        path = os.path.join(self._data_dir, filename)
        for candidate in (path, path + ".bak"):
            try:
                with open(candidate) as f:
                    data = json.load(f)
            except FileNotFoundError:
                continue
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                logger.warning("%s is unreadable or corrupt", candidate)
                continue
            if not isinstance(data, dict):
                logger.warning("%s has unexpected content", candidate)
                continue
            if candidate != path:
                logger.warning("Using backup %s (main file missing or corrupt)", candidate)
            return data.get(key, default)
        return default

    def _write(self, filename: str, key: str, value):
        path = os.path.join(self._data_dir, filename)
        tmp = f"{path}.tmp"
        try:
            # 1. New content fully on disk first
            with open(tmp, "w") as f:
                json.dump({key: value}, f, default=str)
                f.flush()
                os.fsync(f.fileno())
            # 2. Current file becomes the backup, if it's valid (a corrupt
            #    main file must never overwrite a good backup)
            if self._is_valid(path):
                os.replace(path, path + ".bak")
            # 3. Swap the new file in, in one step
            os.replace(tmp, path)
            self._fsync_dir()
        except OSError:
            logger.warning("Failed to write %s", path, exc_info=True)

    @staticmethod
    def _is_valid(path: str) -> bool:
        try:
            with open(path) as f:
                return isinstance(json.load(f), dict)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return False

    def _fsync_dir(self) -> None:
        """Make the renames durable too (best effort; not supported everywhere)."""
        try:
            fd = os.open(self._data_dir, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    def load_energy_register_wh(self) -> int:
        return self._read(_ENERGY_FILE, "energy_wh", 0)

    def save_energy_register_wh(self, value: int) -> None:
        self._write(_ENERGY_FILE, "energy_wh", value)

    def seed_energy_register_wh(self, value: int) -> bool:
        """Set the register to `value` only if that's higher than what's stored.

        A lifetime meter must never go backwards, so a seed value left in the
        add-on options (or entered too low) is ignored. Returns True if applied.
        """
        current = self.load_energy_register_wh()
        if value <= current:
            return False
        self.save_energy_register_wh(value)
        return True

    def load_offline_queue(self) -> list:
        """Transaction messages held while offline (see ChargePoint._send_tx)."""
        queue = self._read(_QUEUE_FILE, "messages", [])
        return queue if isinstance(queue, list) else []

    def save_offline_queue(self, messages: list) -> None:
        self._write(_QUEUE_FILE, "messages", messages)

    def load_active_transaction(self) -> dict | None:
        """The transaction open at the last save (None if none was open)."""
        tx = self._read(_TRANSACTION_FILE, "transaction", None)
        return tx if isinstance(tx, dict) else None

    def save_active_transaction(self, transaction: dict | None) -> None:
        self._write(_TRANSACTION_FILE, "transaction", transaction)

    def load_current_setting(self) -> dict | None:
        """The max current (web page or Home Assistant): {"amps": N}."""
        setting = self._read(_CURRENT_FILE, "current", None)
        return setting if isinstance(setting, dict) and "amps" in setting else None

    def save_current_setting(self, setting: dict) -> None:
        self._write(_CURRENT_FILE, "current", setting)

    def load_app_settings(self) -> dict:
        """Settings made on the web page (src/app_settings.py)."""
        settings = self._read("settings.json", "settings", {})
        return settings if isinstance(settings, dict) else {}

    def save_app_settings(self, settings: dict) -> None:
        self._write("settings.json", "settings", settings)

    def load_ramp_setting(self) -> dict | None:
        """Start delay / ramp-up set on the web page: {"start_delay_s", "ramp_up_s"}."""
        setting = self._read(_RAMP_FILE, "ramp", None)
        return setting if isinstance(setting, dict) else None

    def save_ramp_setting(self, setting: dict) -> None:
        self._write(_RAMP_FILE, "ramp", setting)

    def load_plugged_in(self) -> bool:
        """Whether the car was plugged in at the last save (the cable stays in across a restart)."""
        return self._read(_PLUG_FILE, "plugged_in", False) is True

    def save_plugged_in(self, plugged_in: bool) -> None:
        self._write(_PLUG_FILE, "plugged_in", bool(plugged_in))

    def load_serial_number(self) -> str:
        serial = self._read(_SERIAL_FILE, "serial", "")
        if not serial:
            serial = str(random.randint(100000, 999999))
            self.save_serial_number(serial)
            logger.info("Generated charger serial number: %s", serial)
        return serial

    def save_serial_number(self, value: str) -> None:
        self._write(_SERIAL_FILE, "serial", value)
