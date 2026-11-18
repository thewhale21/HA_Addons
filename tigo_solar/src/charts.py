"""The charts on the page, from the history (src/store.py). Free of I/O but the store.

- day: power through the day (W), by the minute for the whole system (Tigo keeps that),
  by each reading the add-on took for chosen panels (Tigo only keeps the latest);
- week (the 7 days to the day), month (its days), year (its months): energy (Wh).

Each is split into base (what the panels make on their own) and reclaimed (what the Tigo
optimisers won back) where it's known. "panels" is each panel's energy over the same time,
for the roof view.
"""
from __future__ import annotations

import calendar
import datetime
from typing import Optional

VIEWS = ("day", "week", "month", "year")


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


def build(store, view: str, day: str, selected: Optional[list] = None, all_ids: Optional[list] = None) -> dict:
    """The chart for `view` of `day`. `selected`: panel IDs to show (None or all of them:
    the whole system)."""
    if view not in VIEWS:
        raise ValueError(f"View must be one of {', '.join(VIEWS)}")
    _date(day)  # (raises on a bad date)
    start, end = span(view, day)
    all_ids = [int(p) for p in (all_ids or [])]
    chosen = None if selected is None else sorted({int(p) for p in selected})
    whole = chosen is None or (all_ids and set(chosen) >= set(all_ids))
    out = {"view": view, "day": day, "start": start, "end": end, "whole": bool(whole),
           "selected": None if whole else chosen, "note": None}

    # Each panel's energy over the time (the roof view), and for the chart when panels are chosen
    per_panel: dict[int, float] = {}
    by_day: dict[str, float] = {}
    for d, p, wh in store.panel_energy(start, end):
        per_panel[p] = per_panel.get(p, 0.0) + (wh or 0.0)
        if whole or p in chosen:
            by_day[d] = by_day.get(d, 0.0) + (wh or 0.0)
    out["panels"] = {str(p): round(v, 2) for p, v in per_panel.items()}

    if view == "day":
        out["unit"] = "W"
        if whole:
            rows = store.system_power(day)
            out["points"] = [{"t": t[11:16], "total": tot, "base": base, "reclaimed": rec} for t, tot, base, rec in rows]
            energy = store.system_energy(day, day)
            out["total_wh"] = energy[0][1] if energy else (sum(by_day.values()) or None)
            out["reclaimed_wh"] = energy[0][3] if energy else None
        else:
            sums: dict[str, list] = {}
            for t, p, power, rec in store.panel_power(day, chosen):
                s = sums.setdefault(t, [0.0, 0.0, False])
                s[0] += power or 0.0
                s[1] += rec or 0.0
                s[2] = s[2] or rec is not None
            out["points"] = [{"t": t[11:16], "total": round(v[0], 2), "reclaimed": round(v[1], 2) if v[2] else None,
                              "base": round(v[0] - v[1], 2) if v[2] else None} for t, v in sorted(sums.items())]
            out["total_wh"] = round(sum(by_day.values()), 2) if by_day else None
            out["reclaimed_wh"] = None
            if not out["points"]:
                since = store.panel_power_since()
                out["note"] = ("Each panel's power through the day is only known from when the add-on started"
                               + (f" ({since[:10]})" if since else "") + ": Tigo keeps only the latest reading."
                               " The day's energy for these panels is below.")
        return out

    out["unit"] = "Wh"
    days = [(_date(start) + datetime.timedelta(days=n)).isoformat() for n in range((_date(end) - _date(start)).days + 1)]
    if whole:
        system = {d: (tot, base, rec) for d, tot, base, rec in store.system_energy(start, end)}
        values = {d: system.get(d) or ((by_day[d], None, None) if d in by_day else None) for d in days}
    else:
        values = {d: (round(by_day[d], 2), None, None) if d in by_day else None for d in days}
    if view == "year":
        months = {}
        for d, v in values.items():
            if v is None:
                continue
            m = months.setdefault(d[:7], [0.0, 0.0, 0.0, True])
            m[0] += v[0] or 0.0
            if v[1] is None or v[2] is None:
                m[3] = False
            else:
                m[1] += v[1]
                m[2] += v[2]
        out["points"] = [{"t": f"{start[:4]}-{n:02d}", "total": round(months[k][0], 2) if k in months else None,
                          "base": round(months[k][1], 2) if k in months and months[k][3] else None,
                          "reclaimed": round(months[k][2], 2) if k in months and months[k][3] else None}
                         for n in range(1, 13) for k in [f"{start[:4]}-{n:02d}"]]
    else:
        out["points"] = [{"t": d, "total": v[0] if v else None, "base": v[1] if v else None,
                          "reclaimed": v[2] if v else None} for d, v in values.items()]
    totals = [p["total"] for p in out["points"] if p["total"] is not None]
    rec = [p["reclaimed"] for p in out["points"] if p["reclaimed"] is not None]
    out["total_wh"] = round(sum(totals), 2) if totals else None
    out["reclaimed_wh"] = round(sum(rec), 2) if rec else None
    if not whole:
        out["note"] = "Chosen panels: their energy (Tigo splits off reclaimed energy only for the whole system)."
    return out
