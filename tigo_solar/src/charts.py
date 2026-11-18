"""The charts on the page, from the history (src/store.py). Free of I/O but the store.

- day: power through the day (W);
- week (the 7 days to the day), month (its days), year (its months): energy (Wh).

Each chart has the total for the panels shown ("points": total, base, reclaimed) and each
panel's own share of it ("panel_series": panel ID -> a value per point, in the same order),
so the page can stack the panels and show what each made at any point.

Where each panel's numbers come from:
- energy by the day: Tigo has each panel's energy for every day (exact);
- power through a day (every minute, as the system's: its power shared out by each
  panel's share at its readings, going smoothly between them): Tigo keeps each panel's
  readings every 15 minutes; the add-on reads
  them as they come, and the past ones a slot at a time (src/collector.py; exact). Where
  it has none yet (still reading the history, or Tigo didn't send them), each panel's
  power is estimated: the system's power by the minute (which Tigo keeps) times the
  panel's share of that day's energy ("estimated": true).
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
        # (the scale for all the panels, so fewer show as less on the same scale)
        tops = [r[1] for r in store.system_power(day) if r[1] is not None]
        tops += [p["total"] for p in out["points"] if p["total"] is not None]
        out["scale_max"] = max(tops) if tops else None
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
    # (the scale for all the panels: the system's total, or all of them added up, at the most)
    every = [0.0] * len(keys)
    for d, panels in energy.items():
        i = idx.get(key_of(d))
        if i is not None:
            every[i] += sum(panels.values())
    sys_sum = [0.0] * len(keys)
    for d, tot, _base, _rec in store.system_energy(start, end):
        i = idx.get(key_of(d))
        if i is not None and tot is not None:
            sys_sum[i] += tot
    every = [max(a, b) for a, b in zip(every, sys_sum)]
    out["scale_max"] = max(every + [p["total"] or 0.0 for p in points]) or None
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


def _shares(recorded: dict, need: set) -> list:
    """Each reading of the panels as shares: [(minute, {panel: share of the power},
    {panel: share of the reclaimed power})], by time. A reading missing any panel in `need`
    (those that made something that day) is left out: its shares would be wrong."""
    out = []
    for t in sorted(recorded):
        vals = recorded[t]
        if not need <= {p for p, v in vals.items() if v[0] is not None}:
            continue
        tot = sum(v[0] or 0.0 for v in vals.values())
        rec = sum(v[1] or 0.0 for v in vals.values())
        if tot <= 0:
            continue
        out.append((_mins(t), {p: (v[0] or 0.0) / tot for p, v in vals.items()},
                    {p: (v[1] or 0.0) / rec for p, v in vals.items()} if rec > 0 else {}))
    return out


def _share_at(m: int, at: list, readings: list):
    """Each panel's shares at minute m: between the readings either side (if they're near
    enough), else the nearest one if near, else None."""
    import bisect
    i = bisect.bisect_left(at, m)
    before = readings[i - 1] if i > 0 else None
    after = readings[i] if i < len(readings) else None
    if after and after[0] == m:
        return after[1], after[2]
    if before and after and after[0] - before[0] <= 2 * RECORDED_GAP_MIN:
        f = (m - before[0]) / (after[0] - before[0])
        mix = lambda a, b: {p: (a.get(p) or 0.0) * (1 - f) + (b.get(p) or 0.0) * f for p in set(a) | set(b)}  # noqa: E731
        return mix(before[1], after[1]), mix(before[2], after[2]) if before[2] and after[2] else (before[2] or after[2])
    near = [r for r in (before, after) if r and abs(r[0] - m) <= RECORDED_GAP_MIN]
    if not near:
        return None
    r = min(near, key=lambda r: abs(r[0] - m))
    return r[1], r[2]


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
        # Every minute, as the whole system: the system's power shared out between the
        # panels. Each panel's share comes from its readings (every 15 minutes), going
        # smoothly from one reading to the next; where there are none near (not read yet,
        # or Tigo didn't send them), from its share of the day's energy (estimated).
        day_share = {p: (energy.get(p) or 0.0) / day_total for p in panel_ids}
        readings = _shares(recorded, {p for p, wh in energy.items() if wh})  # [(minute, {panel: power share}, {panel: reclaimed share})]
        at = [m for m, _, _ in readings]
        rows = []  # (ts, {panel: (power, reclaimed)}, estimated)
        for ts, tot, _base, rec in system:
            shares = _share_at(_mins(ts), at, readings)
            if shares is None:
                ps, rs, guess = day_share, day_share, True
            else:
                (ps, rs), guess = shares, False
                rs = rs or ps  # (no panel reclaimed anything then: shared as the power)
            rows.append((ts, {p: (None if tot is None else tot * (ps.get(p) or 0.0),
                                  None if rec is None else rec * (rs.get(p) or 0.0)) for p in panel_ids}, guess))
        series, reclaimed, points = _series(rows, panel_ids)
        guessed = sum(1 for r in rows if r[2])
        out["estimated"] = guessed > 0
        if guessed == len(rows):
            out["note"] = ("Each panel's power is estimated for this day: the add-on hasn't read each panel's "
                           "readings for it from Tigo yet (see History), so it's the system's power times the "
                           "panel's share of the day's energy.")
        elif guessed:
            out["note"] = ("Each panel's power is partly estimated for this day: where the add-on hasn't "
                           "read each panel from Tigo (yet), it's the system's power times the panel's share "
                           "of the day's energy.")
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


# --- Through the year: each day by the time of day ------------------------------------

YEAR_STEP_MIN = 30  # the time of day in steps of this many minutes


def year_grid(store, year: int, selected: Optional[list] = None, all_ids: Optional[list] = None,
              step: int = YEAR_STEP_MIN) -> dict:
    """Each day of `year` with any power, by the time of day: the average power (W) made and
    reclaimed in each `step` minutes. `selected`: panel IDs (None or all: the whole system,
    from Tigo's own minutes; else these panels, as on a day's chart)."""
    year = int(year)
    if not 2000 <= year <= 2100 or 1440 % step:
        raise ValueError("Give a year, and a step that divides a day")
    all_ids = [int(p) for p in (all_ids or [])]
    chosen = None if selected is None else sorted({int(p) for p in selected})
    whole = chosen is None or bool(all_ids and set(chosen) >= set(all_ids))
    days, made, reclaimed = [], [], []
    start, end = datetime.date(year, 1, 1), datetime.date(year, 12, 31)
    have = {r[0] for r in store.system_energy(start.isoformat(), end.isoformat()) if r[1]}
    d = start
    while d <= end:
        day = d.isoformat()
        d += datetime.timedelta(days=1)
        if whole:
            rows = [(t[11:16], tot, rec) for t, tot, _b, rec in store.system_power(day)]
        elif day in have or store.panel_power(day):
            c = build(store, "day", day, chosen, all_ids)
            rows = [(p["t"], p["total"], p["reclaimed"]) for p in c["points"]]
        else:
            rows = []
        if not any(r[1] for r in rows):
            continue
        n = 1440 // step
        sums, recs, counts = [0.0] * n, [0.0] * n, [0] * n
        rec_seen = [False] * n
        for t, tot, rec in rows:
            i = (int(t[:2]) * 60 + int(t[3:5])) // step
            sums[i] += tot or 0.0
            counts[i] += 1
            if rec is not None:
                recs[i] += rec
                rec_seen[i] = True
        days.append(day)
        made.append([round(sums[i] / counts[i], 1) if counts[i] else None for i in range(n)])
        reclaimed.append([round(recs[i] / counts[i], 1) if counts[i] and rec_seen[i] else None for i in range(n)])
    # (only the times of day anything was made, all year)
    used = [i for i in range(1440 // step) if any(row[i] for row in made)]
    lo, hi = (min(used), max(used)) if used else (0, -1)
    cut = lambda rows: [r[lo:hi + 1] for r in rows]  # noqa: E731
    flat = [v for r in made for v in r if v is not None]
    rflat = [v for r in reclaimed for v in r if v is not None]
    return {"year": year, "step": step, "whole": whole, "selected": None if whole else chosen,
            "days": days, "slots": [i * step for i in range(lo, hi + 1)],
            "made": cut(made), "reclaimed": cut(reclaimed),
            "max_made": max(flat) if flat else None, "max_reclaimed": max(rflat) if rflat else None}
