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


def next_dispatches(dispatches: list, kind: str, now: datetime.datetime) -> list:
    """The dispatches (in the API's order) of `kind` ("charge" or "discharge") that haven't ended."""
    out = []
    for d in dispatches or []:
        if not isinstance(d, dict):
            continue
        kwh = _kwh(d)
        if (kind == "charge" and kwh < 0) or (kind == "discharge" and kwh > 0):
            end = parse_time(d.get("end"))
            if end is not None and end > now:
                out.append(d)
    return out


def next_dispatch(dispatches: list, kind: str, now: datetime.datetime) -> Optional[dict]:
    """The first dispatch (in the API's order) of `kind` ("charge" or "discharge") that hasn't ended."""
    found = next_dispatches(dispatches, kind, now)
    return found[0] if found else None


LATER = (2, 3)  # sensors for the 2nd and 3rd charge and discharge too (e.g. for Predbat)
LATER_DISCHARGES = LATER  # (the old name)


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
    # The 2nd and 3rd charges and discharges: the same set (1999-01-01 and 00:00:00 when there's none)
    for kind in ("charge", "discharge"):
        later = next_dispatches(dispatches, kind, now)
        for n in LATER:
            d = later[n - 1] if len(later) >= n else None
            out[f"{kind}_{n}_start"] = (d or {}).get("start")
            out[f"{kind}_{n}_end"] = (d or {}).get("end")
            out[f"{kind}_{n}_kwh"] = _kwh(d) if d else None
            times = dispatch_times(d, tz, {"start_time": "00:00:00"})
            out.update({f"{kind}_{n}_{k}": v for k, v in times.items()})
    out.update(now_values(dispatches, now))
    return out


def kind_of(d: Optional[dict]) -> str:
    """"charge", "discharge" or "idle" (no energy)."""
    kwh = _kwh(d or {})
    return "charge" if kwh < 0 else "discharge" if kwh > 0 else "idle"


NOW_STATES = {"charge": "charging", "discharge": "discharging", "idle": "idle"}


def now_values(dispatches: list, now: datetime.datetime) -> dict:
    """What Octopus has the device doing right now: the dispatch running now
    ("now": charging, discharging, idle, or none), with its start, end and
    energy and the minutes left in it."""
    for d in dispatches or []:
        if not isinstance(d, dict):
            continue
        start, end = parse_time(d.get("start")), parse_time(d.get("end"))
        if start is not None and end is not None and start <= now < end:
            return {"now": NOW_STATES[kind_of(d)], "now_start": d.get("start"), "now_end": d.get("end"),
                    "now_kwh": _kwh(d), "now_minutes_left": int((end - now).total_seconds() // 60)}
    return {"now": "none", "now_start": None, "now_end": None, "now_kwh": None, "now_minutes_left": None}


# --- changes to the plan -----------------------------------------------------------

CHANGES_KEEP_DAYS = 7
CHANGES_MAX = 300


def _short(d: dict) -> dict:
    return {"start": d.get("start"), "end": d.get("end"), "energyAddedKwh": _kwh(d), "kind": kind_of(d)}


def plan_changes(previous: Optional[list], dispatches: list, now: datetime.datetime) -> list:
    """What changed between two reads of the plan (dispatches matched by their start):
    [{"change": "added" | "removed" | "changed", "dispatch", "was"}]. Dispatches that
    have ended aren't counted (Octopus drops them then), nor idle ones (no energy:
    one that becomes a charge or discharge is "added"). No previous read: nothing."""
    if previous is None:
        return []

    def live(ds):
        out = {}
        for d in ds or []:
            end = parse_time((d or {}).get("end")) if isinstance(d, dict) else None
            if end is not None and end > now and d.get("start") and kind_of(d) != "idle":
                out[d["start"]] = _short(d)
        return out

    before, after = live(previous), live(dispatches)
    out = []
    for start, d in sorted(after.items()):
        was = before.get(start)
        if was is None:
            out.append({"change": "added", "dispatch": d})
        elif (was["end"], round(was["energyAddedKwh"], 3)) != (d["end"], round(d["energyAddedKwh"], 3)):
            out.append({"change": "changed", "dispatch": d, "was": was})
    for start, was in sorted(before.items()):
        if start not in after:
            out.append({"change": "removed", "dispatch": was})
    return out


def track_changes(kept: dict, dispatches: list, now: datetime.datetime) -> list:
    """Log the plan's changes since the last read in kept["changes"] (newest first,
    each with "at"); kept["plan"] is the plan as last read. Returns the new ones."""
    new = plan_changes(kept.get("plan"), dispatches, now)
    kept["plan"] = [_short(d) for d in dispatches or [] if isinstance(d, dict)]
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    changes = [dict(c, at=stamp) for c in new] + [c for c in kept.get("changes") or []
                                                  if (c.get("dispatch") or {}).get("kind") != "idle"]
    cutoff = now - datetime.timedelta(days=CHANGES_KEEP_DAYS)
    kept["changes"] = [c for c in changes if (parse_time(c.get("at")) or now) >= cutoff][:CHANGES_MAX]
    return new


# --- completed sessions -----------------------------------------------------------
# Octopus changes its planned dispatches a lot, but one that actually happens stays
# in the list until its end time. So a dispatch that's started is followed (by its
# start time: an end that's moved later is the same session), and when its end has
# passed it counts as completed if it was still listed close to that end (it was
# last seen at most `grace_s` before it). One taken off the plan earlier didn't happen.

KEEP_DAYS = 30  # completed sessions are kept this long
KEEP_MAX = 200


def track_completed(kept: dict, dispatches: list, now: datetime.datetime, grace_s: float) -> list:
    """Update kept["tracking"] (dispatches that have started) and kept["completed"]
    (newest first: {"start", "end", "energyAddedKwh", "type", "kind"}). Returns the
    sessions completed this time."""
    tracking = kept.setdefault("tracking", {})
    completed = kept.setdefault("completed", [])
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    for d in dispatches or []:
        if not isinstance(d, dict):
            continue
        start, end = parse_time(d.get("start")), parse_time(d.get("end"))
        kwh = _kwh(d)
        if start is None or end is None or start > now or kwh == 0:
            continue  # (idle ones, with no energy, aren't sessions)
        tracking[d["start"]] = {"start": d["start"], "end": d["end"], "energyAddedKwh": kwh,
                                "type": d.get("type"), "kind": "charge" if kwh < 0 else "discharge" if kwh > 0 else None,
                                "last_seen": stamp}
    done = []
    for key, t in list(tracking.items()):
        end, seen = parse_time(t.get("end")), parse_time(t.get("last_seen"))
        if end is None or seen is None:
            tracking.pop(key)
            continue
        if end > now:
            continue
        tracking.pop(key)
        if (end - seen).total_seconds() <= grace_s and not any(c["start"] == t["start"] for c in completed):
            entry = {k: t[k] for k in ("start", "end", "energyAddedKwh", "type", "kind")}
            done.append(entry)
    if done:
        completed[:0] = sorted(done, key=lambda c: c["start"], reverse=True)
    cutoff = now - datetime.timedelta(days=KEEP_DAYS)
    kept["completed"] = merge_overlapping([c for c in completed if (parse_time(c["end"]) or now) >= cutoff])[:KEEP_MAX]
    return done


SOC_FIELDS = ("soc_entity", "soc_start", "soc_end", "soc_result")


def _half_hour(t: datetime.datetime) -> datetime.datetime:
    """The start of the half hour `t` is in."""
    return t.replace(minute=t.minute - t.minute % 30, second=0, microsecond=0)


def merge_overlapping(completed: list) -> list:
    """Completed sessions of the same kind that overlap, or touch within one half hour,
    made into one (newest first). Octopus sometimes re-plans a session part-way through,
    as a new dispatch for the rest of it (e.g. 04:30-05:00, then 04:59-05:00), or cuts it
    short and adds one for the rest (12:30-12:47, then 12:47-13:00): both are completed,
    but it's one session. Back-to-back half hours (05:00-05:30 after 04:30-05:00) stay
    apart, as Octopus bills and credits by the half hour.
    The merged one runs from the first start to the last end. Its energy is the later
    dispatch's plus the earlier one's for the time the later one doesn't cover (pro rata;
    touching ones simply add up). Its SoC result is dropped, so it's checked again over
    the whole session."""
    ordered = sorted((c for c in completed if parse_time(c.get("start")) and parse_time(c.get("end"))),
                     key=lambda c: c["start"])
    out = []
    for c in ordered:
        last = out[-1] if out else None
        a0, a1 = (parse_time(last["start"]), parse_time(last["end"])) if last is not None else (None, None)
        b0, b1 = parse_time(c["start"]), parse_time(c["end"])
        overlaps = last is not None and b0 < a1
        # (touching: only within one half hour, i.e. a half hour split in two)
        touches = last is not None and b0 == a1 and _half_hour(a0) == _half_hour(max(a1, b1) - datetime.timedelta(seconds=1))
        if last is not None and last.get("kind") == c.get("kind") and (overlaps or touches):
            length = (a1 - a0).total_seconds()
            overlap = max(0, (min(a1, b1) - b0).total_seconds())
            share = 1 - overlap / length if length > 0 else 0
            merged = {k: v for k, v in last.items() if k not in SOC_FIELDS}
            merged["end"] = c["end"] if b1 > a1 else last["end"]
            merged["energyAddedKwh"] = round(_kwh(last) * share + _kwh(c), 3)
            out[-1] = merged
        else:
            out.append(c)
    return list(reversed(out))
