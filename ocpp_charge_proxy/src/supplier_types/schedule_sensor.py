"""Integrations that publish the plan as a sensor with a schedule attribute (E.ON
Next: "<charger serial> Smart Charging Schedule", sensor.<...>_smart_charging_schedule).

- The plan: a sensor whose entity ID contains schedule_sensor_suffix, its
  slots in schedule_attribute (schedule), each {start, end, type,
  energy_added_kwh} (slot_fields). Planned slots only; no completed ones.
- No ready time.
"""

from __future__ import annotations

NAME = "schedule_sensor"
REQUIRED = ("schedule_sensor_suffix",)
DEFAULTS = {
    "schedule_attribute": "schedule",
    "slot_fields": {"start": "start", "end": "end", "kwh": "energy_added_kwh", "source": "type"},
}


def _attr(supplier: dict) -> str:
    return supplier.get("schedule_attribute") or DEFAULTS["schedule_attribute"]


def matches_entity(entity_id: str, supplier: dict) -> bool:
    suffix = supplier.get("schedule_sensor_suffix") or ""
    return bool(suffix) and entity_id.startswith("sensor.") and suffix in entity_id


def is_sensor(state: dict, supplier: dict) -> bool:
    return matches_entity(str(state.get("entity_id", "")), supplier) and isinstance(
        (state.get("attributes") or {}).get(_attr(supplier)), list)


def slot_lists(state: dict, supplier: dict) -> tuple:
    return (state.get("attributes") or {}).get(_attr(supplier)), None


def ready_entity_ids(sensor_id: str, supplier: dict) -> list:
    return []


def check(by_id: dict, supplier: dict) -> list:
    planned = _attr(supplier)
    return [{"level": "warn", "text": f"{eid} is there but has no {planned} attribute: {supplier['name']}'s "
             "integration may have changed (schedule_attribute in suppliers.json)"}
            for eid, st in by_id.items()
            if matches_entity(eid, supplier) and str(st.get("state")).lower() not in ("unavailable", "unknown")
            and not isinstance((st.get("attributes") or {}).get(planned), list)]
