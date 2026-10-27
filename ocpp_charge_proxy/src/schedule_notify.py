"""Notifications when the schedule changes (Settings › Notifications).

Whatever changes it (you on the page or in Home Assistant, a saving session,
Charge now, auto plug-in, the car plugged in sensor, the daily limit...), the
times the schedule has the car plugged in are compared with the last ones
told: a change is sent once it has settled for SETTLE_S (a saving session can
move a slot and add a charge before it in two steps), with each day that
changed, before and after, and what changed it where that's known.

Pure apart from the clock passed in: src/__main__.py runs it and sends the
message through Home Assistant's notify service (src/ha_link.py notify).
"""
from __future__ import annotations

import datetime
from typing import Optional

LOOK_AHEAD = datetime.timedelta(days=7)
SETTLE_S = 60  # a change is sent once nothing more has changed for this long

SOURCE_TEXT = {"auto_plug": "auto plug-in", "charge_now": "Charge now", "car_plugged": "the car plugged in sensor",
               "saving_session": "a charge before a saving session"}


def upcoming(windows: list, now: datetime.datetime) -> tuple:
    """The plugged-in stretches still to come (or going now) in the next week:
    ((start, end), ...), times to the minute."""
    out = []
    for a, b in windows:
        if b <= now or a > now + LOOK_AHEAD:
            continue
        out.append((a.replace(second=0, microsecond=0), b.replace(second=0, microsecond=0)))
    return tuple(sorted(out))


def _day_name(day: datetime.date, today: datetime.date) -> str:
    if day == today:
        return "Today"
    if day == today + datetime.timedelta(days=1):
        return "Tomorrow"
    return day.strftime("%a %d %b").replace(" 0", " ")


def _spans(stretches: list) -> str:
    return ", ".join(f"{a.strftime('%H:%M')}–{b.strftime('%H:%M')}" for a, b in stretches) or "nothing"


def describe(old: tuple, new: tuple, now: datetime.datetime, causes: Optional[dict] = None) -> Optional[str]:
    """What changed between `old` and `new` (from upcoming), a line per day,
    e.g. "Today: 15:30–21:30 → 14:00–18:00, 20:00–22:00 (saving session
    18:00–20:00)"; None if nothing did. A stretch that has started is compared
    from now (it isn't a change that its start has passed)."""
    def by_day(stretches):
        days: dict = {}
        for a, b in stretches:
            if b <= now:
                continue
            days.setdefault(max(a, now).date() if a < now else a.date(), []).append((a, b))
        return days

    before, after = by_day(old), by_day(new)
    lines = []
    for day in sorted(set(before) | set(after)):
        x, y = before.get(day, []), after.get(day, [])
        if x == y:
            continue
        why = (causes or {}).get(day)
        lines.append(f"{_day_name(day, now.date())}: {_spans(x)} → {_spans(y)}" + (f" ({why})" if why else ""))
    return "\n".join(lines) or None


def causes(entries: list, saving_sessions: list, saving_block: bool) -> dict:
    """What's changing each day, where the schedule says: {date: "saving session 18:00–20:00, Charge now"}."""
    out: dict = {}

    def add(day, text):
        if text not in out.setdefault(day, []):
            out[day].append(text)

    if saving_block:
        for r in saving_sessions or []:
            a, b = datetime.datetime.fromisoformat(r["start"]), datetime.datetime.fromisoformat(r["end"])
            add(a.date(), f"saving session {a.strftime('%H:%M')}–{b.strftime('%H:%M')}")
    for e in entries or []:
        text = SOURCE_TEXT.get(e.get("source"))
        if text and e.get("date"):
            add(datetime.date.fromisoformat(e["date"]), text)
    return {day: ", ".join(texts) for day, texts in out.items()}


class Watcher:
    """Tells a change to the schedule once it has settled."""

    def __init__(self) -> None:
        self.told: Optional[tuple] = None  # what was last told (or seen at start-up)
        self.seen: Optional[tuple] = None
        self.seen_at: float = 0.0

    def tick(self, now: datetime.datetime, clock: float, current: tuple, why: Optional[dict] = None) -> Optional[str]:
        """`current` from upcoming. The message to send, or None."""
        if self.told is None:  # start-up (or turned on): nothing to compare with
            self.told = self.seen = current
            return None
        if current != self.seen:
            self.seen, self.seen_at = current, clock
            return None
        if current == self.told or clock - self.seen_at < SETTLE_S:
            return None
        text = describe(self.told, current, now, why)
        self.told = current
        return text

    def reset(self) -> None:
        self.told = self.seen = None
