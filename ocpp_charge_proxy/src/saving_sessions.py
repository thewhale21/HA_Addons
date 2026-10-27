"""Saving sessions (Octopus Saving Sessions / Power Down, E.ON Next Saver
Sessions, EDF's sessions...), read from a Home Assistant calendar.

Pure functions, no I/O: src/ha_link.py reads the calendar (calendar.get_events)
and src/automation.py adjusts the schedule around the sessions.

The calendar is the one picked on the Automations tab, or found by its name:
- Octopus Energy (BottlecapDave's integration):
  calendar.octopus_energy_<account>_octoplus_power_down, or the older
  calendar.octopus_energy_<account>_octoplus_saving_sessions;
- E.ON Next, EDF and others: a calendar whose ID or name mentions saving
  or saver sessions, power down or demand flexibility.
Calendars for the opposite (Octopus Power Up, free electricity) are left out.

Or from sensors (sensor_events): Axle Energy's next event is three sensors,
sensor.axle_energy_event_start, _end and _type; its "export" events are saving
sessions (its "import" ones, use more, are left out). The sources are in
src/suppliers.json (saving_sessions.sensors).
"""
from __future__ import annotations

import datetime
import re
from typing import Optional

from src import suppliers

# The words in a calendar's ID or name that mean saving sessions (and the
# opposite), and each supplier's own words, are in src/suppliers.json
MAX_SESSION = datetime.timedelta(hours=6)  # longer than this isn't a saving session (e.g. a bad event)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def is_saving_calendar(entity_id: str, name: str = "") -> bool:
    """A calendar that holds saving sessions, judging by its ID and name."""
    if not str(entity_id).startswith("calendar."):
        return False
    text = _norm(entity_id) + "__" + _norm(name)
    words = suppliers.saving_words()
    if any(w in text for w in words["not_words"]):
        return False
    return any(w in text for w in words["words"])


def supplier_of(entity_id: str, name: str = "") -> Optional[str]:
    """Whose calendar it is, if its ID or name says (for the page)."""
    text = _norm(entity_id) + "_" + _norm(name)
    tokens = set(text.split("_"))
    for s in suppliers.all_suppliers():
        if any((w in tokens) if "_" not in w else (w in text) for w in s.get("calendar_words") or []):
            return s["name"]
    return None


def find_calendar(states: list) -> Optional[str]:
    """The saving sessions calendar among HA's states, if there's one:
    Octopus's Power Down first (it replaces Saving Sessions), then the rest."""
    found = [st.get("entity_id", "") for st in states or []
             if is_saving_calendar(st.get("entity_id", ""), ((st.get("attributes") or {}).get("friendly_name") or ""))]
    if not found:
        return None
    prefer = suppliers.saving_words()["prefer"]
    return sorted(found, key=lambda e: (0 if any(w in e for w in prefer) else 1, e))[0]


def _when(value) -> Optional[datetime.datetime]:
    """An event's start or end: a date and time (aware). All-day events (a date) give None."""
    if isinstance(value, dict):
        value = value.get("dateTime") or value.get("date_time")
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.astimezone()


def parse_events(response, entity_id: str, now: datetime.datetime, past: bool = False) -> list[dict]:
    """calendar.get_events' response -> the sessions not yet over, in order:
    [{"start", "end" (aware datetimes), "summary"}] (with `past`, the ones that
    are over instead, for the Sessions tab). All-day events, events that end
    before they start and ones longer than MAX_SESSION are left out."""
    events = ((response or {}).get(entity_id) or {}).get("events") or []
    out = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        start, end = _when(ev.get("start")), _when(ev.get("end"))
        if start is None or end is None or end <= start or end - start > MAX_SESSION or (end > now if past else end <= now):
            continue
        out.append({"start": start, "end": end, "summary": str(ev.get("summary") or "Saving session")[:80]})
    return merge(out)


def merge(sessions: list[dict]) -> list[dict]:
    """In order, with overlapping ones (e.g. the same session twice, or from a
    calendar and a sensor) made one."""
    merged: list[dict] = []
    for s in sorted(sessions, key=lambda s: s["start"]):
        if merged and s["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], s["end"])
        else:
            merged.append(dict(s))
    return merged


NO_READING = ("", "unknown", "none")


def find_sensor_sources(states: list) -> list[dict]:
    """The sensor sources (src/suppliers.json saving_sessions.sensors) found in
    HA's states: [{"name", "types", "start", "end", "type" (entity IDs; "type" may be None)}].
    The end and type sensors are the ones named like the start one found."""
    ids = {st.get("entity_id", "") for st in states or []}
    found = []
    for src in suppliers.saving_words().get("sensors") or []:
        for start in sorted(e for e in ids if e.startswith("sensor.") and e.endswith(src["start"])):
            stem = start[:-len(src["start"])]
            end = stem + src["end"]
            if end not in ids:
                continue
            kind = stem + src["type"] if src.get("type") else None
            found.append({"name": src["name"], "types": src.get("types"), "start": start, "end": end,
                          "type": kind if kind in ids else None})
            break  # one of each
    return found


def sensor_events(states: list, sources: list[dict], now: datetime.datetime,
                  look_ahead: datetime.timedelta) -> Optional[list[dict]]:
    """The sources' events not yet over, as parse_events gives them. None if a
    sensor is unavailable (e.g. while its integration starts up), so the sessions
    already known aren't taken as cancelled."""
    by_id = {st.get("entity_id", ""): st for st in states or []}
    out = []
    for src in sources:
        readings = {k: str((by_id.get(src[k]) or {}).get("state") or "").strip()
                    for k in ("start", "end", "type") if src.get(k)}
        if any(v == "unavailable" for v in readings.values()):
            return None
        if src.get("type") and src.get("types") and readings.get("type", "").lower() not in src["types"]:
            continue  # no event, or one of another type (Axle: "import", use more)
        if readings["start"].lower() in NO_READING or readings["end"].lower() in NO_READING:
            continue
        start, end = _when(readings["start"]), _when(readings["end"])
        if start is None or end is None or end <= start or end - start > MAX_SESSION or end <= now \
                or start > now + look_ahead:
            continue
        kind = readings.get("type")
        out.append({"start": start, "end": end,
                    "summary": f"{src['name']} event" + (f" ({kind})" if kind else "")})
    return out


def session_id(start: datetime.datetime, end: datetime.datetime) -> str:
    return start.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M") + "-" + \
        end.astimezone(datetime.timezone.utc).strftime("%H%M")
