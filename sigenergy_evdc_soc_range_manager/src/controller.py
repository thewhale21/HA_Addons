"""The decision: start the charger, stop it, or leave it.

The charger only has Start and Stop. Once started, Sigenergy decides
whether the car charges or discharges; this keeps it running only while
that's wanted, so the car's state of charge (SoC) stays between the low and
high limits:

- Between the limits it's always allowed to run.
- At or above the high limit it only runs while the house needs power (so
  the car discharges), and is stopped once it isn't discharging.
- At or below the low limit it only runs when there's spare power to charge
  from (exporting, or a "charge now" signal such as Predbat charging), and
  is stopped if it starts discharging.
- After the charger stops, for whatever reason, it isn't started again for
  the restart wait (some cars stop discharging now and then; this stops it
  being restarted straight away, over and over).

Pure functions, no I/O: src/manager.py gathers the inputs and presses the
buttons.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# The limits can never go outside these, whatever the helpers or the schedule say
SOC_FLOOR = 20.0  # the low limit is at least this
SOC_CEILING = 99.0  # the high limit is at most this


def bound_limits(high: Optional[float], low: Optional[float]) -> tuple:
    """(high, low) kept within SOC_FLOOR..SOC_CEILING, with the low below the high."""
    if high is not None:
        high = min(max(high, SOC_FLOOR + 1), SOC_CEILING)
    if low is not None:
        low = max(min(low, SOC_CEILING - 1), SOC_FLOOR)
    if high is not None and low is not None and low >= high:
        low = high - 1
    return high, low


def check_limit(key: str, value: float) -> float:
    """A limit someone set: refused if it's outside the bounds."""
    if key == "low" and not SOC_FLOOR <= value <= SOC_CEILING - 1:
        raise ValueError(f"The low limit must be between {SOC_FLOOR:g}% and {SOC_CEILING - 1:g}%")
    if key == "high" and not SOC_FLOOR + 1 <= value <= SOC_CEILING:
        raise ValueError(f"The high limit must be between {SOC_FLOOR + 1:g}% and {SOC_CEILING:g}%")
    return value


# The tuning, as saved by the Settings tab (src/app_settings.py)
TUNING_DEFAULTS = {
    "restart_wait_s": 180,  # charger off at least this long before it's started again
    "house_battery_kw": 0.1,  # home battery discharging faster than this = the house needs power
    "house_grid_kw": 0.1,  # ...or importing more than this from the grid
    "export_kw": 0.5,  # exporting more than this = spare power to charge the car from
    "export_hold_s": 10,  # ...for at least this long
    "margin_pct": 0.0,  # starts need the SoC this far inside the limits (stops are at the limits)
    "press_gap_s": 60,  # at least this long between button presses
}


@dataclass
class Inputs:
    plugged_in: bool
    mode_on: Optional[bool]  # in V2X mode (None: can't tell)
    running_state: Optional[str]
    active: bool  # the charger is running (charging, discharging or preparing)
    discharging: bool  # ...and discharging the car
    inactive_for: Optional[float]  # seconds since it stopped (None while running)
    soc: Optional[float]  # the car's last known SoC, %
    high: Optional[float]  # limits, %
    low: Optional[float]
    battery_kw: Optional[float]  # home battery: negative = discharging
    grid_kw: Optional[float]  # grid: positive = importing
    export_kw: Optional[float]  # grid export, kW
    export_held_s: float  # how long export has been above the export level
    ems_mode: Optional[str]
    charge_signal: Optional[bool]  # e.g. Predbat charging (None: not set up)
    ems_blocked: bool = False  # the EMS mode is one that rules out charging from export


@dataclass
class Decision:
    action: Optional[str]  # "start", "stop" or None
    rule: str  # a short key, e.g. "house_needs_power"
    status: str  # a few words for the page and the status sensor
    reason: str  # one sentence: why


RULES = {
    "house_needs_power": "Start: the house needs power",
    "charge_opportunity": "Start: spare power to charge from",
    "in_range": "Start: SoC within the limits",
    "high_limit": "Stop: reached the high limit",
    "low_limit": "Stop: reached the low limit",
}


def _pct(v: float) -> str:
    return f"{v:g}%"


def decide(i: Inputs, tuning: Optional[dict] = None) -> Decision:
    t = {**TUNING_DEFAULTS, **(tuning or {})}
    if not i.plugged_in:
        return Decision(None, "not_plugged_in", "Not plugged in", "The car isn't plugged in.")
    if i.mode_on is None:
        return Decision(None, "mode_unknown", "Mode unknown", "Can't read the V2X mode entity.")
    if not i.mode_on:
        return Decision(None, "not_v2x", "Not in V2X mode", "The charger isn't in V2X mode, so it's left alone.")
    if i.soc is None:
        return Decision(None, "no_soc", "Waiting for the SoC", "The car's state of charge isn't known yet.")
    if i.high is None or i.low is None:
        return Decision(None, "no_limits", "Limits not set", "The high and low limits can't be read.")
    if i.low >= i.high:
        return Decision(None, "bad_limits", "Limits overlap",
                        f"The low limit ({_pct(i.low)}) must be below the high limit ({_pct(i.high)}).")

    soc, high, low, margin = i.soc, i.high, i.low, float(t["margin_pct"])
    wait = float(t["restart_wait_s"])
    rested = not i.active and i.inactive_for is not None and i.inactive_for >= wait
    house_needs = ((i.battery_kw is not None and i.battery_kw < -t["house_battery_kw"])
                   or (i.grid_kw is not None and i.grid_kw > t["house_grid_kw"]))
    house_quiet = (i.battery_kw is not None and i.battery_kw > -t["house_battery_kw"]
                   and i.grid_kw is not None and i.grid_kw < t["house_grid_kw"])
    exporting = (i.export_kw is not None and i.export_kw > t["export_kw"]
                 and i.export_held_s >= t["export_hold_s"] and not i.ems_blocked)
    opportunity = i.charge_signal is True or exporting
    why_spare = "a charge signal is on" if i.charge_signal is True else "you're exporting"

    # 1. The house needs power and the car has some to spare: start, so it can discharge
    if house_needs and rested and soc > low + margin:
        return Decision("start", "house_needs_power", "Starting",
                        f"The house is using the home battery or the grid and the car is at {_pct(soc)}, "
                        f"above the low limit ({_pct(low)}).")
    # 2. Spare power and room in the car: start, so it can charge
    if opportunity and rested and soc < high - margin and not i.discharging:
        return Decision("start", "charge_opportunity", "Starting",
                        f"There's spare power ({why_spare}) and the car is at {_pct(soc)}, "
                        f"below the high limit ({_pct(high)}).")
    # 3. At the high limit and not discharging (nor needed to): stop
    if soc >= high and i.active and not i.discharging and house_quiet:
        return Decision("stop", "high_limit", "Stopping",
                        f"The car is at {_pct(soc)}, at or above the high limit ({_pct(high)}), "
                        "and the house doesn't need its power.")
    # 4. At the low limit and discharging: stop (unless told to charge)
    if soc <= low and i.discharging and i.charge_signal is not True:
        return Decision("stop", "low_limit", "Stopping",
                        f"The car is at {_pct(soc)}, at or below the low limit ({_pct(low)}), and was discharging.")
    # 5. Within the limits: keep it running
    if low + margin < soc < high - margin and rested:
        return Decision("start", "in_range", "Starting",
                        f"The car is at {_pct(soc)}, between the limits ({_pct(low)}–{_pct(high)}).")

    # Nothing to do: say what it's waiting for
    if i.active:
        doing = "Discharging" if i.discharging else ("Charging" if (i.running_state or "").lower() == "charging"
                                                     else "Running")
        return Decision(None, "running", doing, f"The charger is {(i.running_state or 'running').lower()}; "
                        f"the car is at {_pct(soc)} ({_pct(low)}–{_pct(high)}).")
    if not rested and i.inactive_for is not None:
        left = max(0, round(wait - i.inactive_for))
        return Decision(None, "restart_wait", "Restart wait",
                        f"The charger stopped {round(i.inactive_for)} s ago; it can be started again in {left} s.")
    if soc >= high - margin:
        return Decision(None, "held_high", "Held at the high limit",
                        f"The car is at {_pct(soc)}: it starts again when the house needs power.")
    if soc <= low + margin:
        return Decision(None, "held_low", "Held at the low limit",
                        f"The car is at {_pct(soc)}: it starts again when there's spare power to charge from.")
    return Decision(None, "idle", "Idle", f"The car is at {_pct(soc)}.")
