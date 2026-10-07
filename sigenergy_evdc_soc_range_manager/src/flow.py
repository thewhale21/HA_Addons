"""Who's powering what right now, for the Overview's power flow diagram:
solar, the grid, the home battery and the car (with the house) shared out
the way the Home Assistant power flow cards do it.

The car hangs off the house in the diagram, so the "house side" is the
house's use plus the car charging, minus the car discharging. If the car
gives more than the house uses, the house side becomes a source too (its
spare goes to the grid or the home battery).

Each source feeds sinks in a fixed order: solar first to the house side,
then the home battery, then the grid; then the home battery, the grid and
the house side's spare. Pure: src/manager.py supplies the readings (kW).
"""
from __future__ import annotations

from typing import Optional

MIN_KW = 0.01


def house_load(pv: Optional[float], grid: Optional[float], batt: Optional[float], car: float,
               measured: Optional[float] = None) -> Optional[float]:
    """The house's use (kW): the measured sensor if there is one, otherwise what's left
    over (`car`: positive charging, negative discharging; `batt`: positive charging)."""
    if measured is not None:
        return max(0.0, measured)
    if pv is None or grid is None or batt is None:
        return None
    return max(0.0, max(pv, 0.0) + grid - batt - car)


def flows(pv: Optional[float], grid: Optional[float], batt: Optional[float], car: float,
          house: Optional[float]) -> dict:
    """kW along each line: solar_house, solar_battery, solar_grid, grid_house,
    grid_battery, battery_house, battery_grid, house_grid, house_battery."""
    pv, grid, batt, house = max(pv or 0.0, 0.0), grid or 0.0, batt or 0.0, house or 0.0
    side = house + car  # what the house side needs (negative: it has spare)
    supply = {"solar": pv, "grid": max(grid, 0.0), "battery": max(-batt, 0.0), "house": max(-side, 0.0)}
    demand = {"house": max(side, 0.0), "battery": max(batt, 0.0), "grid": max(-grid, 0.0)}
    order = [("solar", "house"), ("solar", "battery"), ("solar", "grid"),
             ("battery", "house"), ("battery", "grid"),
             ("grid", "house"), ("grid", "battery"),
             ("house", "battery"), ("house", "grid")]
    out = {}
    for src, dst in order:
        amount = min(supply[src], demand[dst])
        if amount > MIN_KW:
            supply[src] -= amount
            demand[dst] -= amount
            out[f"{src}_{dst}"] = round(amount, 3)
    return out
