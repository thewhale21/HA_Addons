"""The battery's live readings from Octopus: SmartFlexInverter.telemetry (what Octopus
gets from the inverter's own cloud, so it can be a few minutes behind) and its status.

Pure functions, no I/O: src/octopus.py reads it with the plan, src/ha_entities.py posts
the sensors and the Overview's power flow card draws it.

Signs, as seen on a Sigenergy SigenStor, discharging and charging from the grid:
- battery power: + discharging, - charging (passed on as it is: what Home Assistant expects);
- grid power: Octopus sends + exporting, - importing. Turned round here (+ importing,
  - exporting), like the Octopus Energy integration's current demand sensor and as Home
  Assistant's energy dashboard expects;
- inverter power: + putting power out, - taking it in; export: + or 0;
- site consumption: what the home uses; negative when something else on the inverter (e.g. a
  DC car charger discharging the car) is feeding the home.
"""
from __future__ import annotations

from typing import Optional


def _num(value) -> Optional[float]:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _part(parent: dict, key: str) -> dict:
    value = (parent or {}).get(key)
    return value if isinstance(value, dict) else {}


def parse_device(device: Optional[dict], read_at: Optional[str] = None) -> Optional[dict]:
    """The readings and status from a devices(...) item ({id, status, telemetry, details}); None
    when there's no telemetry (a device that isn't an inverter, or Octopus didn't send it)."""
    if not isinstance(device, dict):
        return None
    telemetry = device.get("telemetry")
    status = _part(device, "status")
    if not isinstance(telemetry, dict):
        return None
    grid = _num(_part(telemetry, "grid").get("powerInKw"))
    return {
        "battery_soc": _num(_part(telemetry, "battery").get("stateOfCharge")),
        "battery_power_kw": _num(_part(telemetry, "battery").get("powerInKw")),
        "battery_connection": _part(telemetry, "battery").get("connectionStatus"),
        "inverter_power_kw": _num(_part(telemetry, "inverter").get("powerInKw")),
        "inverter_connection": _part(telemetry, "inverter").get("connectionStatus"),
        "solar_power_kw": _num(_part(telemetry, "solar").get("powerInKw")),
        "grid_power_kw": -grid if grid else grid,  # + importing, - exporting (0 stays 0)
        "home_consumption_kw": _num(_part(telemetry, "site").get("consumptionInKw")),
        "export_power_kw": _num(_part(telemetry, "site").get("exportInKw")),
        "peak_solar_kw": _num(_part(_part(device, "details"), "solar").get("peakSolarPowerInKw")),
        "state": status.get("currentState"),
        "status": status.get("current"),
        "is_suspended": status.get("isSuspended"),
        "read_at": read_at,
    }
