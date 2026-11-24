"""The house's average use, for the automatic schedule's Where it earns the most (Automations ›
Automatic schedule › House load sensor): from a power sensor's hourly statistics in Home Assistant
over the last days, the average kW for each half hour of the day. The planner uses it for what the
house costs on the grid at the dearer import rate while the battery's empty (and, if asked, takes
it off the battery)."""
from __future__ import annotations

import datetime
import logging
from typing import Optional

from src.ha_history import parse_history, parse_statistics
from src.populate_schedule import ENERGY_UNITS, _power_scale

logger = logging.getLogger(__name__)

DAYS = 7  # how many days back the average is over
REFRESH_S = 6 * 3600  # read again this often (and when the sensor changes)
MIN_HOURS = 12  # fewer hours of statistics than this: not used


def profile(rows: list, scale: float, tz: Optional[datetime.tzinfo] = None) -> Optional[list]:
    """Hourly statistics rows ({"start": unix seconds, "mean"}) -> the average kW for each half hour
    of the day from midnight (48; both half hours of an hour the same), local time (tz); an hour of
    the day with no rows gets the average of them all. None with fewer than MIN_HOURS rows."""
    by: dict = {}
    vals = []
    for r in rows:
        try:
            v = max(0.0, float(r.get("mean")) * scale)
        except (TypeError, ValueError):
            continue
        h = datetime.datetime.fromtimestamp(r["start"], tz or datetime.timezone.utc).hour
        by.setdefault(h, []).append(v)
        vals.append(v)
    if len(vals) < MIN_HOURS:
        return None
    mean = sum(vals) / len(vals)
    hours = [sum(by[h]) / len(by[h]) if by.get(h) else mean for h in range(24)]
    return [round(hours[i // 2], 3) for i in range(48)]


def choose(sensor_profile: Optional[list], sensor_status: dict, typed_kw: Optional[float]) -> tuple:
    """(profile, status) to plan with: the sensor's while it can be used, else the average typed in
    (the same every half hour; the sensor's error kept, to show), else none."""
    if sensor_profile:
        return sensor_profile, {**sensor_status, "from": "sensor"}
    if typed_kw:
        return [float(typed_kw)] * 48, {**({"error": sensor_status["error"]} if sensor_status.get("error") else {}),
                                        "kw": float(typed_kw), "from": "typed"}
    return None, dict(sensor_status or {})


def battery_kwh(state: Optional[dict]) -> Optional[float]:
    """A battery size sensor's value in kWh (its unit Wh, kWh or MWh; none: kWh), or None (unknown,
    not a number, or not above 0)."""
    if not state:
        return None
    try:
        v = float(state.get("state"))
    except (TypeError, ValueError):
        return None
    unit = str((state.get("attributes") or {}).get("unit_of_measurement") or "kWh").strip().lower()
    v *= {"wh": 0.001, "mwh": 1000.0}.get(unit, 1.0)
    return round(v, 3) if v > 0 else None


async def read(ha_link, entity_id: str, now: datetime.datetime, days: int = DAYS) -> tuple:
    """(profile or None, status for the page: {"entity", "at", "kw" (the day's average), "error"})."""
    status = {"entity": entity_id, "at": now.isoformat(timespec="seconds")}
    iso = lambda t: t.astimezone(datetime.timezone.utc).isoformat()  # noqa: E731
    scale = 1.0
    try:
        h = await ha_link.query({
            "type": "history/history_during_period",
            "start_time": iso(now - datetime.timedelta(hours=6)), "end_time": iso(now),
            "entity_ids": [entity_id], "minimal_response": False, "no_attributes": False,
            "significant_changes_only": False,
        }, timeout=30) or {}
        hrows = parse_history(h, entity_id)
        attrs = (hrows[-1][2] or {}) if hrows else {}
        unit = attrs.get("unit_of_measurement")
        if attrs.get("device_class") == "energy" or (unit or "").strip().lower() in ENERGY_UNITS:
            return None, {**status, "error": f"an energy sensor ({unit or 'kWh'}): pick a power sensor (W or kW)"}
        vals = []
        for _, st, _ in hrows[-50:]:
            try:
                vals.append(float(st))
            except (TypeError, ValueError):
                pass
        scale, _ = _power_scale(unit, vals)
    except Exception as err:
        logger.debug("House load: unit of %s not found: %s", entity_id, err)
    try:
        result = await ha_link.query({
            "type": "recorder/statistics_during_period",
            "start_time": iso(now - datetime.timedelta(days=days)), "end_time": iso(now),
            "statistic_ids": [entity_id], "period": "hour", "types": ["mean"],
        }, timeout=60) or {}
    except Exception as err:
        return None, {**status, "error": f"couldn't read its history ({err})"}
    prof = profile(parse_statistics(result, entity_id), scale, now.tzinfo)
    if prof is None:
        return None, {**status, "error": "not enough history yet (it needs long-term statistics: a state_class of measurement)"}
    return prof, {**status, "kw": round(sum(prof) / 48, 2), "days": days}
