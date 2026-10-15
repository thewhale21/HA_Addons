"""Octopus Intelligent flex dispatches (Charge Pack sessions) turned into the
sensors' values, as the old REST and template sensors worked them out.

Pure functions, no I/O: src/__main__.py fetches the dispatches
(src/octopus.py) and src/ha_entities.py posts the results.

Which way a dispatch goes is read from energyAddedKwh, as the templates did:
- a **charge** dispatch has energyAddedKwh below 0,
- a **discharge** dispatch has energyAddedKwh above 0.
"""
from __future__ import annotations

import datetime
from typing import Optional

NO_DATE = "1999-01-01"  # the discharge date when there's no discharge dispatch (as the template did)


def parse_time(value) -> Optional[datetime.datetime]:
    """An ISO 8601 time from the API (with "Z" or an offset), timezone-aware; None if it isn't one."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def _kwh(d: dict) -> float:
    try:
        return float(d.get("energyAddedKwh") or 0)
    except (TypeError, ValueError):
        return 0.0


def next_dispatch(dispatches: list, kind: str, now: datetime.datetime) -> Optional[dict]:
    """The first dispatch (in the API's order) of `kind` ("charge" or "discharge") that hasn't ended."""
    for d in dispatches or []:
        if not isinstance(d, dict):
            continue
        kwh = _kwh(d)
        if (kind == "charge" and kwh < 0) or (kind == "discharge" and kwh > 0):
            end = parse_time(d.get("end"))
            if end is not None and end > now:
                return d
    return None


def discharge_times(dispatch: Optional[dict], tz: Optional[datetime.tzinfo],
                    previous: dict) -> dict:
    """The next discharge's local date, start time and end time, as the template sensors gave them:

    - date: YYYY-MM-DD, or 1999-01-01 when there's none;
    - start time: HH:MM:SS, or the last one when there's none;
    - end time: HH:MM:SS, 23:59:59 if it ends on a later day, or the start time when there's none.

    `previous` is the last result (kept between restarts), `tz` the local timezone (None: the system's)."""
    start = parse_time((dispatch or {}).get("start"))
    end = parse_time((dispatch or {}).get("end"))
    out = {"date": NO_DATE, "start_time": previous.get("start_time"), "end_time": None}
    if start is not None:
        start_local = start.astimezone(tz)
        out["date"] = start_local.strftime("%Y-%m-%d")
        out["start_time"] = start_local.strftime("%H:%M:%S")
        if end is not None:
            end_local = end.astimezone(tz)
            out["end_time"] = "23:59:59" if end_local.date() > start_local.date() else end_local.strftime("%H:%M:%S")
    if out["end_time"] is None:
        out["end_time"] = out["start_time"]
    return out


def summarise(dispatches: list, now: datetime.datetime, tz: Optional[datetime.tzinfo], previous: dict) -> dict:
    """Everything the sensors show, from the planned dispatches."""
    charge = next_dispatch(dispatches, "charge", now)
    discharge = next_dispatch(dispatches, "discharge", now)
    return {
        "count": len(dispatches or []),
        "dispatches": list(dispatches or []),
        "charge_start": (charge or {}).get("start"),
        "charge_end": (charge or {}).get("end"),
        "discharge_start": (discharge or {}).get("start"),
        "discharge_end": (discharge or {}).get("end"),
        "discharge_kwh": _kwh(discharge) if discharge else None,
        **{f"discharge_{k}": v for k, v in discharge_times(discharge, tz, {
            "start_time": previous.get("discharge_start_time")}).items()},
    }
