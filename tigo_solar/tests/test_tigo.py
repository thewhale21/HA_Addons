"""Reading Tigo, the history and the charts, with real answers from a free-plan system
(tests/samples.json: 12 panels in two strings, captured 18 Nov 2026 at 08:15; serials
and the system ID changed)."""

import asyncio
import datetime
import json
from pathlib import Path

import pytest

from src import charts, tigo_data
from src.collector import Collector
from src.layout import Layout
from src.shared_state import SharedState
from src.store import Store

SAMPLES = json.loads((Path(__file__).parent / "samples.json").read_text())


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --- what Tigo sends ---------------------------------------------------------------


def test_the_system_and_its_layout():
    system = tigo_data.parse_config(SAMPLES["config"])
    panels = system["panels"]
    assert [p["label"] for p in panels] == ["A1", "A2", "A3", "A4", "A5", "A6", "B1", "B2", "B3", "B4", "B5", "B6"]
    a1 = panels[0]
    assert a1["id"] == 90375862 and a1["string"] == "String A" and a1["inverter"] == "Inverter 1"
    assert (a1["left"], a1["top"], a1["watts"]) == (50.0, 110.0, 480.0)
    assert panels[6]["string"] == "String B" and panels[6]["top"] == 200.0
    assert [s["label"] for s in system["strings"]] == ["String A", "String B"]
    assert system["inverters"][0]["label"] == "Inverter 1"
    assert tigo_data.parse_config(None) == {"panels": [], "strings": [], "inverters": [], "gateways": []}


def test_each_panels_energy_for_a_day():
    day = tigo_data.parse_aggenergy(SAMPLES["aggenergy_yday"])
    assert day["date"] == "2026-11-17" and len(day["panels"]) == 12 and day["panels"][90375862] == 363
    assert day["total"] == pytest.approx(3568.1166) and day["reclaimed"] == pytest.approx(303.0102)
    assert day["last"] == "2026-11-17 17:24"
    assert tigo_data.parse_aggenergy(SAMPLES["aggenergy_today"])["last"] == "2026-11-18 08:13"


def test_power_by_the_minute_and_energy_by_the_day():
    rows = tigo_data.echart_rows(SAMPLES["agg_line_today"])
    assert rows[0] == ("2026-11-18 07:30", 8.0, 8.0, None)
    assert rows[-1] == ("2026-11-18 08:13", 156.0, 149.21, 6.79)
    days = tigo_data.echart_rows(SAMPLES["agg_day_month"])
    assert days[0] == ("2026-10-18 00:00", 8830.67, 8351.89, 478.78) and len(days) == 32
    assert tigo_data.first_month(SAMPLES["agg_month_year"]) == "2026-04-01"


def test_plan_and_lastvalue():
    info = tigo_data.parse_systeminfo(SAMPLES["systeminfo"], "2026-11-18")
    assert info == {"premium": False, "timezone": "Europe/London", "sunrise": "06:25", "sunset": "15:12",
                    "last_data": "2026-11-18 08:13:00"}
    assert tigo_data.parse_lastvalue({"dataset": {"1": 12.5, "2": None, "x": 3}}) == {1: 12.5}
    assert tigo_data.parse_lastvalue([]) == {}


# --- reading it ----------------------------------------------------------------------


class FakeTigo:
    """Answers as Tigo did, for any day (yesterday's answers, moved to the day asked)."""

    def __init__(self):
        self.calls = []

    async def config(self):
        self.calls.append("config")
        return SAMPLES["config"]

    async def systeminfo(self, day):
        self.calls.append(("systeminfo", day))
        return {day: SAMPLES["systeminfo"]["2026-11-18"], "has_premium": False}

    async def aggenergy(self, day):
        self.calls.append(("aggenergy", day))
        src = SAMPLES["aggenergy_today"] if day == "2026-11-18" else SAMPLES["aggenergy_yday"]
        data = json.loads(json.dumps(src))
        data["dataDate"] = day
        data["datasetLastData"] = {k: day + v[10:] for k, v in data["datasetLastData"].items()}
        return data

    async def aggregate(self, agg, start, end, line=False):
        self.calls.append(("aggregate", agg, start, end))
        if agg == "minute":
            data = json.loads(json.dumps(SAMPLES["agg_line_today"]))
            for s in data["series"]:
                s["data"] = [[start + p[0][10:], p[1]] for p in s["data"]]
            return data
        if agg == "month":
            return SAMPLES["agg_month_year"]
        if agg == "day":
            data = json.loads(json.dumps(SAMPLES["agg_day_month"]))
            for s in data["series"]:
                s["data"] = [p for p in s["data"] if start <= p[0][:10] <= end]
            return data
        return SAMPLES["agg_" + agg] if ("agg_" + agg) in SAMPLES else {"series": []}

    async def lastvalue(self, day, kind, hhmm):
        self.calls.append(("lastvalue", kind, hhmm))
        return {"dataset": {"90375862": 41.0 if kind == "pin" else 2.5, "90375863": 39.0 if kind == "pin" else 1.0}}

    async def lifetime(self):
        return SAMPLES["lifetime"]


def _collector(now="2026-11-18T08:20:00+00:00", tmp_path=None):
    state = SharedState()
    store = Store(None)
    clock = {"t": 0.0}

    async def no_sleep(_s):
        return None

    c = Collector(FakeTigo(), store, state, Layout(str(tmp_path) if tmp_path else None),
                  now=lambda: datetime.datetime.fromisoformat(now), sleep=no_sleep, clock=lambda: clock["t"])
    return c, state, store


def test_a_poll_reads_today(tmp_path):
    c, state, store = _collector(tmp_path=tmp_path)
    _run(c.poll())
    assert state.timezone == "Europe/London" and state.premium is False
    assert len(state.panels) == 12 and state.panels[0]["energy_today"] == 3.4
    assert state.power == 156.0 and state.reclaimed == 6.79 and state.as_of == "2026-11-18 08:13"
    assert state.today_wh == pytest.approx(52.27) or state.today_wh is not None
    assert state.lifetime_wh == 3845488
    # each panel's power at the latest reading, kept (Tigo only has the latest)
    assert state.panels[0]["power"] == 41.0 and state.panels[0]["reclaimed"] == 2.5
    assert store.panel_power("2026-11-18") == [("2026-11-18 08:13", 90375862, 41.0, 2.5),
                                              ("2026-11-18 08:13", 90375863, 39.0, 1.0)]
    assert len(store.system_power("2026-11-18")) == len(tigo_data.echart_rows(SAMPLES["agg_line_today"]))
    # the next poll with no new reading doesn't ask for each panel again
    c.client.calls.clear()
    _run(c.poll())
    assert not any(isinstance(x, tuple) and x[0] == "lastvalue" for x in c.client.calls)


def test_the_history_is_read_a_day_at_a_time_and_once(tmp_path):
    c, state, store = _collector(tmp_path=tmp_path)
    _run(c.poll())
    steps = 0
    while _run(c.backfill_step()):
        steps += 1
        assert steps < 500
    start = state.history["from"]
    # (the first month with production: April; the sample has no days for it, so its 1st)
    assert start == "2026-04-01"
    days = (datetime.date(2026, 11, 17) - datetime.date(2026, 4, 1)).days + 1
    assert state.history["done"] == days == state.history["days"] and not state.history["running"]
    assert store.counts()["panel_energy"] >= 12 * days
    assert store.is_done("2026-04-01", "day") and not store.is_done("2026-11-18", "day")
    assert store.is_done("2026-10", "month") and not store.is_done("2026-11", "month")
    # done: nothing asked again
    c.client.calls.clear()
    assert not _run(c.backfill_step())
    assert not any(isinstance(x, tuple) and x[0] == "aggenergy" for x in c.client.calls)


def _past_day_tigo(c, store, fair=True):
    """Tigo with each panel's readings for any time: 12 panels sharing the system's power
    then (fair), or always the latest reading whatever the time (not)."""
    system = {t: tot for t, tot, _, _ in store.system_power("2026-11-18")}

    async def lastvalue(day, kind, hhmm):
        c.client.calls.append(("lastvalue", kind, day, hhmm))
        tot = system.get(f"{day} {hhmm}") if fair else 156.0
        if tot is None:
            return {"dataset": {}}
        each = tot / 12 if kind == "pin" else tot / 120
        return {"dataset": {str(p): each for p in IDS}}
    c.client.lastvalue = lastvalue


def test_each_panel_through_past_days_is_read_every_15_minutes(tmp_path):
    c, state, store = _collector(now="2026-11-18T09:00:00+00:00", tmp_path=tmp_path)
    _run(c.poll())
    c._start = "2026-11-18"
    # (the add-on read each panel at 08:13 as it happened; the system made power from 07:30)
    _past_day_tigo(c, store)
    c.client.calls.clear()
    while _run(c.panel_history_step()):
        assert len(c.client.calls) < 50
    asked = sorted({x[3] for x in c.client.calls})
    assert asked == ["07:30", "07:45", "08:00"]  # (08:15: the 08:13 reading covers it)
    rows = store.panel_power("2026-11-18")
    assert {r[0] for r in rows} == {"2026-11-18 07:30", "2026-11-18 07:45", "2026-11-18 08:00", "2026-11-18 08:13"}
    a1 = [r for r in rows if r[0] == "2026-11-18 08:00" and r[1] == IDS[0]][0]
    assert a1[2] == pytest.approx(store.system_power("2026-11-18")[30][1] / 12) and a1[3] is not None
    assert state.history["panels_running"] is False and not state.history["panels_off"]
    # asked once: nothing more
    c.client.calls.clear()
    assert not _run(c.panel_history_step()) and not c.client.calls


def test_each_panel_through_past_days_stops_if_tigo_sends_only_the_latest(tmp_path):
    c, state, store = _collector(now="2026-11-18T09:00:00+00:00", tmp_path=tmp_path)
    _run(c.poll())
    c._start = "2026-11-18"
    _past_day_tigo(c, store, fair=False)
    store.put_panel_power("2026-11-18 08:13", {}, {})  # (nothing read as it happened)
    steps = 0
    while _run(c.panel_history_step()):
        steps += 1
        assert steps < 10
    assert state.history["panels_off"] and c._panel_off
    assert {r[0] for r in store.panel_power("2026-11-18")} == {"2026-11-18 08:13"}


def test_a_new_day_finishes_yesterday(tmp_path):
    c, state, store = _collector(now="2026-11-17T22:00:00+00:00", tmp_path=tmp_path)
    _run(c.poll())
    assert not store.is_done("2026-11-17", "day")
    c._now = lambda: datetime.datetime.fromisoformat("2026-11-18T00:10:00+00:00")
    _run(c.poll())
    assert store.is_done("2026-11-17", "day") and c._day == "2026-11-18"


# --- the charts ----------------------------------------------------------------------


def _filled_store():
    store = Store(None)
    store.put_system_power(tigo_data.echart_rows(SAMPLES["agg_line_today"]))
    store.put_system_energy((t[:10], a, b, r) for t, a, b, r in tigo_data.echart_rows(SAMPLES["agg_day_month"]))
    store.put_panel_energy("2026-11-17", tigo_data.parse_aggenergy(SAMPLES["aggenergy_yday"])["panels"])
    return store


IDS = [p["id"] for p in tigo_data.parse_config(SAMPLES["config"])["panels"]]


def test_charts_for_the_whole_system():
    store = _filled_store()
    day = charts.build(store, "day", "2026-11-18", None, IDS)
    # (no panel's energy that day yet: the system's own power, split base / reclaimed)
    assert day["whole"] and day["unit"] == "W" and day["panel_series"] == {}
    assert day["points"][-1] == {"t": "08:13", "total": 156.0, "base": 149.21, "reclaimed": 6.79}
    week = charts.build(store, "week", "2026-11-17", None, IDS)
    assert [p["t"] for p in week["points"]] == [f"2026-11-{d}" for d in range(11, 18)]
    assert week["points"][-1] == {"t": "2026-11-17", "total": 3568.12, "base": 3265.11, "reclaimed": 303.01}
    assert week["panels"]["90375862"] == 363.0
    # each panel's part of each bar, stacked on the page
    assert len(week["panel_series"]) == 12 and week["panel_series"]["90375862"][-1] == 363
    assert week["panel_series"]["90375862"][0] is None  # (no panel energy that day)
    month = charts.build(store, "month", "2026-10-05", None, IDS)
    assert month["start"] == "2026-10-01" and len(month["points"]) == 31 and month["points"][0]["total"] is None
    year = charts.build(store, "year", "2026-11-17", None, IDS)
    assert len(year["points"]) == 12 and year["points"][9]["total"] == pytest.approx(
        sum(r[1] for r in tigo_data.echart_rows(SAMPLES["agg_day_month"]) if r[0].startswith("2026-10")), abs=0.01)
    assert year["panel_series"]["90375862"][10] == 363
    with pytest.raises(ValueError):
        charts.build(store, "decade", "2026-11-17")
    with pytest.raises(ValueError):
        charts.build(store, "day", "17/11/2026")


def test_a_past_day_estimates_each_panel_from_the_system():
    """A day before the add-on read each panel: the system's power by the minute, shared out by
    each panel's share of the day's energy, every minute (as the whole system); said so."""
    store = _filled_store()
    store.put_panel_energy("2026-11-18", tigo_data.parse_aggenergy(SAMPLES["aggenergy_today"])["panels"])
    day = charts.build(store, "day", "2026-11-18", None, IDS)
    assert day["estimated"] and "estimated" in day["note"] and len(day["panel_series"]) == 12
    assert [p["t"] for p in day["points"]] == [r["t"] for r in day["system_points"]]
    last = day["points"][-1]
    stacked = sum(v[-1] for v in day["panel_series"].values())
    assert stacked == pytest.approx(last["total"], abs=0.5)
    share = 3.4 / sum(tigo_data.parse_aggenergy(SAMPLES["aggenergy_today"])["panels"].values())
    assert day["panel_series"]["90375862"][-1] == pytest.approx(last["total"] * share, abs=0.2)
    assert day["system_points"][-1]["t"] == "08:13"
    one = charts.build(store, "day", "2026-11-18", [90375862], IDS)
    assert not one["whole"] and list(one["panel_series"]) == ["90375862"] and one["total_wh"] == 3.4


def test_charts_for_chosen_panels():
    store = _filled_store()
    store.put_panel_power("2026-11-18 08:00", {90375862: 30.0, 90375863: 28.0}, {90375862: 1.5, 90375863: 1.0})
    store.put_panel_power("2026-11-18 08:13", {90375862: 41.0, 90375863: 39.0}, {90375862: 2.5, 90375863: 1.0})
    day = charts.build(store, "day", "2026-11-18", [90375862], IDS)
    # (the add-on's own readings of the panel: exact)
    assert not day["whole"] and not day["estimated"]
    assert day["points"] == [{"t": "08:00", "total": 30.0, "reclaimed": 1.5, "base": 28.5},
                             {"t": "08:13", "total": 41.0, "reclaimed": 2.5, "base": 38.5}]
    assert day["panel_series"] == {"90375862": [30.0, 41.0]} and day["panel_reclaimed"] == {"90375862": [1.5, 2.5]}
    week = charts.build(store, "week", "2026-11-17", [90375862, 90375863], IDS)
    assert week["points"][-1]["total"] == 725 and week["points"][-1]["reclaimed"] is None and week["note"]
    assert set(week["panel_series"]) == {"90375862", "90375863"}
    # all of them chosen: the whole system, with reclaimed
    assert charts.build(store, "week", "2026-11-17", IDS, IDS)["whole"]
    # a day with nothing known of the panel: empty
    empty = charts.build(store, "day", "2026-11-16", [90375862], IDS)
    assert empty["points"] == [] and empty["total_wh"] is None


def test_a_day_recorded_from_part_way_is_estimated_before_that():
    """The add-on started recording each panel at 08:05 (e.g. after a restart): before that,
    each panel is estimated from the system's power, not left out."""
    store = _filled_store()
    store.put_panel_energy("2026-11-18", tigo_data.parse_aggenergy(SAMPLES["aggenergy_today"])["panels"])
    store.put_panel_power("2026-11-18 08:05", {90375862: 30.0}, {90375862: 1.5})
    store.put_panel_power("2026-11-18 08:13", {90375862: 41.0}, {90375862: 2.5})
    day = charts.build(store, "day", "2026-11-18", [90375862], IDS)
    times = [p["t"] for p in day["points"]]
    assert times[0] == "07:30" and times[-2:] == ["08:05", "08:13"]
    assert "07:45" not in times  # (within 20 minutes of a reading: the reading is used)
    assert day["estimated"] and "partly estimated" in day["note"]
    assert day["panel_series"]["90375862"][-2:] == [30.0, 41.0]
    assert day["panel_reclaimed"]["90375862"][-1] == 2.5


def test_your_layout_wins_over_tigos(tmp_path):
    panels = tigo_data.parse_config(SAMPLES["config"])["panels"]
    layout = Layout(str(tmp_path))
    assert layout.apply(panels)[0]["left"] == 50.0 and not layout.apply(panels)[0]["moved"]
    layout.update({"moved": {str(panels[0]["id"]): {"left": 400, "top": 300}}})
    again = Layout(str(tmp_path))  # (kept)
    first = again.apply(panels)[0]
    assert (first["left"], first["top"], first["moved"]) == (400.0, 300.0, True)
    again.update({"moved": {str(panels[0]["id"]): None}})
    assert not again.apply(panels)[0]["moved"]
    again.update({"moved": {str(panels[1]["id"]): {"left": 1, "top": 2}}})
    again.update({"reset": True})
    assert again.moved == {}
    # panels with no place on Tigo's layout: a grid, a row per string
    loose = [dict(p, left=None, top=None) for p in panels]
    placed = Layout(None).apply(loose)
    assert placed[0]["top"] == placed[5]["top"] != placed[6]["top"] and placed[1]["left"] > placed[0]["left"]
    for bad in ({"moved": {"1": {"left": "x"}}}, {"moved": {"1": {"left": 1e9, "top": 0}}}, []):
        with pytest.raises(ValueError):
            Layout(None).update(bad)
