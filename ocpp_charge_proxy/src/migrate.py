"""Moving the add-on's settings (and, if you like, its history) to another
install of it, e.g. from the ocpp_charge_proxy repository's add-on to the
HA_Addons one, without entering them again: Diagnostics › Move to another
install.

- export(): one JSON file with the add-on's options (its Configuration tab:
  server, chargepoint ID, password unless left out, charger details), the
  files in /data it keeps your settings in (the schedule, sensors, page
  settings, max current, the simulated car, the charger's serial and its
  lifetime energy register), your supplier changes (/config/suppliers.json)
  and, if asked, the history (the sessions and the OCPP message log).
- check(): what a file holds, for the page to show before anything changes
  (raises ValueError if it isn't one of these, or it's damaged).
- stage() / apply_pending(): the import. The file is saved as
  /data/import_pending.json and used at the next start, before anything
  else reads /data, so nothing running overwrites it; the add-on's options
  are set through the Supervisor and it restarts (src/__main__.py). The
  energy register never goes backwards: the higher of the two is kept.

Not moved: what's only for the moment (an open transaction, held offline
messages, when the schedule last looked, Plugged In), and the charts, which
are Home Assistant's own history of the add-on's sensors (they're kept, with
the same entity IDs).
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Optional

from src import jsonfile

logger = logging.getLogger(__name__)

FORMAT = "ocpp_charge_proxy_settings"
FORMAT_VERSION = 1
PENDING = "import_pending.json"
# The files in /data with your settings (always moved) and the history (if asked)
SETTINGS_FILES = ("automation.json", "sensors.json", "settings.json", "current_setting.json",
                  "ramp_setting.json", "serial_number.json", "energy_register.json")
HISTORY_FILES = ("sessions.json", "messages.json")
# The add-on's options moved (its Configuration tab); not initial_energy_wh (a one-off seed)
OPTIONS = ("server_hostname", "chargepoint_id", "password", "charger_model", "charger_vendor",
           "charger_serial", "firmware_version")
NAMES = {"automation.json": "the schedule and automations", "sensors.json": "your sensors and supplier settings",
         "settings.json": "the page's settings", "current_setting.json": "the max current",
         "ramp_setting.json": "the simulated car", "serial_number.json": "the charger's serial number",
         "energy_register.json": "the lifetime energy register", "sessions.json": "the session history",
         "messages.json": "the OCPP message log"}


def _read(path: str) -> Optional[dict]:
    found: dict = {}
    return found if jsonfile.load(path, os.path.basename(path), found.update) else None


def export(data_dir: str, version: str, history: bool = True, password: bool = True,
           options_path: Optional[str] = None, suppliers_path: Optional[str] = None) -> dict:
    """Everything to move, as one dict (saved by the page as a .json file)."""
    options = _read(options_path or os.path.join(data_dir, "options.json")) or {}
    options = {k: options[k] for k in OPTIONS if k in options}
    if not password:
        options.pop("password", None)
    files = {}
    for name in SETTINGS_FILES + (HISTORY_FILES if history else ()):
        data = _read(os.path.join(data_dir, name))
        if data is not None:
            files[name] = data
    supplier_changes = _read(suppliers_path) if suppliers_path and os.path.exists(suppliers_path) else None
    return {"format": FORMAT, "format_version": FORMAT_VERSION, "addon_version": version,
            "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "options": options, "files": files, "supplier_changes": supplier_changes,
            "with_history": bool(history), "with_password": "password" in options}


def check(bundle) -> dict:
    """What a file holds, for the page: {"addon_version", "exported_at", "items": [...],
    "options": [names], "with_password", "with_history", "energy_wh", "serial"}. Raises
    ValueError if it isn't an export of this add-on, or it's damaged."""
    if not isinstance(bundle, dict) or bundle.get("format") != FORMAT:
        raise ValueError("That isn't a settings file from the OCPP Charge Proxy add-on "
                         "(Diagnostics › Move to another install › Export)")
    if not isinstance(bundle.get("format_version"), int) or bundle["format_version"] > FORMAT_VERSION:
        raise ValueError("That settings file is from a newer version of the add-on: update this one first")
    files, options = bundle.get("files"), bundle.get("options")
    if not isinstance(files, dict) or not isinstance(options, dict) \
            or not all(isinstance(v, dict) for v in files.values()):
        raise ValueError("That settings file is damaged")
    unknown = [n for n in files if n not in SETTINGS_FILES + HISTORY_FILES]
    if unknown:
        raise ValueError(f"That settings file has files this version doesn't know: {', '.join(unknown)}")
    if any(k not in OPTIONS or not isinstance(v, (str, int, float)) for k, v in options.items()):
        raise ValueError("That settings file's options are damaged")
    sc = bundle.get("supplier_changes")
    if sc is not None and not isinstance(sc, dict):
        raise ValueError("That settings file's supplier changes are damaged")
    energy = (files.get("energy_register.json") or {}).get("energy_wh")
    serial = (files.get("serial_number.json") or {}).get("serial") or options.get("charger_serial")
    items = [NAMES[n] for n in SETTINGS_FILES + HISTORY_FILES if n in files]
    if options:
        items.insert(0, "the Configuration tab (server, chargepoint ID" + (", password" if "password" in options else "")
                     + " and charger details)")
    if sc:
        items.append("your supplier changes (suppliers.json)")
    return {"addon_version": bundle.get("addon_version"), "exported_at": bundle.get("exported_at"),
            "items": items, "options": sorted(options), "with_password": "password" in options,
            "with_history": any(n in files for n in HISTORY_FILES),
            "energy_wh": energy if isinstance(energy, (int, float)) else None,
            "serial": str(serial) if serial else None, "chargepoint_id": options.get("chargepoint_id")}


def stage(data_dir: str, bundle: dict) -> None:
    """Keep the file for the next start (apply_pending), checked first."""
    check(bundle)
    if not jsonfile.save(os.path.join(data_dir, PENDING), bundle, "the settings to import", backup=False):
        raise ValueError("Couldn't save the settings to import (is /data full?)")


def options_after(current: dict, bundle: dict) -> dict:
    """The add-on's options with the file's on top (the password kept if the file has none)."""
    out = dict(current)
    out.update({k: v for k, v in (bundle.get("options") or {}).items() if k in OPTIONS})
    out["initial_energy_wh"] = 0
    return out


def apply_pending(data_dir: str, suppliers_path: Optional[str] = None) -> list[str]:
    """At start-up, before anything reads /data: write the staged file's contents and set
    it aside (import_done.json). Returns what was done, to log once logging is set up."""
    path = os.path.join(data_dir, PENDING)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            bundle = json.load(f)
        info = check(bundle)
    except Exception as err:
        _set_aside(path, data_dir)
        return [f"couldn't import the settings file ({err}): nothing was changed"]
    done = []
    try:
        for name, data in bundle["files"].items():
            target = os.path.join(data_dir, name)
            if name == "energy_register.json":
                # A lifetime meter never goes backwards: the higher of the two
                mine = (_read(target) or {}).get("energy_wh") or 0
                theirs = data.get("energy_wh") or 0
                if isinstance(mine, (int, float)) and isinstance(theirs, (int, float)) and mine > theirs:
                    done.append(f"kept this install's energy register ({mine} Wh, more than the file's {theirs} Wh)")
                    continue
            jsonfile.save(target, data, name, default=str)
        # The serial is in the Configuration tab too: if the old install had no serial file
        # (it was entered there), this install's own (made up on its first start) goes
        serial = (bundle.get("options") or {}).get("charger_serial")
        if serial and "serial_number.json" not in bundle["files"]:
            jsonfile.save(os.path.join(data_dir, "serial_number.json"), {"serial": str(serial)}, "serial_number.json")
        sc = bundle.get("supplier_changes")
        if sc and suppliers_path:
            if os.path.exists(suppliers_path):
                done.append(f"kept the supplier changes already in {suppliers_path}")
            elif os.path.isdir(os.path.dirname(suppliers_path)):
                jsonfile.save(suppliers_path, sc, "your supplier changes", backup=False, indent=2)
        done.insert(0, f"imported {', '.join(info['items'])} (exported from version {info['addon_version']} "
                       f"on {info['exported_at']})")
    except Exception as err:
        done.append(f"the import stopped part of the way through ({err}): check the settings")
    _set_aside(path, data_dir)
    return done


def _set_aside(path: str, data_dir: str) -> None:
    try:
        os.replace(path, os.path.join(data_dir, "import_done.json"))
    except OSError:
        logger.warning("Couldn't set %s aside", path)


class Mover:
    """The page's Export / Import (src/api.py), with the Supervisor calls given:
    supervisor(method, path, body=None) -> the reply's "data" (raises if it can't), and
    restart() (the add-on restarting itself, as Diagnostics › Debug › Restart does)."""

    def __init__(self, data_dir: str, version: str, supervisor, restart, suppliers_path: Optional[str] = None):
        self.data_dir, self.version = data_dir, version
        self._supervisor, self._restart, self._suppliers = supervisor, restart, suppliers_path

    def export(self, history: bool, password: bool) -> dict:
        return export(self.data_dir, self.version, history=history, password=password,
                      suppliers_path=self._suppliers)

    async def _others_running(self) -> list[str]:
        """Other OCPP Charge Proxy add-ons that are running (they'd use the same chargepoint)."""
        try:
            me = (await self._supervisor("get", "/addons/self/info")).get("slug")
            addons = (await self._supervisor("get", "/addons")).get("addons") or []
        except Exception as err:
            logger.debug("Couldn't list the add-ons: %s", err)
            return []
        return [a.get("name") or a.get("slug") for a in addons
                if str(a.get("slug", "")).endswith("ocpp_charge_proxy") and a.get("slug") != me
                and a.get("state") == "started"]

    async def check(self, bundle) -> dict:
        info = check(bundle)
        warnings = []
        others = await self._others_running()
        if others:
            warnings.append(f"{', '.join(others)} is still running: stop it before importing. Both would "
                            "connect to your supplier as the same chargepoint and make the same Home Assistant "
                            "entities.")
        here = (_read(os.path.join(self.data_dir, "energy_register.json")) or {}).get("energy_wh")
        if isinstance(here, (int, float)) and info["energy_wh"] is not None and here > info["energy_wh"]:
            warnings.append(f"This install's energy register ({here} Wh) is higher than the file's: it's kept.")
        if not info["with_password"]:
            warnings.append("The file has no password: enter it on the Configuration tab after the import.")
        return {**info, "warnings": warnings, "this_version": self.version}

    async def import_now(self, bundle) -> dict:
        """Save the file for the next start, set the options, and restart."""
        check(bundle)
        current = _read(os.path.join(self.data_dir, "options.json")) or {}
        stage(self.data_dir, bundle)
        options = options_after(current, bundle)
        try:
            await self._supervisor("post", "/addons/self/options", {"options": options})
        except Exception as err:
            os.replace(os.path.join(self.data_dir, PENDING), os.path.join(self.data_dir, "import_done.json"))
            raise ValueError(f"Home Assistant didn't take the options ({err}): nothing was changed") from None
        logger.info("Importing the settings file (exported from version %s): restarting to use it",
                    bundle.get("addon_version"))
        await self._restart()
        return {"restarting": True}
