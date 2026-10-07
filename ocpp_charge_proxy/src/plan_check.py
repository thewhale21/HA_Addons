"""Check your supplier's plan against the schedule (Force schedule on supplier).

While the schedule has the car plugged in (a "stretch", e.g. 16:00 to 18:00)
and it has set the supplier's ready time for that stretch's unplug, the
supplier's planned charge slots up to that ready time should all sit inside
the stretch: a slot that runs past the unplug would expect the car to be
plugged in when the schedule has unplugged it. The ready time on the
supplier's side should still be the one the schedule set (it may have been
changed in the supplier's app since).

Only the current stretch is checked, up to its ready time: with stretches
16:00-18:00 and 20:00-22:00, the first is checked from 16:00 (slots up to
18:00), the second from 20:00 (slots up to 22:00).

Kept free of I/O so it can be tested on its own.
"""

from __future__ import annotations

import datetime
from typing import Optional

SETTLE_S = 300  # after plugging in, give the supplier this long to plan before checking
TOLERANCE_S = 60  # slots ending this close after the unplug are fine


def _dt(value) -> Optional[datetime.datetime]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    try:
        dt = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def _iso(dt: Optional[datetime.datetime]) -> Optional[str]:
    return dt.isoformat(timespec="minutes") if dt else None


def _hm(dt: datetime.datetime, tz) -> str:
    return dt.astimezone(tz).strftime("%H:%M")


def _hhmm(value) -> Optional[str]:
    """'07:30', '07:30:00' -> '07:30'; anything else -> None."""
    s = str(value or "")
    parts = s.split(":")
    if len(parts) < 2 or not (parts[0].isdigit() and parts[1][:2].isdigit()):
        return None
    return f"{int(parts[0]):02d}:{int(parts[1][:2]):02d}"


def check_plan(slots: list, start: datetime.datetime, end: datetime.datetime,
               until: Optional[datetime.datetime] = None, ready_set: Optional[str] = None,
               supplier_ready: Optional[str] = None, provider: str = "Your supplier") -> dict:
    """slots: the supplier's running and planned slots [{"start", "end"} ISO].
    start / end: the stretch the schedule has the car plugged in (aware).
    until: the ready time set for it (default: the unplug). ready_set: that
    ready time as "HH:MM"; supplier_ready: what the supplier's setting says now.

    Returns {"status": "ok" | "error" | "none", "start", "end", "until",
    "slots": [{"start", "end", "ok"}], "problems": [text]}."""
    tz = start.tzinfo
    until = until or end
    problems = []
    checked = []
    for s in slots or []:
        a, b = _dt(s.get("start")), _dt(s.get("end"))
        if a is None or b is None or a >= until:
            continue  # after the ready time: checked with the stretch it falls in
        ok = (b - end).total_seconds() <= TOLERANCE_S
        if not ok:
            problems.append(f"{provider} plans a slot {_hm(a, tz)}–{_hm(b, tz)}, "
                            f"past the schedule's unplug at {_hm(end, tz)}")
        checked.append({"start": _iso(a), "end": _iso(b), "ok": ok})
    want, have = _hhmm(ready_set), _hhmm(supplier_ready)
    if want and have and want != have:
        problems.insert(0, f"{provider}'s ready time is {have}, not the {want} the schedule set "
                           + ("(changed in the supplier's app?)" if provider == "Your supplier"
                              else f"(changed in the {provider} app?)"))
    status = "error" if problems else "ok" if checked else "none"
    return {"status": status, "start": _iso(start), "end": _iso(end), "until": _iso(until),
            "slots": checked, "problems": problems}
