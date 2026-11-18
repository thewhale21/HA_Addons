"""What the Tigo cloud sends, made into plain data. Kept free of I/O so it can be
tested on its own (tests/samples.json has real answers from a free-plan system).

The Tigo portal (ei.tigoenergy.com) answers in its own shapes:

- /system/summary/config: the system as a list of "objects", each a dict of one-letter
  keys. B is the type (1 the system, 4 an inverter, 3 a string, 2 a panel, 44 the
  gateway, 10 a line on the layout), A its ID, C its label, K its parent's ID. A panel
  also has L and M, its left and top on Tigo's layout (in the portal's pixels), J its
  watts and T the optimiser's serial.
- /api/v4/system/summary/aggenergy?date=: each panel's energy that day (Wh), and the
  day's totals (dailyStats: total_agg_energy, total_agg_reclaimed).
- /api/v4/data/aggregate (output=echart): series "solar_total", "solar_base" and
  "solar_reclaimed", each [[time, value], ...]: power (W) by the minute with
  agg=minute, energy (Wh) by the hour, day, month or year otherwise.
- /api/v4/system/summary/lastvalue: each panel's last reading of one kind (pin: power,
  reclaimedPower), {"dataset": {panel ID: value}}.
"""
from __future__ import annotations

from typing import Any, Optional

PANEL, STRING, INVERTER, SYSTEM, GATEWAY = 2, 3, 4, 1, 44
SERIES = ("solar_total", "solar_base", "solar_reclaimed")


def _num(value) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def parse_config(config: Any) -> dict:
    """The panels (in label order) and the strings and inverters they're in:
    {"panels": [{"id", "label", "serial", "watts", "string", "string_id", "inverter",
    "left", "top"}], "strings": [{"id", "label", "inverter"}], "inverters": [{"id", "label",
    "watts"}], "gateways": [{"id", "label", "serial"}]}. Panels without an ID or label are left out."""
    objects = ((config or {}).get("system") or {}).get("objects") or []
    by_id = {o.get("A"): o for o in objects if isinstance(o, dict)}

    def label(o):
        return str(o.get("C") or "").strip()

    inverters = [{"id": o["A"], "label": label(o) or f"Inverter {o['A']}", "watts": _num(o.get("J"))}
                 for o in objects if isinstance(o, dict) and o.get("B") == INVERTER and o.get("A") is not None]
    strings = []
    for o in objects:
        if isinstance(o, dict) and o.get("B") == STRING and o.get("A") is not None:
            parent = by_id.get(o.get("K")) or {}
            strings.append({"id": o["A"], "label": label(o) or f"String {o['A']}",
                            "inverter": label(parent) if parent.get("B") == INVERTER else None})
    panels = []
    for o in objects:
        if not isinstance(o, dict) or o.get("B") != PANEL or o.get("A") is None or not label(o):
            continue
        parent = by_id.get(o.get("K")) or {}
        inverter = by_id.get(parent.get("K")) or {}
        panels.append({
            "id": int(o["A"]), "label": label(o), "serial": o.get("T"), "watts": _num(o.get("J")),
            "string": label(parent) if parent.get("B") == STRING else None,
            "string_id": parent.get("A") if parent.get("B") == STRING else None,
            "inverter": label(inverter) if inverter.get("B") == INVERTER else None,
            "left": _num(o.get("L")), "top": _num(o.get("M")),
        })
    panels.sort(key=lambda p: _natural(p["label"]))
    gateways = [{"id": o["A"], "label": label(o), "serial": o.get("T")}
                for o in objects if isinstance(o, dict) and o.get("B") == GATEWAY]
    return {"panels": panels, "strings": strings, "inverters": inverters, "gateways": gateways}


def _natural(text: str) -> tuple:
    """A2 before A10."""
    import re
    return tuple(int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", text))


def parse_aggenergy(data: Any) -> dict:
    """{"date": the day it's for, "panels": {panel ID: Wh}, "last": the latest reading's time
    ("YYYY-MM-DD HH:MM") or None, "total": the day's Wh, "reclaimed": the day's reclaimed Wh}."""
    data = data or {}
    panels = {}
    for key, value in (data.get("dataset") or {}).items():
        v = _num(value)
        if v is not None:
            try:
                panels[int(key)] = v
            except (TypeError, ValueError):
                continue
    times = [str(t)[:16] for t in (data.get("datasetLastData") or {}).values() if t]
    stats = data.get("dailyStats") or {}
    return {
        "date": data.get("dataDate") or data.get("currentDate"),
        "panels": panels,
        "last": max(times) if times else None,
        "total": _num(stats.get("total_agg_energy")),
        "reclaimed": _num(stats.get("total_agg_reclaimed")),
    }


def parse_echart(data: Any) -> dict:
    """{series id: [(time "YYYY-MM-DD HH:MM" or "YYYY-MM-DD", value), ...]} for solar_total,
    solar_base and solar_reclaimed, without the empty ones (None)."""
    out = {name: [] for name in SERIES}
    for serie in (data or {}).get("series") or []:
        name = serie.get("id")
        if name not in out:
            continue
        for point in serie.get("data") or []:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            v = _num(point[1])
            if v is None:
                continue
            t = str(point[0])
            out[name].append((t[:16] if len(t) > 10 else t[:10], v))
    return out


def echart_rows(data: Any) -> list[tuple[str, float, Optional[float], Optional[float]]]:
    """parse_echart as rows (time, total, base, reclaimed), by time; total from base +
    reclaimed where Tigo sent no total."""
    series = parse_echart(data)
    total = dict(series["solar_total"])
    base = dict(series["solar_base"])
    reclaimed = dict(series["solar_reclaimed"])
    rows = []
    for t in sorted(set(total) | set(base) | set(reclaimed)):
        tot = total.get(t)
        if tot is None:
            tot = (base.get(t) or 0.0) + (reclaimed.get(t) or 0.0)
        rows.append((t, tot, base.get(t), reclaimed.get(t)))
    return rows


def parse_lastvalue(data: Any) -> dict:
    """{panel ID: value} from a lastvalue answer."""
    out = {}
    dataset = (data or {}).get("dataset") if isinstance(data, dict) else None
    for key, value in (dataset or {}).items():
        v = _num(value)
        if v is None:
            continue
        try:
            out[int(key)] = v
        except (TypeError, ValueError):
            continue
    return out


def parse_systeminfo(data: Any, date: str) -> dict:
    """{"premium": bool or None, "timezone", "sunrise", "sunset" ("HH:MM"), "last_data"}."""
    data = data or {}
    day = data.get(date) or {}
    premium = data.get("has_premium")
    return {
        "premium": premium if isinstance(premium, bool) else None,
        "timezone": day.get("timezone"),
        "sunrise": day.get("sunrise_time"),
        "sunset": day.get("sunset_time"),
        "last_data": data.get("last_day_with_data"),
    }


def first_month(data: Any) -> Optional[str]:
    """The first month ("YYYY-MM-01") with production, from an agg=month answer."""
    months = sorted(t[:10] for t, v in parse_echart(data)["solar_total"] if v)
    return months[0] if months else None
