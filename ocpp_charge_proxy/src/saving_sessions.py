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


def parse_events(response, entity_id: str, now: datetime.datetime) -> list[dict]:
    """calendar.get_events' response -> the sessions not yet over, in order:
    [{"start", "end" (aware datetimes), "summary"}]. All-day events, events
    that end before they start and ones longer than MAX_SESSION are left out."""
    events = ((response or {}).get(entity_id) or {}).get("events") or []
    out = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        start, end = _when(ev.get("start")), _when(ev.get("end"))
        if start is None or end is None or end <= start or end - start > MAX_SESSION or end <= now:
            continue
        out.append({"start": start, "end": end, "summary": str(ev.get("summary") or "Saving session")[:80]})
    out.sort(key=lambda s: s["start"])
    # overlapping events (e.g. the same session twice) become one
    merged: list[dict] = []
    for s in out:
        if merged and s["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], s["end"])
        else:
            merged.append(dict(s))
    return merged


def session_id(start: datetime.datetime, end: datetime.datetime) -> str:
    return start.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M") + "-" + \
        end.astimezone(datetime.timezone.utc).strftime("%H%M")
