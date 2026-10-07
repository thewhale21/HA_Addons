from __future__ import annotations

import datetime

from src.charger_sim import ChargerReading


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sv(
    value: str, measurand: str, context: str, unit: str | None = None,
    location: str = "Outlet",
) -> dict:
    """Build a single sampled value with full OCPP metadata."""
    entry = {
        "format": "Raw",
        "location": location,
        "context": context,
        "measurand": measurand,
        "value": value,
    }
    if unit is not None:
        entry["unit"] = unit
    return entry


# Measurand used when MeterValuesAlignedData is empty (OCPP 1.6 default measurand)
DEFAULT_MEASURAND = "Energy.Active.Import.Register"


def _available_values(
    reading: ChargerReading | None, energy_register_wh: int,
    soc: float | None = None,
) -> dict[str, tuple[str, str | None]]:
    """Every measurand we can report right now -> (value, unit).

    reading=None means idle (not delivering power). soc is the car's state of
    charge in %, or None when there's no SoC entity / the car isn't connected.
    """
    values: dict[str, tuple[str, str | None]] = {
        "Energy.Active.Import.Register": (str(float(energy_register_wh)), "Wh"),
        "Energy.Active.Export.Register": ("0", "Wh"),
        "Power.Active.Export": ("0", "W"),
    }
    if reading is None:
        values["Power.Active.Import"] = ("0.0", "W")
    else:
        values["Power.Active.Import"] = (str(round(reading.power_kw * 1000, 1)), "W")
        values["Frequency"] = (str(reading.frequency_hz), None)
        values["Power.Offered"] = (str(round(reading.power_offered_kw * 1000)), "W")
        values["Current.Offered"] = (str(reading.current_offered_a), "A")
    if soc is not None:
        values["SoC"] = (str(int(round(soc))), "Percent")
    return values


def build_meter_values(
    reading: ChargerReading | None,
    energy_register_wh: int,
    context: str,
    measurands: list[str] | None = None,
    timestamp: str | None = None,
    soc: float | None = None,
) -> list[dict]:
    """Meter values containing only the requested measurands, in request order.

    Measurands we can't supply (e.g. SoC without a SoC entity, or Frequency
    while idle) are skipped. An empty/None list falls back to
    Energy.Active.Import.Register.
    """
    available = _available_values(reading, energy_register_wh, soc)
    wanted = measurands or [DEFAULT_MEASURAND]
    sampled = []
    seen = set()
    for m in wanted:
        if m in available and m not in seen:
            value, unit = available[m]
            # SoC is measured by the car, not at the charger's outlet
            location = "EV" if m == "SoC" else "Outlet"
            sampled.append(_sv(value, m, context, unit, location))
            seen.add(m)
    return [{"timestamp": timestamp or _now_iso(), "sampledValue": sampled}]


def build_idle_meter_values(energy_register_wh: int) -> list[dict]:
    """Periodic meter values when idle (not charging)."""
    ctx = "Sample.Periodic"
    return [
        {
            "timestamp": _now_iso(),
            "sampledValue": [
                _sv(str(float(energy_register_wh)), "Energy.Active.Import.Register", ctx, "Wh"),
                _sv("0.0", "Power.Active.Import", ctx, "W"),
                _sv("0", "Energy.Active.Export.Register", ctx, "Wh"),
                _sv("0", "Power.Active.Export", ctx, "W"),
            ],
        }
    ]


def build_charging_meter_values(
    reading: ChargerReading,
    energy_register_wh: int,
) -> list[dict]:
    """Periodic meter values during active charging."""
    ctx = "Sample.Periodic"
    return [
        {
            "timestamp": _now_iso(),
            "sampledValue": [
                _sv(str(float(energy_register_wh)), "Energy.Active.Import.Register", ctx, "Wh"),
                _sv(str(round(reading.power_kw * 1000, 1)), "Power.Active.Import", ctx, "W"),
                _sv(str(reading.frequency_hz), "Frequency", ctx),
                _sv(str(round(reading.power_offered_kw * 1000)), "Power.Offered", ctx, "W"),
                _sv(str(reading.current_offered_a), "Current.Offered", ctx, "A"),
                _sv("0", "Energy.Active.Export.Register", ctx, "Wh"),
                _sv("0", "Power.Active.Export", ctx, "W"),
            ],
        }
    ]