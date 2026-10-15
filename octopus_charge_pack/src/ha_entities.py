"""The add-on's own Home Assistant entities, posted as states through the
Supervisor (no integration needed). They show as "unavailable" while the
add-on is stopped, and are posted again when it (or HA) restarts.

Add a sensor: an entry in SENSORS (entity ID, attributes) and a value for
it in values() below. Use device_class / state_class / unit_of_measurement
so HA records it properly (e.g. the Energy dashboard needs
device_class: energy, state_class: total_increasing, unit kWh).

Kept free of I/O so it can be tested on its own; HaLink posts them."""
from __future__ import annotations

import json
from typing import Optional

PREFIX = "octopus_charge_pack"  # the add-on's own: sensor.octopus_charge_pack_status
# The dispatch sensors keep the entity IDs the REST and template sensors had, so anything
# using them (e.g. Predbat's rates_export_override) carries on unchanged.
TIMESTAMP = {"device_class": "timestamp"}

SENSORS = {
    "status": (f"sensor.{PREFIX}_status", {
        "friendly_name": "Octopus Charge Pack Status", "icon": "mdi:ev-station"}),
    "planned": ("sensor.octopus_planned_dispatches", {
        "friendly_name": "Octopus Planned Dispatches", "icon": "mdi:calendar-clock"}),
    "charge_start": ("sensor.next_charge_dispatch_start", {
        "friendly_name": "Next Charge Dispatch Start", **TIMESTAMP}),
    "charge_end": ("sensor.next_charge_dispatch_end", {
        "friendly_name": "Next Charge Dispatch End", **TIMESTAMP}),
    "discharge_start": ("sensor.next_discharge_dispatch_start", {
        "friendly_name": "Next Discharge Dispatch Start", **TIMESTAMP}),
    "discharge_end": ("sensor.next_discharge_dispatch_end", {
        "friendly_name": "Next Discharge Dispatch End", **TIMESTAMP}),
    "charge_date": ("sensor.next_charge_dispatch_date", {
        "friendly_name": "Next Charge Dispatch Date", "icon": "mdi:calendar"}),
    "charge_start_date": ("sensor.next_charge_dispatch_start_date", {
        "friendly_name": "Next Charge Dispatch Start Date", "icon": "mdi:calendar-start"}),
    "charge_end_date": ("sensor.next_charge_dispatch_end_date", {
        "friendly_name": "Next Charge Dispatch End Date", "icon": "mdi:calendar-end"}),
    "charge_start_time": ("sensor.next_charge_dispatch_start_time", {
        "friendly_name": "Next Charge Dispatch Start Time", "icon": "mdi:clock-start"}),
    "charge_end_time": ("sensor.next_charge_dispatch_end_time", {
        "friendly_name": "Next Charge Dispatch End Time", "icon": "mdi:clock-end"}),
    "discharge_date": ("sensor.next_discharge_dispatch_date", {
        "friendly_name": "Next Discharge Dispatch Date", "icon": "mdi:calendar"}),
    "discharge_start_date": ("sensor.next_discharge_dispatch_start_date", {
        "friendly_name": "Next Discharge Dispatch Start Date", "icon": "mdi:calendar-start"}),
    "discharge_end_date": ("sensor.next_discharge_dispatch_end_date", {
        "friendly_name": "Next Discharge Dispatch End Date", "icon": "mdi:calendar-end"}),
    "discharge_start_time": ("sensor.next_discharge_dispatch_start_time", {
        "friendly_name": "Next Discharge Dispatch Start Time", "icon": "mdi:clock-start"}),
    "discharge_end_time": ("sensor.next_discharge_dispatch_end_time", {
        "friendly_name": "Next Discharge Dispatch End Time", "icon": "mdi:clock-end"}),
}
ALL_SENSORS = [entity_id for entity_id, _ in SENSORS.values()]

REFRESH_S = 300  # everything posted again at least this often, even unchanged


def values(state) -> dict:
    """The value of each sensor (by its key in SENSORS) from the shared state: the value, or
    (value, extra attributes). Before the first successful read the dispatch sensors are unknown."""
    s = state.summary or {}
    out = {"status": (state.status, {"error": state.error, "device_id": state.device_id,
                                     "last_update": state.last_update})}
    if not s:
        return {**out, **{key: None for key in SENSORS if key != "status"}}
    out["planned"] = (s.get("count"), {"flexPlannedDispatches": s.get("dispatches") or []})
    for key in [k for k in SENSORS if k not in ("status", "planned")]:
        out[key] = s.get(key)
    return out


class SensorPublisher:
    """Decides what to post: anything that changed, everything every REFRESH_S."""

    def __init__(self) -> None:
        self._sent: dict[str, tuple[str, float]] = {}  # entity_id -> (value posted, when)

    def reset(self) -> None:
        self._sent.clear()  # e.g. HA restarted: post everything again

    def forget(self, entity_id: str) -> None:
        self._sent.pop(entity_id, None)  # posting failed: try again next time

    def due(self, state, now: float) -> list[tuple[str, str, dict]]:
        out = []
        for key, value in values(state).items():
            entity_id, attrs = SENSORS[key]
            extra = {}
            if isinstance(value, tuple):
                value, extra = value
            text = "unknown" if value is None else str(value)
            sig = text + json.dumps(extra, sort_keys=True, default=str)
            last = self._sent.get(entity_id)
            if last is None or last[0] != sig or now - last[1] >= REFRESH_S:
                self._sent[entity_id] = (sig, now)
                out.append((entity_id, text, {**attrs, **extra}))
        return out

    @staticmethod
    def unavailable() -> list[tuple[str, str, dict]]:
        return [(entity_id, "unavailable", dict(attrs)) for entity_id, attrs in SENSORS.values()]


def entity_info(states: dict, entity_id: Optional[str]) -> Optional[dict]:
    """An entity's state and name for the web page."""
    if not entity_id:
        return None
    st = states.get(entity_id)
    attrs = (st or {}).get("attributes") or {}
    return {
        "entity_id": entity_id,
        "name": attrs.get("friendly_name") or entity_id,
        "state": (st or {}).get("state"),
        "unit": attrs.get("unit_of_measurement"),
    }
