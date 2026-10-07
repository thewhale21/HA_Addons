"""One-tap holds from the Overview: a one-off schedule entry from now until
a time (or for so many hours), made from the car's SoC now.

- no_discharge: the low limit at the car's SoC now, so it isn't discharged
  any further (it can still charge).
- hold: the low limit at the SoC now and the high limit 1% above it, so it
  stays where it is.
- at_least: the low limit at a level you give (e.g. 90% for a trip).

They're ordinary schedule entries (src/schedule.py): they show on the
Schedule tab, and end by themselves.
"""
from __future__ import annotations

import datetime
from typing import Optional

from src.controller import SOC_CEILING, SOC_FLOOR

KINDS = ("no_discharge", "hold", "at_least")
MAX_HOURS = 23.75  # a one-off entry runs at most to the same time the next day


def make_hold(kind: str, soc: Optional[float], now: datetime.datetime, *, until: Optional[str] = None,
              hours: Optional[float] = None, low: Optional[float] = None) -> dict:
    """The schedule entry for a hold (raises ValueError)."""
    if kind not in KINDS:
        raise ValueError("kind must be one of: " + ", ".join(KINDS))
    start = now.replace(second=0, microsecond=0)
    if hours is not None:
        hours = float(hours)
        if not 0.25 <= hours <= MAX_HOURS:
            raise ValueError("A hold lasts from 15 minutes to a day")
        end = start + datetime.timedelta(hours=hours)
    elif until:
        h, m = (int(x) for x in str(until).split(":"))
        end = start.replace(hour=h, minute=m)
        if end <= start:
            end += datetime.timedelta(days=1)
    else:
        raise ValueError("Say how long: hours or until")
    if end - start < datetime.timedelta(minutes=15):
        raise ValueError("A hold lasts at least 15 minutes")
    if kind in ("no_discharge", "hold") and soc is None:
        raise ValueError("The car's SoC isn't known yet")
    entry = {"kind": "once", "date": start.date().isoformat(), "start": start.strftime("%H:%M"),
             "end": end.strftime("%H:%M"), "high": None, "low": None}
    if kind == "no_discharge":
        entry["low"] = max(SOC_FLOOR, min(round(soc), SOC_CEILING - 1))
        entry["label"] = f"Hold: no discharging below {entry['low']:g}%"
    elif kind == "hold":
        entry["low"] = max(SOC_FLOOR, min(round(soc), SOC_CEILING - 1))
        entry["high"] = entry["low"] + 1
        entry["label"] = f"Hold at {entry['low']:g}%"
    else:
        if low is None:
            raise ValueError("Say what level to keep it at")
        entry["low"] = float(low)
        entry["label"] = f"Hold: at least {float(low):g}%"
    return entry
