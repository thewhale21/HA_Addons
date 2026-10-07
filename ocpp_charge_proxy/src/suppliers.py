"""Each supplier's defaults, from suppliers.json next to this file.

Edit suppliers.json and rebuild the add-on to change them (a supplier's
daily limit, when it resets, the ready times its app accepts, or how its
smart charging sensor is found). Anything set on the web page (Settings ›
Your supplier) still wins. If the file is missing or broken, the built-in
values below are used and the log says why.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "suppliers.json")
ALL_DAY = [f"{h:02}:{m:02}" for h in range(24) for m in (0, 30)]

BUILT_IN = {
    "suppliers": [
        {"name": "Octopus Energy", "dispatch_prefix": "binary_sensor.octopus_energy_",
         "ready_times": {"from": "00:00", "to": "23:30"}, "daily_limit_h": 6, "limit_reset": "12:00"},
        {"name": "EDF Energy", "dispatch_prefix": "binary_sensor.edf_energy_",
         "ready_times": {"from": "04:00", "to": "11:00"}, "daily_limit_h": None, "limit_reset": "rolling"},
        {"name": "E.ON Next", "schedule_sensor_suffix": "smart_charging_schedule",
         "ready_times": None, "daily_limit_h": None, "limit_reset": "rolling"},
    ],
    "other": {"name": "Your supplier", "ready_times": {"from": "04:00", "to": "11:00"},
              "daily_limit_h": None, "limit_reset": "rolling"},
}


def _check(entry: dict, where: str) -> dict:
    """One supplier's entry, checked: raises ValueError saying what's wrong."""
    if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
        raise ValueError(f"{where}: needs a name")
    out = {"name": str(entry["name"]).strip()}
    for key in ("dispatch_prefix", "schedule_sensor_suffix"):
        if entry.get(key):
            out[key] = str(entry[key]).strip()
    times = entry.get("ready_times")
    if times is None:
        out["ready_times"] = None
    else:
        lo, hi = (times or {}).get("from"), (times or {}).get("to")
        if lo not in ALL_DAY or hi not in ALL_DAY or lo > hi:
            raise ValueError(f"{where}: ready_times needs from / to on the hour or half hour, from before to")
        out["ready_times"] = {"from": lo, "to": hi}
    hours = entry.get("daily_limit_h")
    if hours is not None:
        try:
            hours = float(hours)
        except (TypeError, ValueError):
            raise ValueError(f"{where}: daily_limit_h must be a number of hours or null") from None
        if not 0 < hours <= 24 or hours * 2 != int(hours * 2):
            raise ValueError(f"{where}: daily_limit_h must be 0.5 to 24, in half hours (null: no limit)")
    out["daily_limit_h"] = hours
    reset = str(entry.get("limit_reset") or "rolling").strip()
    if reset != "rolling" and reset not in ALL_DAY:
        raise ValueError(f"{where}: limit_reset must be \"rolling\" or a time on the hour or half hour")
    out["limit_reset"] = reset
    return out


def parse(data: dict) -> dict:
    """The file's contents, checked (raises ValueError)."""
    if not isinstance(data, dict) or not isinstance(data.get("suppliers"), list):
        raise ValueError("needs a \"suppliers\" list")
    suppliers = [_check(e, f"supplier {i + 1}") for i, e in enumerate(data["suppliers"])]
    other = _check(dict({"name": "Your supplier"}, **(data.get("other") or {})), "other")
    return {"suppliers": suppliers, "other": other}


def load(path: str = PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return parse(json.load(f))
    except FileNotFoundError:
        logger.warning("Supplier defaults: %s not found, using the built-in ones", path)
    except (ValueError, OSError) as err:  # json.JSONDecodeError is a ValueError
        logger.warning("Supplier defaults: %s can't be used (%s), using the built-in ones", path, err)
    return parse(BUILT_IN)


DATA = load()


def all_suppliers() -> list[dict]:
    return DATA["suppliers"]


def by_name(name: Optional[str]) -> dict:
    """A supplier's defaults by the name shown on the page (other: the defaults for any other)."""
    return next((s for s in DATA["suppliers"] if s["name"] == name), DATA["other"])


def for_entity(entity_id: Optional[str]) -> dict:
    """The supplier an entity belongs to (its dispatching sensor, or the ready
    time entity next to it), else the defaults for any other supplier."""
    entity_id = str(entity_id or "")
    obj = entity_id.split(".", 1)[-1]
    for s in DATA["suppliers"]:
        prefix = s.get("dispatch_prefix")
        if prefix and (entity_id.startswith(prefix) or obj.startswith(prefix.split(".", 1)[-1])):
            return s
        suffix = s.get("schedule_sensor_suffix")
        if suffix and entity_id.startswith("sensor.") and suffix in entity_id:
            return s
    return DATA["other"]


def ready_times(supplier: dict) -> list[str]:
    """The ready times a supplier accepts ("HH:MM"), or [] if it has none."""
    t = supplier.get("ready_times")
    if not t:
        return []
    return [x for x in ALL_DAY if t["from"] <= x <= t["to"]]


def daily_limit_min(name: Optional[str]) -> Optional[int]:
    hours = by_name(name).get("daily_limit_h")
    return int(round(hours * 60)) if hours else None


def limit_reset(name: Optional[str]) -> str:
    """"HH:MM" or "rolling"."""
    return by_name(name).get("limit_reset") or "rolling"
