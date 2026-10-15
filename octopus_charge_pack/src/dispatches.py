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

NO_DATE = "1999-01-01"  # the date when there's no dispatch of that kind (as the discharge template did)


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


def dispatch_times(dispatch: Optional[dict], tz: Optional[datetime.tzinfo],
                   previous: dict) -> dict:
    """A dispatch's local start and end, as dates and times:

    - start_date / end_date: YYYY-MM-DD, or 1999-01-01 when there's none. A dispatch that runs
      past midnight ends on the next day's date, at its real end time;
    - start_time: HH:MM:SS, or the last one when there's none;
    - end_time: HH:MM:SS, or the start time when there's none;
    - date: the start date (the old single date sensor, kept for existing configs).

    `previous` is the last result (kept between restarts), `tz` the local timezone (None: the system's)."""
    start = parse_time((dispatch or {}).get("start"))
    end = parse_time((dispatch or {}).get("end"))
    out = {"start_date": NO_DATE, "end_date": NO_DATE, "start_time": previous.get("start_time"), "end_time": None}
    if start is not None:
        start_local = start.astimezone(tz)
        out["start_date"] = out["end_date"] = start_local.strftime("%Y-%m-%d")
        out["start_time"] = start_local.strftime("%H:%M:%S")
        if end is not None:
            end_local = end.astimezone(tz)
            out["end_date"] = end_local.strftime("%Y-%m-%d")
            out["end_time"] = end_local.strftime("%H:%M:%S")
    if out["end_time"] is None:
        out["end_time"] = out["start_time"]
    out["date"] = out["start_date"]
    return out


def summarise(dispatches: list, now: datetime.datetime, tz: Optional[datetime.tzinfo], previous: dict) -> dict:
    """Everything the sensors show, from the planned dispatches. `previous` holds the last
    charge_start_time and discharge_start_time (kept when none is planned)."""
    out = {"count": len(dispatches or []), "dispatches": list(dispatches or [])}
    for kind in ("charge", "discharge"):
        d = next_dispatch(dispatches, kind, now)
        out[f"{kind}_start"] = (d or {}).get("start")
        out[f"{kind}_end"] = (d or {}).get("end")
        out[f"{kind}_kwh"] = _kwh(d) if d else None
        times = dispatch_times(d, tz, {"start_time": previous.get(f"{kind}_start_time")})
        out.update({f"{kind}_{k}": v for k, v in times.items()})
    return out
