"""How each kind of supplier integration shows its smart charging plan in Home
Assistant: one module per kind, each with the same functions, so a change to
one touches one file, and a new kind is a new file (added to TYPES).

- kraken: a binary sensor with the planned slots in an attribute, and a ready
  (target) time entity next to it (Octopus Energy, EDF Energy).
- schedule_sensor: a sensor with the planned slots in an attribute, no ready
  time (E.ON Next).

A supplier in src/suppliers.json says its kind with "type" (or it's worked out:
kraken with a dispatch_prefix, schedule_sensor with a schedule_sensor_suffix),
and the kind's DEFAULTS fill in any names it doesn't give.

Each module has:
- NAME, REQUIRED (the fields a supplier of this kind must have), DEFAULTS;
- matches_entity(entity_id, supplier): the entity is this supplier's (its
  sensor, or the ready time entity next to it);
- is_sensor(state, supplier): the state is its smart charging sensor, with the
  slots attribute;
- slot_lists(state, supplier): (planned items, completed items) as listed;
- ready_entity_ids(sensor_id, supplier): the ready time entity IDs to look for;
- check(states_by_id, supplier): problems seen with its entities
  [{"level", "text"}], e.g. the sensor there without the slots attribute.
"""

from __future__ import annotations

from typing import Optional

from src.supplier_types import kraken, schedule_sensor

TYPES = {m.NAME: m for m in (kraken, schedule_sensor)}


def kind_of(supplier: dict):
    """A supplier's kind (its module), or None (e.g. the defaults for any other)."""
    name = supplier.get("type")
    if name:
        return TYPES.get(name)
    for m in TYPES.values():
        if all(supplier.get(k) for k in m.REQUIRED):
            return m
    return None


def name_of(raw: dict) -> Optional[str]:
    """The kind a supplier's file entry is (for checking it), or None."""
    m = kind_of(raw)
    return m.NAME if m else None
