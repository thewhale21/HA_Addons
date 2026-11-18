"""The charts on the page, from the history (src/store.py). Free of I/O but the store.

- day: power through the day (W);
- week (the 7 days to the day), month (its days), year (its months): energy (Wh).

Each chart has the total for the panels shown ("points": total, base, reclaimed) and each
panel's own share of it ("panel_series": panel ID -> a value per point, in the same order),
so the page can stack the panels and show what each made at any point.

Where each panel's numbers come from:
- energy by the day: Tigo has each panel's energy for every day (exact);
- power through a day: Tigo keeps only each panel's latest reading, so the add-on records
  them as it reads (exact, from when it started). For a day before that, each panel's
  power is estimated: the system's power by the minute (which Tigo keeps) times the
  panel's share of that day's energy ("estimated": true); so is any part of a day
  without the add-on's readings (before it started, or while it was stopped).
- reclaimed: Tigo splits it off for the whole system by the minute and the day; for a
  panel, from the add-on's own readings (or, estimated, the system's times its share).
"""
from __future__ import annotations

import calendar
import datetime
from typing import Optional

VIEWS = ("day", "week", "month", "year")
ESTIMATE_STEP_MIN = 1  # an estimated day: a point every this many minutes (each of Tigo's, so
# some panels chosen look like the whole system, just smaller)


def _date(text: str) -> datetime.date:
    return datetime.date.fromisoformat(str(text)[:10])


def span(view: str, day: str) -> tuple[str, str]:
    """The first and last day a view of `day` covers."""
    d = _date(day)
    if view == "day":
        return d.isoformat(), d.isoformat()
    if view == "week":
        return (d - datetime.timedelta(days=6)).isoformat(), d.isoformat()
    if view == "month":
        return d.replace(day=1).isoformat(), d.replace(day=calendar.monthrange(d.year, d.month)[1]).isoformat()
    if view == "year":
        return d.replace(month=1, day=1).isoformat(), d.replace(month=12, day=31).isoformat()
    raise ValueError(f"View must be one of {', '.join(VIEWS)}")


def _r(v: Optional[float], d: int = 2) -> Optional[float]:
    return None if v is None else round(v, d)


def build(store, view: str, day: str, selected: Optional[list] = None, all_ids: Optional[list] = None) -> dict:
    """The chart for `view` of `day`. `selected`: panel IDs to show (None or all of them:
    the whole system)."""
    if view not in VIEWS:
        raise ValueError(f"View must be one of {', '.join(VIEWS)}")
    _date(day)  # (raises on a bad date)
    start, end = span(view, day)
    all_ids = [int(p) for p in (all_ids or [])]
    chosen = None if selected is None else sorted({int(p) for p in selected})
    whole = chosen is None or bool(all_ids and set(chosen) >= set(all_ids))
    out = {"view": view, "day": day, "start": start, "end": end, "whole": whole,
           "selected": None if whole else chosen, "note": None, "estimated": False}

    # Each panel's energy by the day (exact), for the roof and the bars
    energy: dict[str, dict[int, float]] = {}
    per_panel: dict[int, float] = {}
    for d, p, wh in store.panel_energy(start, end):
        energy.setdefault(d, {})[p] = wh or 0.0
        per_panel[p] = per_panel.get(p, 0.0) + (wh or 0.0)
    out["panels"] = {str(p): round(v, 2) for p, v in per_panel.items()}
    keep = (lambda p: True) if whole else (lambda p: p in set(chosen))

    if view == "day":
        out["unit"] = "W"
        _day(store, day, out, energy.get(day, {}), whole, chosen, keep)
        return out

    out["unit"] = "Wh"
    days = [(_date(start) + datetime.timedelta(days=n)).isoformat() for n in range((_date(end) - _date(start)).days + 1)]
    system = {d: (tot, base, rec) for d, tot, base, rec in store.system_energy(start, end)} if whole else {}
    if view == "year":
        keys = [f"{start[:4]}-{n:02d}" for n in range(1, 13)]
        key_of = lambda d: d[:7]  # noqa: E731
    else:
        keys = days
        key_of = lambda d: d  # noqa: E731
    panel_ids = sorted({p for e in energy.values() for p in e if keep(p)}) if whole else list(chosen)
    series = {p: [0.0] * len(keys) for p in panel_ids}
    seen = [False] * len(keys)
    idx = {k: i for i, k in enumerate(keys)}
    for d, panels in energy.items():
        i = idx.get(key_of(d))
        if i is None:
            continue
        for p, wh in panels.items():
            if p in series:
                series[p][i] += wh
                seen[i] = True
    sys_rows = [[0.0, 0.0, 0.0, True, False] for _ in keys]  # total, base, reclaimed, split known, any
    for d, (tot, base, rec) in system.items():
        i = idx.get(key_of(d))
        if i is None:
            continue
        r = sys_rows[i]
        r[0] += tot or 0.0
        r[4] = True
        if base is None or rec is None:
            r[3] = False
        else:
            r[1] += base
            r[2] += rec
    points = []
    for i, k in enumerate(keys):
        panels_total = sum(series[p][i] for p in series) if seen[i] else None
        if whole and sys_rows[i][4]:
            r = sys_rows[i]
            points.append({"t": k, "total": _r(r[0]), "base": _r(r[1]) if r[3] else None,
                           "reclaimed": _r(r[2]) if r[3] else None})
        else:
            points.append({"t": k, "total": _r(panels_total), "base": None, "reclaimed": None})
    out["points"] = points
    out["panel_series"] = {str(p): [_r(v) if seen[i] else None for i, v in enumerate(vals)] for p, vals in series.items()}
    totals = [p["total"] for p in points if p["total"] is not None]
    rec = [p["reclaimed"] for p in points if p["reclaimed"] is not None]
    out["total_wh"] = round(sum(totals), 2) if totals else None
    out["reclaimed_wh"] = round(sum(rec), 2) if rec else None
    if not whole:
        out["note"] = ("Tigo splits off reclaimed energy by the day only for the whole system, so it's shown "
                       "with all panels chosen.")
    return out


RECORDED_GAP_MIN = 20  # an estimate fills in where no reading of each panel is this near


def _mins(ts: str) -> int:
    return int(ts[11:13]) * 60 + int(ts[14:16])


def _near(m: int, recorded: list) -> bool:
    """Is a reading of each panel within RECORDED_GAP_MIN of minute m? (`recorded` sorted)"""
    import bisect
    i = bisect.bisect_left(recorded, m)
    return any(0 <= k < len(recorded) and abs(recorded[k] - m) <= RECORDED_GAP_MIN for k in (i - 1, i))


def _series(rows: list, panel_ids: list):
    """Each panel's power and reclaimed power, and the totals, from (ts, {panel: (power,
    reclaimed)}, estimated) rows in time order."""
    series = {p: [_r((r[1].get(p) or (None, None))[0], 1) for r in rows] for p in panel_ids}
    reclaimed = {p: [_r((r[1].get(p) or (None, None))[1], 1) for r in rows] for p in panel_ids}
    points = []
    for i, r in enumerate(rows):
        tot = sum(series[p][i] or 0.0 for p in panel_ids)
        rec_vals = [reclaimed[p][i] for p in panel_ids if reclaimed[p][i] is not None]
        rec = sum(rec_vals) if rec_vals else None
        points.append({"t": r[0][11:16], "total": _r(tot, 1), "reclaimed": _r(rec, 1),
                       "base": _r(tot - rec, 1) if rec is not None else None})
    return series, reclaimed, points


def _day(store, day: str, out: dict, energy: dict, whole: bool, chosen: Optional[list], keep) -> None:
    """A day's power: each panel's recorded readings, else estimated from the system's."""
    recorded: dict[str, dict[int, tuple]] = {}
    for t, p, power, rec in store.panel_power(day):
        recorded.setdefault(t, {})[p] = (power, rec)
    system = store.system_power(day)
    panel_ids = sorted(energy) if whole else list(chosen)
    if whole and not panel_ids:
        panel_ids = sorted({p for v in recorded.values() for p in v})
    day_total = sum(energy.values())

    if system and day_total > 0:
        # Each panel's own readings where the add-on has them (exact); before them, after
        # them and in any gap (e.g. the add-on was stopped), estimated: the system's power
        # by the minute, shared out by each panel's share of the day's energy
        share = {p: (energy.get(p) or 0.0) / day_total for p in panel_ids}
        rec_mins = sorted(_mins(t) for t in recorded)
        steps = [r for r in system if int(r[0][14:16]) % ESTIMATE_STEP_MIN == 0] or system
        rows = []  # (ts, {panel: (power, reclaimed)}, estimated)
        for r in steps:
            if not _near(_mins(r[0]), rec_mins):
                rows.append((r[0], {p: (None if r[1] is None else r[1] * share[p],
                                        None if r[3] is None else r[3] * share[p]) for p in panel_ids}, True))
        if len(recorded) >= 2:
            rows += [(t, recorded[t], False) for t in recorded]
        rows.sort(key=lambda r: r[0])
        series, reclaimed, points = _series(rows, panel_ids)
        guessed = sum(1 for r in rows if r[2])
        out["estimated"] = guessed > 0
        if guessed == len(rows):
            out["note"] = ("Each panel's power is estimated for this day: Tigo keeps only each panel's latest "
                           "reading, so it's the system's power times the panel's share of the day's energy. "
                           "The add-on records each panel's own readings from when it started.")
        elif guessed:
            out["note"] = ("Each panel's power is partly estimated for this day: where the add-on wasn't "
                           "recording each panel (before it started, or while it was stopped), it's the "
                           "system's power times the panel's share of the day's energy.")
        if whole:
            out["system_points"] = [{"t": t[11:16], "total": tot, "base": base, "reclaimed": rec}
                                    for t, tot, base, rec in system]
    elif len(recorded) >= 2:
        # The add-on's own readings of each panel (exact)
        series, reclaimed, points = _series([(t, recorded[t], False) for t in sorted(recorded)], panel_ids)
        if whole and system:
            out["system_points"] = [{"t": t[11:16], "total": tot, "base": base, "reclaimed": rec}
                                    for t, tot, base, rec in system]
    elif whole and system:
        # (no panel's share known: the whole system on its own)
        series, reclaimed = {}, {}
        points = [{"t": t[11:16], "total": tot, "base": base, "reclaimed": rec} for t, tot, base, rec in system]
    else:
        series, reclaimed, points = {}, {}, []
    out["points"] = points
    out["panel_series"] = {str(p): v for p, v in series.items()}
    out["panel_reclaimed"] = {str(p): v for p, v in reclaimed.items()}
    energy_shown = sum(v for p, v in energy.items() if keep(p))
    if whole:
        totals = store.system_energy(day, day)
        out["total_wh"] = totals[0][1] if totals else (_r(energy_shown) if energy else None)
        out["reclaimed_wh"] = totals[0][3] if totals else None
    else:
        out["total_wh"] = _r(energy_shown) if energy else None
        rec_share = None
        totals = store.system_energy(day, day)
        if totals and totals[0][3] is not None and day_total > 0:
            rec_share = totals[0][3] * energy_shown / day_total
        out["reclaimed_wh"] = _r(rec_share)
        if rec_share is not None:
            out["reclaimed_estimated"] = True
