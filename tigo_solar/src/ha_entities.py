"""The add-on's Home Assistant sensors, posted as states through the Supervisor (no
integration needed). They show as "unavailable" while the add-on is stopped, and are
posted again when it (or HA) restarts.

The whole system: power and reclaimed power (W), energy today, this month, this year and
ever, and reclaimed energy today (kWh, for the Energy dashboard). Each panel: its power,
reclaimed power and energy today. Panel sensors are named after the panel's label on
Tigo (sensor.tigo_solar_panel_a1_power...).

Kept free of I/O so it can be tested on its own; HaLink posts them."""
from __future__ import annotations

import re
from typing import Optional

PREFIX = "tigo_solar"  # entity IDs: sensor.tigo_solar_...
NAME = "Tigo"
REFRESH_S = 300  # everything posted again at least this often, even unchanged

POWER = {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
ENERGY = {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}


def _kwh(wh: Optional[float]) -> Optional[float]:
    return None if wh is None else round(wh / 1000.0, 3)


def _w(w: Optional[float]) -> Optional[float]:
    return None if w is None else round(w, 1)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or "panel"


def sensors(state) -> list[tuple[str, Optional[object], dict]]:
    """Every sensor: (entity ID, value or None, attributes)."""
    out = [
        (f"sensor.{PREFIX}_status", state.status, {"friendly_name": f"{NAME} Status", "icon": "mdi:solar-panel"}),
        (f"sensor.{PREFIX}_power", _w(state.power), {"friendly_name": f"{NAME} Solar Power", "icon": "mdi:solar-power", **POWER}),
        (f"sensor.{PREFIX}_reclaimed_power", _w(state.reclaimed),
         {"friendly_name": f"{NAME} Reclaimed Power", "icon": "mdi:solar-power-variant", **POWER}),
        (f"sensor.{PREFIX}_energy_today", _kwh(state.today_wh),
         {"friendly_name": f"{NAME} Energy Today", "icon": "mdi:solar-power-variant-outline", **ENERGY}),
        (f"sensor.{PREFIX}_reclaimed_energy_today", _kwh(state.today_reclaimed_wh),
         {"friendly_name": f"{NAME} Reclaimed Energy Today", "icon": "mdi:solar-power-variant", **ENERGY}),
        (f"sensor.{PREFIX}_energy_month", _kwh(state.month_wh),
         {"friendly_name": f"{NAME} Energy This Month", "icon": "mdi:solar-power-variant-outline", **ENERGY}),
        (f"sensor.{PREFIX}_energy_year", _kwh(state.year_wh),
         {"friendly_name": f"{NAME} Energy This Year", "icon": "mdi:solar-power-variant-outline", **ENERGY}),
        (f"sensor.{PREFIX}_energy_lifetime", _kwh(state.lifetime_wh),
         {"friendly_name": f"{NAME} Energy Lifetime", "icon": "mdi:solar-power-variant-outline", **ENERGY}),
    ]
    used = set()
    for p in state.panels or []:
        key = slug(p.get("label"))
        while key in used:
            key += "_"
        used.add(key)
        label = p.get("label")
        info = {"panel_id": p.get("id"), "string": p.get("string"), "serial": p.get("serial")}
        out += [
            (f"sensor.{PREFIX}_panel_{key}_power", _w(p.get("power")),
             {"friendly_name": f"{NAME} {label} Power", "icon": "mdi:solar-power", **POWER, **info}),
            (f"sensor.{PREFIX}_panel_{key}_reclaimed_power", _w(p.get("reclaimed")),
             {"friendly_name": f"{NAME} {label} Reclaimed Power", "icon": "mdi:solar-power-variant", **POWER, **info}),
            (f"sensor.{PREFIX}_panel_{key}_energy_today", _kwh(p.get("energy_today")),
             {"friendly_name": f"{NAME} {label} Energy Today", "icon": "mdi:solar-power-variant-outline", **ENERGY, **info}),
        ]
    return out


class SensorPublisher:
    """Decides what to post: anything that changed, everything every REFRESH_S."""

    def __init__(self) -> None:
        self._sent: dict[str, tuple[str, float]] = {}  # entity_id -> (value posted, when)
        self._attrs: dict[str, dict] = {}  # entity_id -> attributes, for unavailable()

    @property
    def ids(self) -> list[str]:
        return sorted(self._attrs)

    def reset(self) -> None:
        self._sent.clear()  # e.g. HA restarted: post everything again

    def forget(self, entity_id: str) -> None:
        self._sent.pop(entity_id, None)  # posting failed: try again next time

    def due(self, state, now: float) -> list[tuple[str, str, dict]]:
        out = []
        for entity_id, value, attrs in sensors(state):
            text = "unknown" if value is None else str(value)
            self._attrs[entity_id] = attrs
            last = self._sent.get(entity_id)
            if last is None or last[0] != text or now - last[1] >= REFRESH_S:
                self._sent[entity_id] = (text, now)
                out.append((entity_id, text, dict(attrs)))
        return out

    def unavailable(self) -> list[tuple[str, str, dict]]:
        return [(entity_id, "unavailable", dict(attrs)) for entity_id, attrs in self._attrs.items()]


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
