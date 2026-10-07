"""Scheduled limits (src/schedule.py), discharge dropouts and the money (src/stats.py)."""

import asyncio
import datetime

import pytest

from src.schedule import Schedule, describe, validate_entry
from src.stats import Sample, StatsRecorder

TUE_23 = datetime.datetime(2026, 10, 6, 23, 30)  # a Tuesday


def test_entries_are_checked():
    e = validate_entry({"kind": "weekly", "days": ["Tuesday", "thu"], "start": "23:00", "end": "08:00", "high": "50"})
    assert e["days"] == ["tue", "thu"] and e["high"] == 50 and e["low"] is None
    assert describe(e) == "Tue, Thu 23:00-08:00: high 50%"
    for bad in ({"kind": "weekly", "days": [], "start": "23:00", "end": "08:00", "high": 50},
                {"kind": "weekly", "days": ["tue"], "start": "23:00", "end": "23:00", "high": 50},
                {"kind": "once", "date": "soon", "start": "06:00", "end": "10:00", "low": 95},
                {"kind": "once", "date": "2026-10-09", "start": "06:00", "end": "10:00"},
                {"kind": "once", "date": "2026-10-09", "start": "6am", "end": "10:00", "low": 95},
                {"kind": "once", "date": "2026-10-09", "start": "06:00", "end": "10:00", "low": 60, "high": 50}):
        with pytest.raises(ValueError):
            validate_entry(bad)


def test_weekly_entry_runs_past_midnight(tmp_path):
    s = Schedule(str(tmp_path))
    s.add({"kind": "weekly", "days": ["tue", "thu"], "start": "23:00", "end": "08:00", "high": 50})
    assert s.apply(80, 40, TUE_23)[:2] == (50, 40)
    assert s.apply(80, 40, TUE_23 + datetime.timedelta(hours=8))[:2] == (50, 40)  # Wed 07:30: still on
    assert s.apply(80, 40, TUE_23 + datetime.timedelta(hours=9))[:2] == (80, 40)  # Wed 08:30: off
    assert s.apply(80, 40, TUE_23 + datetime.timedelta(days=1))[:2] == (80, 40)  # Wed 23:30: not a Wed entry
    assert s.apply(80, 60, TUE_23)[:2] == (50, 49)  # the low gets out of the way
    assert len(Schedule(str(tmp_path)).entries) == 1  # saved
    up = s.upcoming(TUE_23 + datetime.timedelta(hours=9))
    assert up[0]["starts"] == "2026-10-08T23:00"


def test_one_off_wins_when_it_starts_later_and_is_tidied_away(tmp_path):
    s = Schedule(str(tmp_path))
    s.add({"kind": "weekly", "days": ["wed"], "start": "00:00", "end": "12:00", "low": 30})
    one = s.add({"kind": "once", "date": "2026-10-07", "start": "06:00", "end": "10:00", "low": 95, "label": "trip"})
    wed_7 = datetime.datetime(2026, 10, 7, 7, 0)
    high, low, on = s.apply(80, 40, wed_7)
    assert (high, low) == (96, 95) and on[-1]["id"] == one["id"]  # the high gets out of the way
    assert s.apply(80, 40, datetime.datetime(2026, 10, 7, 11, 0))[:2] == (80, 30)
    s.update(one["id"], {"enabled": False})
    assert s.apply(80, 40, wed_7)[:2] == (80, 30)
    s.tidy(datetime.datetime(2026, 10, 7, 10, 1))
    assert [e["kind"] for e in s.entries] == ["weekly"]
    with pytest.raises(KeyError):
        s.remove("nope")


def _sessions(rec, kwh_in_per_pct, kwh_out_per_pct, t0, prices=(0.07, 0.25)):
    """A charge 30->70% at the cheap price while importing, then a discharge 70->30% saving imports."""
    imp_cheap, imp_dear = prices
    e_in = e_out = 100.0
    now = t0
    for soc in range(30, 71):
        rec.feed(Sample(now, "charge", soc, e_in, e_out, 3, 0, 0, -3, grid_kw=3.5, import_price=imp_cheap,
                        export_price=0.15))
        now += 60
        e_in += kwh_in_per_pct
    rec.feed(Sample(now, None, 0, e_in, e_out, 0, 0, 0, 0, grid_kw=0.2, import_price=imp_dear, export_price=0.15))
    now += 3600
    for soc in range(70, 29, -1):
        rec.feed(Sample(now, "discharge", soc, e_in, e_out, -3, 0, 0, 3, grid_kw=0.0, import_price=imp_dear,
                        export_price=0.15))
        now += 60
        e_out += kwh_out_per_pct
    rec.feed(Sample(now, None, 0, e_in, e_out, 0, 0, 0, 0, grid_kw=0.2, import_price=imp_dear, export_price=0.15))


def test_round_trip_from_kwh_per_percent_and_whether_it_pays(tmp_path):
    rec = StatsRecorder(str(tmp_path))
    t0 = datetime.datetime(2026, 10, 7, 1, 0).timestamp()
    _sessions(rec, 0.6, 0.54, t0)  # 0.6 kWh in per 1%, 0.54 kWh out: 90%
    s = rec.summary(64, now=t0 + 6 * 3600, settings={"inverter_efficiency_pct": 100})
    assert s["per_pct_in"]["kwh"] == 0.6 and s["per_pct_out"]["kwh"] == 0.54 and s["round_trip"] == 0.9
    m = s["money"]
    assert m["in_price"] == 0.07 and m["out_price"] == 0.25  # charged cheap, discharging saved dear imports
    assert m["break_even_price"] == round(0.07 / 0.9, 4)
    assert abs(m["margin_per_kwh"] - (0.25 - 0.07 / 0.9)) < 1e-4 and m["profit"] > 0
    assert abs(s["soc_loss_30_kwh"] - s["last30"]["car_out_kwh"] * (1 / 0.9 - 1)) < 0.01
    with_inverter = rec.summary(64, now=t0 + 6 * 3600, settings={"inverter_efficiency_pct": 95})["money"]
    assert abs(with_inverter["whole_round_trip"] - 0.9 * 0.95 * 0.95) < 1e-4
    assert with_inverter["profit"] < m["profit"]


def test_dropouts_are_counted_per_day(tmp_path):
    rec = StatsRecorder(str(tmp_path))
    t = datetime.datetime(2026, 10, 7, 9, 0).timestamp()
    rec.record_dropout(t)
    rec.record_dropout(t + 600)
    s = rec.summary(now=t + 3600)
    assert s["dropouts_today"] == 2 and s["dropouts_7"] == 2 and s["dropouts_30"] == 2
