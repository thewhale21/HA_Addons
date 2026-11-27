"""The add-on's own Home Assistant entities, posted as states through the
Supervisor (no integration needed). They show as "unavailable" while the
add-on is stopped, and are posted again when it (or HA) restarts.

Add a sensor: an entry in SENSORS (entity ID, attributes) and a value for
it in values() below. Use device_class / state_class / unit_of_measurement
so HA records it properly (e.g. the Energy dashboard needs
device_class: energy, state_class: total_increasing, unit kWh).

Kept free of I/O so it can be tested on its own; HaLink posts them."""
from __future__ import annotations

from typing import Optional

PREFIX = "neighbourhood_view"  # entity IDs: sensor.neighbourhood_view_...

SENSORS = {
    "status": (f"sensor.{PREFIX}_status", {
        "friendly_name": "Neighbourhood View Status", "icon": "mdi:map-marker-radius",
    }),
}
ALL_SENSORS = [entity_id for entity_id, _ in SENSORS.values()]

REFRESH_S = 300  # everything posted again at least this often, even unchanged


def attributes(state) -> dict:
    """Attributes that change, by the sensor's key: the status's map_url, where the dashboard card
    reads the map (src/card_data.py)."""
    x = state.extra or {}
    # (and the screensaver: where the map is, where a tap goes, how long left alone before coming
    # back; read by the card's file on every dashboard)
    return {"status": {"map_url": x.get("map_url"), "screensaver": x.get("screensaver")}}


def values(state) -> dict:
    """The value of each sensor (by its key in SENSORS) from the shared state."""
    return {
        "status": state.status,
    }


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
        extra = attributes(state)
        for key, value in values(state).items():
            entity_id, attrs = SENSORS[key]
            attrs = {**attrs, **(extra.get(key) or {})}
            text = "unknown" if value is None else str(value)
            sig = text + repr(sorted(attrs.items()))
            last = self._sent.get(entity_id)
            if last is None or last[0] != sig or now - last[1] >= REFRESH_S:
                self._sent[entity_id] = (sig, now)
                out.append((entity_id, text, attrs))
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
