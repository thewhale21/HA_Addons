"""The V2X battery rate sensors: how fast the plant may charge or discharge
with the car on the DC charger, and how that splits between the home
battery and the car (e.g. for Predbat). The same sums as the "V2X Battery
Rate", "V2X Battery Rate Car" and "V2X Battery Rate House" template
sensors, with their fixed figures as settings.

The car and the home battery are shared in proportion to their sizes (the
car's size being the kWh between its limits), capped at each one's top rate
and, together, at what the plant can do right now.

Pure functions, no I/O: src/manager.py supplies the readings.
"""
from __future__ import annotations

from typing import Optional

RATE_DEFAULTS = {
    "rate_kw": 8.0,  # the plant's rate with the car in V2X (or Solar Surplus) mode...
    "rate_full_kw": 12.5,  # ...and when the home battery is nearly full, or in Fast Charging
    "rate_full_soc_pct": 95.0,  # "nearly full"
    "house_rate_kw": 4.5,  # the home battery's top rate
    "car_rate_kw": 8.0,  # the car's top rate
}
HOME_BATTERY_DEFAULT_KWH = 9.0  # used when the home battery's capacity can't be read


def battery_rates(*, plugged_in: bool, v2x: bool, fast: bool, available_kw: Optional[float],
                  home_soc: Optional[float], home_kwh: Optional[float], car_window_kwh: Optional[float],
                  settings: Optional[dict] = None) -> dict:
    """{"rate_kw", "car_kw", "house_kw"}. `v2x`: plugged in and in V2X (or Solar Surplus)
    mode; `fast`: plugged in and in Fast Charging; `car_window_kwh`: kWh between the limits."""
    t = {**RATE_DEFAULTS, **(settings or {})}
    available = available_kw or 0.0
    house_max, car_max = float(t["house_rate_kw"]), float(t["car_rate_kw"])

    if plugged_in and v2x:
        full = (home_soc or 0.0) >= float(t["rate_full_soc_pct"])
        rate = min(available, float(t["rate_full_kw"] if full else t["rate_kw"]))
    elif plugged_in and fast:
        rate = min(available, float(t["rate_full_kw"]))
    else:
        rate = 0.0

    if not (plugged_in and v2x):
        return {"rate_kw": round(rate, 2), "car_kw": 0.0, "house_kw": round(min(house_max, available), 2)}
    house_size = home_kwh if home_kwh else HOME_BATTERY_DEFAULT_KWH
    car_size = car_window_kwh or 0.0
    if car_size <= 0:
        return {"rate_kw": round(rate, 2), "car_kw": 0.0, "house_kw": round(min(house_max, available), 2)}
    ratio = house_size / car_size
    house = min(house_max, car_max * ratio)  # each gets a share in proportion to its size
    car = house / ratio
    combined = house + car
    if combined > available:  # more than the plant can do: scale both down
        scale = available / combined if combined else 0.0
        house, car = house * scale, car * scale
    return {"rate_kw": round(rate, 2), "car_kw": round(car, 2), "house_kw": round(house, 2)}
