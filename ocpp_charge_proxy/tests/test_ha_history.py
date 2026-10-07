import asyncio
import datetime

from src.gui_data import PowerHistory
from src.ha_history import (
    CURRENT, ENERGY, POWER, ChartHistory, charging_per_day, fine_samples, long_samples, parse_history, parse_statistics,
)
from src.ha_entities import LIMIT_SENSOR, STATUS_SENSOR
from src.shared_state import SharedState

T0 = 1_790_000_000.0  # a multiple of 10 and of 300


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_parse_history_compact_and_full():
    result = {
        "sensor.a": [{"s": "1.5", "a": {"x": 1}, "lu": T0}, {"s": "unavailable", "lu": T0 + 10}, {"s": "2", "lu": T0 + 20}],
        "sensor.b": [{"state": "Charging", "attributes": {}, "last_updated": "2026-09-21T14:13:20+00:00"}],
    }
    rows = parse_history(result, "sensor.a")
    assert [(t - T0, s) for t, s, _ in rows] == [(0, "1.5"), (10, None), (20, "2")]
    assert rows[2][2] == {"x": 1}  # attributes carry on with minimal_response
    assert parse_history(result, "sensor.b")[0][1] == "Charging"
    assert parse_history(None, "sensor.a") == []


def test_parse_statistics_milliseconds():
    rows = parse_statistics({"s": [{"start": T0 * 1000, "end": (T0 + 300) * 1000, "mean": 1.0}]}, "s")
    assert rows[0]["start"] == T0


def test_fine_samples_step_and_gaps():
    rows = {
        "power": [(T0, "1.4", {}), (T0 + 25, None, {}), (T0 + 45, "0.0", {})],  # stopped 25-45 s
        "status": [(T0 - 100, "Charging", {})],
        "limit": [(T0 - 100, "6", {"max_amps": 6, "provider_limit_amps": 32.0})],
        "current": [(T0, "6.1", {})],
    }
    out = fine_samples(rows, T0, T0 + 60)
    assert [s["t"] - T0 for s in out] == [10, 20, 50]  # 30 and 40: add-on stopped
    assert out[0]["power_kw"] == 1.4 and out[0]["state"] == "Charging"
    assert out[0]["effective_amps"] == 6.0 and out[0]["provider_limit_amps"] == 32.0
    assert out[0]["soc"] is None


def test_long_samples_from_statistics():
    stats = {
        "power": [{"start": T0, "end": T0 + 300, "mean": 1.2, "max": 1.4},
                  {"start": T0 + 300, "end": T0 + 600, "mean": 0.0, "max": 0.0}],
        "current": [{"start": T0, "mean": 5.2}],
        "limit": [{"start": T0, "mean": 6.0}],
    }
    rows = {"status": [(T0 - 50, "Preparing", {}), (T0 + 100, "Charging", {}), (T0 + 280, "Finishing", {}),
                       (T0 + 290, "Preparing", {})],
            "soc": [(T0, "55", {})]}
    out = long_samples(stats, rows)
    assert [(p["t"] - T0, p["d"]) for p in out] == [(150, 300), (450, 300)]
    assert out[0]["state"] == "Charging"  # the most telling state in the 5 minutes
    assert out[1]["state"] == "Preparing"
    assert out[0]["power_max_kw"] == 1.4 and out[0]["current_a"] == 5.2 and out[0]["soc"] == 55.0
    assert out[0]["effective_amps"] == 6.0


class FakeLink:
    connected = True

    def __init__(self):
        self.queries = []

    async def query(self, payload, timeout=30):
        self.queries.append(payload)
        if payload["type"] == "history/history_during_period":
            ids = payload["entity_ids"]
            out = {}
            if POWER in ids:
                out[POWER] = [{"s": "1.4", "lu": T0 - 3 * 3600}]
                out[CURRENT] = [{"s": "6.0", "lu": T0 - 3 * 3600}]
            if STATUS_SENSOR in ids:
                out[STATUS_SENSOR] = [{"s": "Charging", "lu": T0 - 3 * 3600}]
            if LIMIT_SENSOR in ids:
                out[LIMIT_SENSOR] = [{"s": "6", "a": {"max_amps": 6}, "lu": T0 - 3 * 3600}]
            return out
        if payload["type"] == "recorder/statistics_during_period":
            if payload["period"] == "day":
                today = datetime.date.fromtimestamp(T0)
                start = datetime.datetime.combine(today, datetime.time()).astimezone().timestamp()
                return {ENERGY: [{"start": start * 1000, "change": 7.25},
                                 {"start": (start - 86400) * 1000, "change": 6000.0}]}  # a meter jump
            if payload["period"] == "5minute":
                return {POWER: [{"start": (T0 - 600) * 1000, "end": (T0 - 300) * 1000, "mean": 1.4, "max": 1.5}]}
            return {}
        raise AssertionError(payload)


def test_samples_older_than_memory_come_from_ha():
    link = FakeLink()
    recent = PowerHistory(clock=lambda: T0)
    recent.sample(SharedState(power_kw=0.5))
    charts = ChartHistory(link, soc_entity=lambda: None, recent=recent, clock=lambda: T0 + 5)
    out = _run(charts.samples(T0 - 3600))
    assert out[-1]["power_kw"] == 0.5  # from memory
    older = out[:-1]
    assert len(older) == 359 and older[0]["power_kw"] == 1.4 and older[0]["state"] == "Charging"
    # The page's 10-second refresh doesn't ask HA
    link.queries.clear()
    assert _run(charts.samples(T0 - 1)) == recent.since(0)
    assert link.queries == []


def test_without_ha_only_memory():
    recent = PowerHistory(clock=lambda: T0)
    recent.sample(SharedState(power_kw=0.5))
    charts = ChartHistory(None, soc_entity=lambda: None, recent=recent, clock=lambda: T0 + 5)
    assert len(_run(charts.samples(0))) == 1
    assert _run(charts.long_samples(0)) == []


def test_long_samples_and_daily_from_ha():
    link = FakeLink()
    today = datetime.date.fromtimestamp(T0)
    charts = ChartHistory(link, soc_entity=lambda: "sensor.car_soc", clock=lambda: T0, today=lambda: today)
    (point,) = _run(charts.long_samples(0))
    assert point["power_kw"] == 1.4 and point["state"] == "Charging" and point["max_amps"] == 6
    days = _run(charts.daily(2, []))
    assert [d["kwh"] for d in days] == [0.0, 7.25]  # the 6000 kWh jump is ignored
    history_calls = [q for q in link.queries if q["type"] == "history/history_during_period"]
    assert any("sensor.car_soc" in q["entity_ids"] for q in history_calls)


def test_charging_per_day():
    day = 86400
    days = [("d1", T0, T0 + day), ("d2", T0 + day, T0 + 2 * day)]
    rows = [(T0, "Preparing", {}), (T0 + day - 3600, "Charging", {}),  # 23:00 to 01:30
            (T0 + day + 5400, "SuspendedEVSE", {}), (T0 + day + 7200, "Charging", {})]
    out = charging_per_day(rows, days, now=T0 + day + 7200 + 600)  # still charging, 10 min so far
    assert out == {"d1": 3600.0, "d2": 5400.0 + 600.0}
    # History starting part-way through a day: that day is unknown
    assert charging_per_day(rows[1:], days, now=T0 + 2 * day) == {"d2": 5400.0 + day - 7200}
    assert charging_per_day([], days, now=T0) == {}


def test_daily_charging_time_falls_back_to_sessions():
    import datetime as dt
    from src.gui_data import daily_from_sessions
    today = dt.date(2026, 10, 3)
    start = dt.datetime.combine(today - dt.timedelta(days=1), dt.time(23, 0)).astimezone().isoformat()
    sessions = [{"start": start, "energy_kwh": 5.0, "duration_s": 7200}]
    days = daily_from_sessions(2, sessions, today, {}, {"2026-10-03": 1800.0})
    assert [(d["charging_s"], d["charging_estimated"]) for d in days] == [(7200, True), (1800, False)]
