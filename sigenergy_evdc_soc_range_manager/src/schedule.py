"""Scheduled limits: the high and/or low limit changed for a while, every
week (e.g. Tue and Thu 23:00-08:00: high 50%) or once (e.g. 9 Oct
06:00-10:00: low 95%). The limit helpers keep your default limits; while
an entry is on, its limits are used instead. Saved in /data/schedule.json.

When entries overlap, the one that started last wins (per limit). If a
scheduled limit crosses the other one, the other moves out of its way:
a scheduled low of 95% with an default high of 80% makes the high 96%.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import uuid
from typing import Optional

from src.controller import SOC_CEILING, SOC_FLOOR, check_limit

logger = logging.getLogger(__name__)

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_ENTRIES = 50
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _minutes(text: str) -> int:
    m = _TIME.match(str(text or "").strip())
    if not m:
        raise ValueError("Times look like 23:00")
    return int(m.group(1)) * 60 + int(m.group(2))


def validate_entry(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Send a JSON object")
    kind = raw.get("kind")
    if kind not in ("weekly", "once"):
        raise ValueError("kind must be weekly or once")
    start, end = _minutes(raw.get("start")), _minutes(raw.get("end"))
    if start == end:
        raise ValueError("The start and end times must differ")
    out = {"id": str(raw.get("id") or uuid.uuid4().hex[:8]), "kind": kind,
           "start": "%02d:%02d" % divmod(start, 60), "end": "%02d:%02d" % divmod(end, 60),
           "label": str(raw.get("label") or "").strip()[:60], "enabled": raw.get("enabled", True) is not False}
    if kind == "weekly":
        days = [str(d).lower()[:3] for d in (raw.get("days") or [])]
        if not days or any(d not in DAYS for d in days):
            raise ValueError("Pick at least one day")
        out["days"] = [d for d in DAYS if d in days]
    else:
        try:
            out["date"] = datetime.date.fromisoformat(str(raw.get("date"))).isoformat()
        except ValueError:
            raise ValueError("The date looks like 2026-10-09") from None
    for key in ("high", "low"):
        value = raw.get(key)
        if value in (None, ""):
            out[key] = None
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"The {key} limit must be a number") from None
        check_limit(key, value)
        out[key] = value
    if out["high"] is None and out["low"] is None:
        raise ValueError("Set a high limit, a low limit or both")
    if out["high"] is not None and out["low"] is not None and out["low"] >= out["high"]:
        raise ValueError("The low limit must be below the high limit")
    return out


def _windows(entry: dict, now: datetime.datetime) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """The entry's on-periods around `now` (local, naive)."""
    sh, sm = map(int, entry["start"].split(":"))
    eh, em = map(int, entry["end"].split(":"))
    if entry["kind"] == "once":
        days = [datetime.date.fromisoformat(entry["date"])]
    else:
        days = [now.date() + datetime.timedelta(days=d) for d in (-1, 0, 1)]
        days = [d for d in days if DAYS[d.weekday()] in entry["days"]]
    out = []
    for day in days:
        start = datetime.datetime.combine(day, datetime.time(sh, sm))
        end = datetime.datetime.combine(day, datetime.time(eh, em))
        if end <= start:
            end += datetime.timedelta(days=1)  # runs past midnight
        out.append((start, end))
    return out


class Schedule:
    def __init__(self, data_dir: Optional[str] = None) -> None:
        self._path = os.path.join(data_dir, "schedule.json") if data_dir else None
        self.entries: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self._path:
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                for raw in json.load(f) or []:
                    try:
                        self.entries.append(validate_entry(raw))
                    except ValueError:
                        pass
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("The schedule %s is unreadable: starting empty", self._path)

    def _save(self) -> None:
        if not self._path:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.entries, f, indent=1)
            os.replace(tmp, self._path)
        except Exception:
            logger.warning("Could not save the schedule", exc_info=True)

    def add(self, raw: dict) -> dict:
        entry = validate_entry({**raw, "id": None})
        if len(self.entries) >= MAX_ENTRIES:
            raise ValueError(f"At most {MAX_ENTRIES} entries")
        self.entries.append(entry)
        self._save()
        logger.info("Schedule: added %s", describe(entry))
        return entry

    def update(self, entry_id: str, raw: dict) -> dict:
        for n, old in enumerate(self.entries):
            if old["id"] == entry_id:
                self.entries[n] = validate_entry({**old, **raw, "id": entry_id})
                self._save()
                return self.entries[n]
        raise KeyError(entry_id)

    def remove(self, entry_id: str) -> None:
        before = len(self.entries)
        self.entries = [e for e in self.entries if e["id"] != entry_id]
        if len(self.entries) == before:
            raise KeyError(entry_id)
        self._save()

    def tidy(self, now: datetime.datetime) -> None:
        """One-off entries that have finished are removed."""
        keep = [e for e in self.entries if e["kind"] != "once" or any(end > now for _, end in _windows(e, now))]
        if len(keep) != len(self.entries):
            self.entries = keep
            self._save()

    def active(self, now: datetime.datetime) -> list[dict]:
        """Entries on now, the latest started last, each with its end."""
        out = []
        for e in self.entries:
            if not e.get("enabled", True):
                continue
            for start, end in _windows(e, now):
                if start <= now < end:
                    out.append({**e, "started": start.isoformat(timespec="minutes"),
                                "until": end.isoformat(timespec="minutes")})
                    break
        return sorted(out, key=lambda e: e["started"])

    def upcoming(self, now: datetime.datetime, limit: int = 5) -> list[dict]:
        """The next on-periods that haven't started, soonest first."""
        out = []
        for e in self.entries:
            if not e.get("enabled", True):
                continue
            ws = _windows(e, now)
            if e["kind"] == "weekly":  # look a week ahead
                ws = []
                for d in range(0, 8):
                    day = now.date() + datetime.timedelta(days=d)
                    if DAYS[day.weekday()] in e["days"]:
                        ws += [w for w in _windows({**e, "kind": "once", "date": day.isoformat()}, now)]
            for start, end in ws:
                if start > now:
                    out.append({**e, "starts": start.isoformat(timespec="minutes"), "until": end.isoformat(timespec="minutes")})
                    break
        return sorted(out, key=lambda e: e["starts"])[:limit]

    def apply(self, high: Optional[float], low: Optional[float], now: datetime.datetime) -> tuple:
        """(high, low, the entries setting them): the default limits with the schedule on top."""
        on = self.active(now)
        sched_high = sched_low = None
        for e in on:  # the latest started wins
            if e["high"] is not None:
                sched_high = e["high"]
            if e["low"] is not None:
                sched_low = e["low"]
        if sched_high is not None:
            high = sched_high
            if low is not None and sched_low is None and low >= high:
                low = max(SOC_FLOOR, high - 1)
        if sched_low is not None:
            low = sched_low
            if high is not None and sched_high is None and high <= low:
                high = min(SOC_CEILING, low + 1)
        return high, low, on


def describe(e: dict) -> str:
    when = (", ".join(d.capitalize() for d in e["days"]) if e["kind"] == "weekly" else e["date"])
    limits = " and ".join(f"{k} {e[k]:g}%" for k in ("high", "low") if e.get(k) is not None)
    return f"{when} {e['start']}-{e['end']}: {limits}" + (f" ({e['label']})" if e.get("label") else "")
