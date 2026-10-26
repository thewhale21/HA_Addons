"""Kraken-platform integrations (Octopus Energy: BottlecapDave's; EDF Energy:
stevekirtley's, based on it).

- The plan: binary_sensor.<dispatch_prefix><device>_intelligent_<dispatch_suffix>,
  its slots in planned_attribute / completed_attribute (planned_dispatches /
  completed_dispatches), each {start, end, charge_in_kwh, source} (slot_fields).
  started_dispatches isn't used: a started dispatch keeps the times it had when
  it began, even after the supplier re-plans.
- The ready time: time. or select.<the same, with dispatch_suffix swapped for
  ready_entity_suffix> (..._intelligent_target_time).

Any binary sensor with the slots attribute is found too, so a renamed entity
(or another integration using the same format) still works.
"""

from __future__ import annotations

NAME = "kraken"
REQUIRED = ("dispatch_prefix",)
DEFAULTS = {
    "dispatch_suffix": "dispatching",
    "ready_entity_suffix": "target_time",
    "planned_attribute": "planned_dispatches",
    "completed_attribute": "completed_dispatches",
    "slot_fields": {"start": "start", "end": "end", "kwh": "charge_in_kwh", "source": "source"},
}


def _get(supplier: dict, key: str):
    return supplier.get(key) or DEFAULTS[key]


def matches_entity(entity_id: str, supplier: dict) -> bool:
    prefix = supplier.get("dispatch_prefix") or ""
    if not prefix:
        return False
    obj = entity_id.split(".", 1)[-1]
    return entity_id.startswith(prefix) or obj.startswith(prefix.split(".", 1)[-1])


def is_sensor(state: dict, supplier: dict) -> bool:
    entity_id = str(state.get("entity_id", ""))
    return entity_id.startswith("binary_sensor.") and isinstance(
        (state.get("attributes") or {}).get(_get(supplier, "planned_attribute")), list)


def slot_lists(state: dict, supplier: dict) -> tuple:
    attrs = state.get("attributes") or {}
    return attrs.get(_get(supplier, "planned_attribute")), attrs.get(_get(supplier, "completed_attribute"))


def ready_entity_ids(sensor_id: str, supplier: dict) -> list:
    suffix, ready = _get(supplier, "dispatch_suffix"), _get(supplier, "ready_entity_suffix")
    if not sensor_id.startswith("binary_sensor.") or not sensor_id.endswith(suffix):
        return []
    base = sensor_id[len("binary_sensor."):-len(suffix)]  # e.g. octopus_energy_<id>_intelligent_
    return [f"{domain}.{base}{ready}" for domain in ("time", "select")]  # (the time entity is the newer one)


def check(by_id: dict, supplier: dict) -> list:
    prefix, suffix = supplier["dispatch_prefix"], _get(supplier, "dispatch_suffix")
    planned = _get(supplier, "planned_attribute")
    out = []
    for eid, st in by_id.items():
        if eid.startswith(prefix) and eid.endswith(suffix) \
                and str(st.get("state")).lower() not in ("unavailable", "unknown") \
                and not isinstance((st.get("attributes") or {}).get(planned), list):
            out.append({"level": "warn", "text": f"{eid} is there but has no {planned} attribute: "
                        f"{supplier['name']}'s integration may have changed how it lists its slots "
                        "(planned_attribute in suppliers.json)"})
    return out
