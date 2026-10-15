"""Did the battery actually charge or discharge in a completed session? From
the home battery's SoC sensor (picked on the Settings tab), read back from
Home Assistant's history: its SoC at the session's start and at its end.

- A discharge that took the SoC down by MOVED_PCT or more: "discharged";
  one that didn't: "not_discharged". The same for a charge ("charged",
  "not_charged").
- No readings then (no sensor, or older than HA keeps history: 10 days by
  default): "no_data".

Checked once per session, when it completes (and for earlier ones the first
time a sensor is picked); the result is kept with the session.
"""
from __future__ import annotations

import datetime
import logging
from typing import Optional

from src.dispatches import parse_time

logger = logging.getLogger(__name__)

MOVED_PCT = 2.0  # the SoC moving this much (or more) the right way counts
CHECK_MAX = 10  # sessions checked per read (the first time, there may be many)
HISTORY_DAYS = 10  # older than this, HA likely has no readings (its default)


def _readings(history, entity_id: str) -> list[tuple[float, float]]:
    """HA's history (history/history_during_period) -> [(epoch, value)] in order, numbers only."""
    out = []
    for item in (history or {}).get(entity_id) or []:
        state = item.get("s", item.get("state"))
        when = item.get("lu", item.get("lc"))
        if when is None:
            t = parse_time(item.get("last_updated") or item.get("last_changed"))
            when = t.timestamp() if t else None
        try:
            out.append((float(when), float(state)))
        except (TypeError, ValueError):
            continue
    out.sort()
    return out


def soc_at(readings: list, t: float) -> Optional[float]:
    """The SoC at `t`: the last reading at or before it, else the first after it (within 15 minutes)."""
    before = [v for w, v in readings if w <= t]
    if before:
        return before[-1]
    after = [v for w, v in readings if t < w <= t + 900]
    return after[0] if after else None


def result(kind: Optional[str], readings: list, start: datetime.datetime, end: datetime.datetime) -> dict:
    """{"soc_start", "soc_end", "soc_result"} for a session."""
    a, b = soc_at(readings, start.timestamp()), soc_at(readings, end.timestamp())
    if a is None or b is None:
        return {"soc_start": a, "soc_end": b, "soc_result": "no_data"}
    moved = b - a
    if kind == "discharge":
        verdict = "discharged" if moved <= -MOVED_PCT else "not_discharged"
    elif kind == "charge":
        verdict = "charged" if moved >= MOVED_PCT else "not_charged"
    else:
        verdict = "no_data"
    return {"soc_start": round(a, 1), "soc_end": round(b, 1), "soc_result": verdict}


async def check_sessions(completed: list, soc_entity: Optional[str], query, now: datetime.datetime) -> bool:
    """Add the SoC result to completed sessions that don't have one (for this sensor).
    `query` is HaLink.query. Returns whether any changed."""
    if not soc_entity:
        return False
    changed = 0
    for c in completed:
        if changed >= CHECK_MAX:
            break
        if c.get("soc_entity") == soc_entity and c.get("soc_result"):
            continue
        start, end = parse_time(c.get("start")), parse_time(c.get("end"))
        if start is None or end is None:
            continue
        if now - end > datetime.timedelta(days=HISTORY_DAYS):
            c.update(soc_entity=soc_entity, soc_start=None, soc_end=None, soc_result="no_data")
            changed += 1
            continue
        history = await query({
            "type": "history/history_during_period", "entity_ids": [soc_entity],
            "start_time": (start - datetime.timedelta(hours=3)).isoformat(),
            "end_time": (end + datetime.timedelta(minutes=15)).isoformat(),
            "minimal_response": True, "no_attributes": True, "significant_changes_only": False,
            "include_start_time_state": True,
        })
        c.update(soc_entity=soc_entity, **result(c.get("kind"), _readings(history, soc_entity), start, end))
        changed += 1
    return bool(changed)
