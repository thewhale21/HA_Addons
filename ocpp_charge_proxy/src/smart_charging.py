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

Nothing to set up; if none is found the page says so. The entity names,
attributes and fields above are each supplier's in src/suppliers.json (and the
override file), not fixed here, so a supplier's change can be followed there.
check_supplier() looks for signs that a supplier's integration has changed
(its sensor there without the slots, slots in another format...).

Kept free of I/O so it can be tested on its own; HaLink fetches the states.
"""

from __future__ import annotations

import datetime
from typing import Optional

from src import supplier_types, suppliers
from src.supplier_types import kraken


def _kinds() -> list:
    """(supplier, its kind's module) for each supplier in src/suppliers.json (read
    again when the override changes) that has a kind (src/supplier_types)."""
    out = []
    for s in suppliers.all_suppliers():
        kind = supplier_types.kind_of(s)
        if kind:
            out.append((s, kind))
    return out


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


def _slots(items, fields: Optional[dict] = None) -> list[dict]:
    """A supplier's slots, read with its field names (slot_fields in src/suppliers.json)."""
    f = {**suppliers.KRAKEN["slot_fields"], **(fields or {})}
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        start, end = _ts(item.get(f["start"])), _ts(item.get(f["end"]))
        if start is None or end is None or end <= start:
            continue
        kwh = item.get(f["kwh"])
        try:
            kwh = None if kwh is None else round(float(kwh), 2)
        except (TypeError, ValueError):
            kwh = None
        out.append({"start": _iso(start), "end": _iso(end), "charge_kwh": kwh,
                    "source": item.get(f["source"]), "_s": start, "_e": end})
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


def provider_name(entity_id: str) -> str:
    return suppliers.for_entity(entity_id)["name"]


def _owner(st: dict):
    """The supplier (and its kind) whose smart charging sensor this is, or (None, None)."""
    for s, kind in _kinds():
        if kind.is_sensor(st, s):
            return s, kind
    return None, None


def _any_kraken(st: dict) -> bool:
    """Any binary sensor with Kraken-style slots: a renamed entity, or another integration
    using the same format (src/supplier_types/kraken.py)."""
    return kraken.is_sensor(st, {})


def find_dispatch_sensors(states: list[dict]) -> list[dict]:
    """Supplier smart charging sensors (a known supplier's, by its kind in
    src/supplier_types, or any Kraken-style one), known suppliers first."""
    found = [st for st in states or [] if _owner(st)[0] is not None or _any_kraken(st)]
    found.sort(key=lambda st: (_owner(st)[0] is None, st["entity_id"]))
    return found


def _lists(st: dict) -> tuple:
    """(planned items, completed items, slot field names) from a sensor's state."""
    s, kind = _owner(st)
    if s is None:
        s, kind = suppliers.for_entity(st.get("entity_id")), kraken
    planned, completed = kind.slot_lists(st, s)
    return planned, completed, s.get("slot_fields")


def check_supplier(states: list[dict], chosen: Optional[str] = None) -> list[dict]:
    """Signs that a supplier's integration has changed, from all of HA's states:
    [{"level": "warn" | "info", "text"}]. `chosen`: the sensor in use, if any.
    - a supplier's sensor (by name) is there, but without the slots attribute
      (each kind's check(), src/supplier_types);
    - the sensor in use has slots, but none in the format expected;
    - the sensor in use is unavailable;
    - nothing found, but the supplier's integration has entities in HA."""
    by_id = {str(st.get("entity_id", "")): st for st in states or []}
    out = []
    for s, kind in _kinds():
        out += kind.check(by_id, s)
    st = by_id.get(chosen) if chosen else None
    if st is not None:
        s = suppliers.for_entity(chosen)
        if str(st.get("state")).lower() == "unavailable":
            out.append({"level": "warn", "text": f"{chosen} is unavailable: {s['name']}'s integration isn't "
                        "giving its plan at the moment"})
        planned, completed, fields = _lists(st)
        f = {**suppliers.KRAKEN["slot_fields"], **(fields or {})}
        for what, items in (("planned", planned), ("completed", completed)):
            if isinstance(items, list) and items and not _slots(items, fields):
                keys = sorted({k for i in items if isinstance(i, dict) for k in i})
                out.append({"level": "warn", "text": f"{chosen}'s {what} slots ({len(items)}) aren't in the format "
                            f"expected ({f['start']} and {f['end']}; they have {', '.join(keys) or 'nothing'}): "
                            f"{s['name']}'s integration may have changed (slot_fields in suppliers.json)"})
    elif not chosen:
        for s, _ in _kinds():
            base = (s.get("dispatch_prefix") or "").split(".", 1)[-1] or ((s.get("integration") or "") + "_")
            if base.strip("_") and any(eid.split(".", 1)[-1].startswith(base) for eid in by_id):
                out.append({"level": "info", "text": f"{s['name']}'s integration is in Home Assistant, but no smart "
                            "charging sensor was found. That's expected if you're not on its smart charging tariff; "
                            "otherwise its sensor may have been renamed (dispatch_prefix / dispatch_suffix in "
                            "suppliers.json)"})
                break
    return out


def smart_charging(states: list[dict], now: float) -> dict:
    """The plan for the page: whether a slot is on now, the next ones, the recent ones."""
    sensors = find_dispatch_sensors(states)
    if not sensors:
        return {"found": False}
    st = sensors[0]
    attrs = st.get("attributes") or {}
    planned_items, completed_items, fields = _lists(st)
    planned = _merge(_slots(planned_items, fields))
    completed = _merge(_slots(completed_items, fields))
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
