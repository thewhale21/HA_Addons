"""The add-on's own Home Assistant entities, posted as states through the
Supervisor (no integration needed). They show as "unavailable" while the
add-on is stopped, and are posted again when it (or HA) restarts.

Add a sensor: an entry in SENSORS (entity ID, attributes) and a value for
it in values() below: the value, or (value, extra attributes).

Kept free of I/O so it can be tested on its own; HaLink posts them."""
from __future__ import annotations

import json
from typing import Optional

PREFIX = "evdc_soc_range"  # entity IDs: sensor.evdc_soc_range_...
NAME = "EVDC SoC Range"

SENSORS = {
    "status": (f"sensor.{PREFIX}_status", {"friendly_name": f"{NAME} Status", "icon": "mdi:ev-station"}),
    "last_action": (f"sensor.{PREFIX}_last_action", {"friendly_name": f"{NAME} Last Action", "icon": "mdi:history"}),
    "vehicle_soc": (f"sensor.{PREFIX}_vehicle_soc", {
        "friendly_name": f"{NAME} Vehicle SoC", "unit_of_measurement": "%", "device_class": "battery",
        "state_class": "measurement"}),
    "plugged_in": (f"binary_sensor.{PREFIX}_plugged_in", {
        "friendly_name": f"{NAME} Plugged In", "device_class": "plug"}),
    "charger_running": (f"binary_sensor.{PREFIX}_charger_running", {
        "friendly_name": f"{NAME} Charger Running", "device_class": "running"}),
    "available_energy": (f"sensor.{PREFIX}_available_energy", {
        "friendly_name": f"{NAME} Available Energy", "unit_of_measurement": "kWh",
        "device_class": "energy_storage", "state_class": "measurement", "icon": "mdi:car-battery"}),
    "window_energy": (f"sensor.{PREFIX}_window_energy", {
        "friendly_name": f"{NAME} Window Energy", "unit_of_measurement": "kWh",
        "device_class": "energy_storage", "state_class": "measurement", "icon": "mdi:arrow-expand-vertical"}),
    "window_percent": (f"sensor.{PREFIX}_window_percent", {
        "friendly_name": f"{NAME} Window Percent", "unit_of_measurement": "%", "device_class": "battery",
        "state_class": "measurement"}),
    "battery_rate": (f"sensor.{PREFIX}_battery_rate", {
        "friendly_name": f"{NAME} Battery Rate", "unit_of_measurement": "kW", "device_class": "power",
        "state_class": "measurement"}),
    "battery_rate_car": (f"sensor.{PREFIX}_battery_rate_car", {
        "friendly_name": f"{NAME} Battery Rate Car", "unit_of_measurement": "kW", "device_class": "power",
        "state_class": "measurement"}),
    "battery_rate_house": (f"sensor.{PREFIX}_battery_rate_house", {
        "friendly_name": f"{NAME} Battery Rate House", "unit_of_measurement": "kW", "device_class": "power",
        "state_class": "measurement"}),
    "capacity_estimate": (f"sensor.{PREFIX}_capacity_estimate", {
        "friendly_name": f"{NAME} Capacity Estimate", "unit_of_measurement": "kWh",
        "device_class": "energy_storage", "state_class": "measurement", "icon": "mdi:car-battery"}),
    "battery_health": (f"sensor.{PREFIX}_battery_health", {
        "friendly_name": f"{NAME} Battery Health", "unit_of_measurement": "%", "state_class": "measurement",
        "icon": "mdi:battery-heart-variant"}),
    "charge_efficiency": (f"sensor.{PREFIX}_charge_efficiency", {
        "friendly_name": f"{NAME} Charge Efficiency", "unit_of_measurement": "%", "state_class": "measurement",
        "icon": "mdi:transmission-tower-import"}),
    "discharge_efficiency": (f"sensor.{PREFIX}_discharge_efficiency", {
        "friendly_name": f"{NAME} Discharge Efficiency", "unit_of_measurement": "%", "state_class": "measurement",
        "icon": "mdi:transmission-tower-export"}),
    "conversion_loss_today": (f"sensor.{PREFIX}_conversion_loss_today", {
        "friendly_name": f"{NAME} Conversion Loss Today", "unit_of_measurement": "kWh",
        "state_class": "measurement", "icon": "mdi:fire"}),
    "presses_today": (f"sensor.{PREFIX}_presses_today", {
        "friendly_name": f"{NAME} Button Presses Today", "icon": "mdi:gesture-tap-button"}),
}
ALL_SENSORS = [entity_id for entity_id, _ in SENSORS.values()]

REFRESH_S = 300  # everything posted again at least this often, even unchanged


def _pct(fraction) -> Optional[float]:
    return None if fraction is None else round(fraction * 100, 1)


def _onoff(value) -> Optional[str]:
    return None if value is None else ("on" if value else "off")


def values(state) -> dict:
    """The value of each sensor (by its key in SENSORS) from the shared state:
    the value, or (value, extra attributes)."""
    i, energy, last, st = state.inputs or {}, state.energy or {}, state.last_action or {}, state.stats or {}
    action = None
    if last:
        verb = last.get("action") or ""
        action = (f"Failed to {verb}" if last.get("error") else f"Would {verb}" if last.get("observe_only")
                  else "Started" if verb == "start" else "Stopped")
    return {
        "status": (state.status, {"reason": state.reason, "rule": state.rule, "watch_only": state.observe_only}),
        "last_action": (action, {k: last.get(k) for k in ("at", "rule", "reason", "soc", "error")} if last else {}),
        "vehicle_soc": (i.get("soc"), {"read_at": state.soc_at, "from_before_plug_in": state.soc_before_plug_in}),
        "plugged_in": _onoff(i.get("plugged_in")) if i else None,
        "charger_running": (_onoff(i.get("active")) if i else None, {"running_state": i.get("running_state")}),
        "available_energy": energy.get("available_kwh"),
        "window_energy": energy.get("window_kwh"),
        "window_percent": energy.get("window_pct"),
        "battery_rate": (state.rates or {}).get("rate_kw"),
        "battery_rate_car": (state.rates or {}).get("car_kw"),
        "battery_rate_house": (state.rates or {}).get("house_kw"),
        "capacity_estimate": st.get("capacity_kwh"),
        "battery_health": st.get("health_pct"),
        "charge_efficiency": _pct(st.get("charge_efficiency")),
        "discharge_efficiency": _pct(st.get("discharge_efficiency")),
        "conversion_loss_today": st.get("today_car_loss_kwh"),
        "presses_today": state.presses_today,
    }


class SensorPublisher:
    """Decides what to post: anything that changed, everything every REFRESH_S."""

    def __init__(self) -> None:
        self._sent: dict[str, tuple[str, float]] = {}  # entity_id -> (what was posted, when)

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
            attrs = {**attrs, **extra}
            sig = text + json.dumps(extra, sort_keys=True, default=str)
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
