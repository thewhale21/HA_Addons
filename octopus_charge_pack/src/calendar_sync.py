"""Home Assistant calendars of the planned charges and of the planned
discharges, so they can be seen in HA's calendar and used in calendar
triggers ("15 minutes before a discharge...").

Each is a Local Calendar the add-on makes the first time (Settings > Devices
& services > Local Calendar): "Octopus Charge Pack Charge"
(calendar.octopus_charge_pack_charge) and "Octopus Charge Pack Discharge"
(calendar.octopus_charge_pack_discharge). Each is kept in step with the plan: a charge or discharge still
to come is added, and one Octopus takes off the plan before it starts is
removed. Ones that have started are left as they are, so the calendar keeps
the history. Idle dispatches (no energy) aren't added. Only the add-on's own
events are touched (their description says so), so you can add your own.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import time
from typing import Optional

from src.dispatches import _kwh, kind_of, parse_time

logger = logging.getLogger(__name__)

# kind -> (calendar name, the entity ID HA gives it)
CALENDARS = {
    "charge": ("Octopus Charge Pack Charge", "calendar.octopus_charge_pack_charge"),
    "discharge": ("Octopus Charge Pack Discharge", "calendar.octopus_charge_pack_discharge"),
}
MARK = "Planned by Octopus (added by the Octopus Charge Pack add-on)"
RESYNC_S = 600  # checked against the calendar this often even with no change to the plan
CREATE_RETRY_S = 3600  # making the calendar failed: try again after this long


def summary(d: dict) -> str:
    kind = kind_of(d)
    return f"{'Charge' if kind == 'charge' else 'Discharge'} {abs(_kwh(d)):.2f} kWh"


def _utc(value) -> Optional[str]:
    """A time (ISO text, or HA's {"dateTime": ...}) as UTC to the minute, to compare by."""
    if isinstance(value, dict):
        value = value.get("dateTime") or value.get("date_time")
    t = parse_time(value)
    return t.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M") if t else None


def wanted(dispatches: list, now: datetime.datetime, kind: Optional[str] = None) -> dict:
    """The events a calendar should have from now on (`kind`: only charges or
    only discharges): {(start, end, summary): dispatch}."""
    out = {}
    for d in dispatches or []:
        if not isinstance(d, dict) or kind_of(d) == "idle" or (kind and kind_of(d) != kind):
            continue
        end = parse_time(d.get("end"))
        if end is None or end <= now:
            continue
        out[(_utc(d.get("start")), _utc(d.get("end")), summary(d))] = d
    return out


def plan(events: list, dispatches: list, now: datetime.datetime, kind: Optional[str] = None) -> tuple[list, list]:
    """What to do to a calendar: (events to delete (theirs, by uid), dispatches to add).
    Only the add-on's own events, and only ones that haven't started, are deleted."""
    want = wanted(dispatches, now, kind)
    have = {}
    delete = []
    for e in events or []:
        if MARK not in (e.get("description") or ""):
            continue
        key = (_utc(e.get("start")), _utc(e.get("end")), e.get("summary"))
        start = parse_time((e.get("start") or {}).get("dateTime") if isinstance(e.get("start"), dict) else e.get("start"))
        if key in want and key not in have:
            have[key] = e
        elif start is not None and start > now:
            delete.append(e)  # off the plan (or there twice) and not started
    add = [d for key, d in want.items() if key not in have]
    return delete, add


class CalendarSync:
    """Both calendars (one Calendar per kind)."""

    def __init__(self, link, state) -> None:
        self._one = {kind: Calendar(link, kind) for kind in CALENDARS}
        self._state = state
        state.calendar = {"enabled": True, "calendars": {k: c.info for k, c in self._one.items()}}

    async def sync(self, dispatches: list, now: datetime.datetime, enabled: bool = True) -> None:
        self._state.calendar["enabled"] = enabled
        if not enabled:
            return
        for cal in self._one.values():
            await cal.sync(dispatches, now)


class Calendar:
    def __init__(self, link, kind: str) -> None:
        self._link = link
        self.kind = kind
        self.name, self.default_id = CALENDARS[kind]
        self.entity_id: Optional[str] = None
        self._synced: Optional[tuple] = None  # (what was wanted, when)
        self._create_failed_at = 0.0
        self.info = {"name": self.name, "entity_id": None, "error": None, "synced_at": None}

    async def _find(self) -> Optional[str]:
        states = await self._link.all_states()
        for st in states:
            eid = st.get("entity_id", "")
            if eid == self.default_id or (eid.startswith("calendar.")
                                          and (st.get("attributes") or {}).get("friendly_name") == self.name):
                return eid
        return None

    async def _create(self) -> None:
        """A Local Calendar called self.name, through its config flow."""
        flow = await self._link.rest("POST", "config/config_entries/flow", {"handler": "local_calendar"})
        if (flow or {}).get("type") != "form":
            raise RuntimeError(f"Local Calendar couldn't be set up ({(flow or {}).get('reason') or (flow or {}).get('type')})")
        fields = {f.get("name") for f in flow.get("data_schema") or []}
        data = {"calendar_name": self.name}
        if "import" in fields:
            data["import"] = "create_empty"
        done = await self._link.rest("POST", f"config/config_entries/flow/{flow['flow_id']}", data)
        if (done or {}).get("type") != "create_entry":
            raise RuntimeError(f"Local Calendar couldn't be set up ({(done or {}).get('reason') or (done or {}).get('errors') or (done or {}).get('type')})")
        logger.info("Made the %s calendar (Local Calendar)", self.name)
        self._link.forget_states()

    async def sync(self, dispatches: list, now: datetime.datetime) -> None:
        info = self.info
        if not self._link.connected:
            return
        sig = hashlib.sha1(json.dumps(sorted(map(str, wanted(dispatches, now, self.kind))), default=str).encode()).hexdigest()
        if self._synced and self._synced[0] == sig and time.time() - self._synced[1] < RESYNC_S and self.entity_id:
            return
        try:
            self.entity_id = await self._find()
            if self.entity_id is None:
                if time.time() - self._create_failed_at < CREATE_RETRY_S:
                    return
                try:
                    await self._create()
                except Exception:
                    self._create_failed_at = time.time()
                    raise
                self.entity_id = await self._find()
                if self.entity_id is None:
                    return  # (it shows up shortly: next read)
            info["entity_id"] = self.entity_id
            lo = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            hi = (now + datetime.timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
            events = await self._link.rest("GET", f"calendars/{self.entity_id}?start={lo}&end={hi}") or []
            delete, add = plan(events, dispatches, now, self.kind)
            for e in delete:
                await self._link.query({"type": "calendar/event/delete", "entity_id": self.entity_id, "uid": e["uid"]})
                logger.info("Calendar: removed %s %s (off the plan)", e.get("summary"), _utc(e.get("start")))
            for d in add:
                await self._link.query({"type": "calendar/event/create", "entity_id": self.entity_id, "event": {
                    "summary": summary(d), "dtstart": d["start"], "dtend": d["end"], "description": MARK}})
                logger.info("Calendar: added %s %s", summary(d), d["start"])
            self._synced = (sig, time.time())
            info.update(error=None, synced_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        except Exception as err:
            message = str(err) or type(err).__name__
            if info.get("error") != message:
                logger.warning("Couldn't update the %s calendar: %s", self.name, message)
            info["error"] = message
