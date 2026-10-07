"""Your supplier's smart charging plan, found in Home Assistant.

Supplier integrations built on the Kraken platform publish the charge slots
they plan for your car as a binary sensor with a `planned_dispatches`
attribute:

- Octopus Energy (BottlecapDave's integration):
  binary_sensor.octopus_energy_<device>_intelligent_dispatching
- EDF Energy (stevekirtley's integration, based on it):
  binary_sensor.edf_energy_<device>_intelligent_dispatching

Both use the same attributes: planned_dispatches / started_dispatches /
completed_dispatches, each a list of {start, end, charge_in_kwh, source}.
Only planned_dispatches (the current plan, including what's already run
today) and completed_dispatches are used. started_dispatches is ignored: a
started dispatch keeps the times it had when it began, even after the
supplier re-plans (e.g. started 16:01 to run until 22:00, re-planned to
17:00-21:30 after the charger restarted), so it would show a slot that
isn't there.
The add-on looks through HA's states for any binary sensor carrying them, so
a renamed entity, or another integration using the same format, is found
too.

- E.ON Next (the eon_next integration) publishes a sensor named
  "<charger serial> Smart Charging Schedule" with a `schedule` attribute:
  a list of {start, end, type, energy_added_kwh} (planned slots only).

Nothing to set up; if none is found the page says so.

Kept free of I/O so it can be tested on its own; HaLink fetches the states.
"""

from __future__ import annotations

import datetime
from typing import Optional

from src import suppliers

# From src/suppliers.json: dispatching sensor entity ID prefix -> name shown on
# the page, and schedule sensor suffix (E.ON Next) -> name
PROVIDERS = tuple((s["dispatch_prefix"], s["name"]) for s in suppliers.all_suppliers() if s.get("dispatch_prefix"))
SCHEDULE_SENSORS = tuple((s["schedule_sensor_suffix"], s["name"]) for s in suppliers.all_suppliers()
                         if s.get("schedule_sensor_suffix"))


def _ts(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        dt = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def _iso(t: Optional[float]) -> Optional[str]:
    if t is None:
        return None
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slots(items) -> list[dict]:
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        start, end = _ts(item.get("start")), _ts(item.get("end"))
        if start is None or end is None or end <= start:
            continue
        kwh = item.get("charge_in_kwh", item.get("energy_added_kwh"))
        try:
            kwh = None if kwh is None else round(float(kwh), 2)
        except (TypeError, ValueError):
            kwh = None
        out.append({"start": _iso(start), "end": _iso(end), "charge_kwh": kwh,
                    "source": item.get("source"), "_s": start, "_e": end})
    out.sort(key=lambda s: s["_s"])
    return out


def _merge(slots: list[dict]) -> list[dict]:
    """Back-to-back and overlapping slots as one (Octopus often plans 30-minute pieces)."""
    merged: list[dict] = []
    for s in slots:
        if merged and s["_s"] <= merged[-1]["_e"]:
            last = merged[-1]
            if s["_e"] > last["_e"]:
                last["_e"], last["end"] = s["_e"], s["end"]
            if s["charge_kwh"] is not None:
                last["charge_kwh"] = round((last["charge_kwh"] or 0) + s["charge_kwh"], 2)
        else:
            merged.append(dict(s))
    return merged


def _is_eon(st: dict) -> bool:
    entity_id = str(st.get("entity_id", ""))
    return (entity_id.startswith("sensor.") and any(sfx in entity_id for sfx, _ in SCHEDULE_SENSORS)
            and isinstance((st.get("attributes") or {}).get("schedule"), list))


def provider_name(entity_id: str) -> str:
    for prefix, name in PROVIDERS:
        if entity_id.startswith(prefix):
            return name
    for suffix, name in SCHEDULE_SENSORS:
        if entity_id.startswith("sensor.") and suffix in entity_id:
            return name
    return suppliers.DATA["other"]["name"]


def find_dispatch_sensors(states: list[dict]) -> list[dict]:
    """Supplier smart charging sensors (Kraken dispatching binary sensors, or
    E.ON Next's schedule sensor), known suppliers first."""
    found = [
        st for st in states or []
        if (str(st.get("entity_id", "")).startswith("binary_sensor.")
            and isinstance((st.get("attributes") or {}).get("planned_dispatches"), list))
        or _is_eon(st)
    ]
    known = [p for p, _ in PROVIDERS]
    found.sort(key=lambda st: (not (any(st["entity_id"].startswith(p) for p in known) or _is_eon(st)), st["entity_id"]))
    return found


def smart_charging(states: list[dict], now: float) -> dict:
    """The plan for the page: whether a slot is on now, the next ones, the recent ones."""
    sensors = find_dispatch_sensors(states)
    if not sensors:
        return {"found": False}
    st = sensors[0]
    attrs = st.get("attributes") or {}
    planned = _merge(sorted(_slots(attrs.get("planned_dispatches")) + _slots(attrs.get("schedule")),
                            key=lambda s: s["_s"]))
    completed = _merge(_slots(attrs.get("completed_dispatches")))
    current = next((s for s in planned if s["_s"] <= now < s["_e"]), None)
    upcoming = [s for s in planned if s["_s"] > now]
    # For the chart: everything known (completed and planned), merged
    periods = _merge(sorted(completed + planned, key=lambda s: s["_s"]))

    def clean(items):
        return [{k: v for k, v in s.items() if not k.startswith("_")} for s in items]

    return {
        "found": True,
        "provider": provider_name(st["entity_id"]),
        "entity_id": st["entity_id"],
        "name": attrs.get("friendly_name") or st["entity_id"],
        "dispatching": st.get("state") == "on" or current is not None,
        "current": clean([current])[0] if current else None,
        "planned": clean(upcoming),
        "planned_kwh": round(sum(s["charge_kwh"] or 0 for s in upcoming), 2) if any(
            s["charge_kwh"] is not None for s in upcoming) else None,
        "periods": clean(periods),
        "others": [s["entity_id"] for s in sensors[1:]],
    }
