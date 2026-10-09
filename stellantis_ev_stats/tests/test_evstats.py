"""The statistics (src/evstats.py) and feeding them (src/runner.py)."""

import asyncio
import datetime

from src.evstats import KM_PER_MI, EvStats, number, parse_trip, to_c, to_km
from src.ha_link import find_entities
from src.runner import Feed, Runner, history_events
from src.shared_state import SharedState

T0 = datetime.datetime(2026, 10, 1, 8, 0, tzinfo=datetime.timezone.utc).timestamp()
TRIP_ATTRS = {"duration": "00:30:00", "start_mileage": "12000 km", "avg_speed": "48.0 km/h",
              "electric_consumption": "4.0 kWh", "electric_avg_consumption": "16.0 kWh/100km"}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_reading_the_integrations_values():
    assert number("4.25 kWh") == 4.25 and number("12,5 km") == 12.5 and number("x") is None and number(None) is None
    assert round(to_km(10, "mi"), 3) == 16.093 and to_km(1500, "m") == 1.5 and to_km(5, "km") == 5
    assert round(to_c(50, "°F"), 1) == 10.0 and to_c(10, "°C") == 10
    t = parse_trip("25.0", TRIP_ATTRS)
    assert t == {"km": 25.0, "kwh": 4.0, "duration_s": 1800, "odo_start": 12000.0, "avg_kmh": 48.0}
    # No total: from the average; distances in miles
    t = parse_trip("10", {"electric_avg_consumption": "16 kWh/100km"}, "mi")
    assert round(t["km"], 2) == 16.09 and round(t["kwh"], 3) == round(0.16 * 10 * KM_PER_MI, 3)
    assert parse_trip("0", TRIP_ATTRS) is None and parse_trip("unknown", {}) is None


def test_a_trip_gets_its_temperature_and_soc():
    s = EvStats()
    s.soc(T0 - 600, 80)
    s.temperature(T0 + 300, 4.0)
    s.temperature(T0 + 1500, 6.0)
    end = T0 + 1800
    rec = s.trip(end, parse_trip("25", TRIP_ATTRS))
    assert rec["temp_c"] == 5.0 and rec["soc_start"] == 80 and rec["soc_end"] is None
    s.soc(end + 120, 74)  # the SoC after the trip comes in just after it
    assert s.trips[-1]["soc_end"] == 74
    assert s.trip(end + 5, parse_trip("25", TRIP_ATTRS)) is None  # the same trip again: not counted twice


def _drive(s, when, km, kwh, temp, soc_from=None, soc_to=None):
    s.temperature(when - 600, temp)
    if soc_from is not None:
        s.soc(when - 1900, soc_from)
    attrs = {"duration": "00:30:00", "start_mileage": f"{when / 1000:.1f} km", "electric_consumption": f"{kwh} kWh"}
    s.trip(when, parse_trip(str(km), attrs))
    if soc_to is not None:
        s.soc(when + 60, soc_to)


def test_efficiency_and_range_by_temperature():
    s = EvStats()
    t = T0
    for _ in range(3):  # cold: 20 km on 4 kWh (5 km/kWh); mild: 30 km on 4 kWh (7.5 km/kWh)
        _drive(s, t, 20, 4, 2.0, 60, 52)
        _drive(s, t + 7200, 30, 4, 12.0, 52, 44)
        t += 86400
    _drive(s, t, 1, 0.5, 12.0)  # too short to count
    for i in range(5):  # Battery residual ÷ SoC: 50 kWh usable
        s.residual(T0 + i * 3600, 25.0, 50)
    s.range_reading(T0, 50, 150.0, 3.0)  # the car thinks 300 km at 100% when cold
    s.range_reading(T0 + 3600, 50, 175.0, 12.0)
    sm = s.summary(t + 3600, {"min_trip_mi": 2}, current={"temp_c": 11.0, "soc": 50, "range_km": 160.0})
    assert sm["usable_kwh"] == 50 and sm["usable_from"].startswith("measured")
    cold, mild = sm["bands"]
    assert (cold["from_c"], cold["trips"], mild["from_c"], mild["trips"]) == (0, 3, 10, 3)
    assert cold["mi_per_kwh"] == round(5 / KM_PER_MI, 2) and mild["mi_per_kwh"] == round(7.5 / KM_PER_MI, 2)
    assert cold["real_full_mi"] == round(5 / KM_PER_MI * 50) and mild["real_full_mi"] == round(7.5 / KM_PER_MI * 50)
    assert cold["soc_full_mi"] == round(20 / 8 * 100 / KM_PER_MI)  # 20 km for 8%
    assert cold["car_full_mi"] == round(300 / KM_PER_MI) and mild["car_full_mi"] == round(350 / KM_PER_MI)
    now = sm["now"]
    assert now["band"] == 10 and abs(now["real_left_mi"] - mild["real_full_mi"] / 2) <= 1
    assert now["car_full_mi"] == round(320 / KM_PER_MI)
    assert sm["efficiency"]["overall"]["trips"] == 6  # the short one left out
    assert sm["trip_count"] == 7
    # A usable capacity set by hand wins
    assert s.summary(t, {"usable_kwh": 46})["usable_kwh"] == 46


def test_saved_and_merged(tmp_path):
    s = EvStats(str(tmp_path))
    _drive(s, T0, 20, 4, 5.0, 60, 52)
    s.soh(T0, 98.0, 100.0)
    s.soh(T0 + 10, 98.0, 100.0)  # unchanged: not again
    s.save()
    again = EvStats(str(tmp_path))
    assert len(again.trips) == 1 and len(again.health) == 1
    other = EvStats()
    _drive(other, T0, 20, 4, 5.0)  # the same trip
    _drive(other, T0 - 86400, 15, 3, 8.0)
    other.soh(T0 - 86400, 99.0, 100.0)
    assert again.merge(other) == {"trips": 1, "ranges": 0, "health": 1}
    assert [t["km"] for t in again.trips] == [15, 20] and [h["soh_capacity"] for h in again.health] == [99.0, 98.0]


def test_finding_the_cars_sensors():
    states = [{"entity_id": e, "attributes": {"start_mileage": "1 km"} if e.endswith("last_trip") else {}} for e in (
        "sensor.vr3_last_trip", "sensor.vr3_battery", "sensor.vr3_range", "sensor.vr3_temperature",
        "sensor.vr3_battery_residual", "sensor.vr3_battery_soh_capacity", "sensor.vr3_mileage", "sensor.other_battery")]
    found = find_entities(states)
    assert found == {"last_trip": "sensor.vr3_last_trip", "soc": "sensor.vr3_battery", "range": "sensor.vr3_range",
                     "temperature": "sensor.vr3_temperature", "residual": "sensor.vr3_battery_residual",
                     "soh_capacity": "sensor.vr3_battery_soh_capacity", "odometer": "sensor.vr3_mileage"}
    assert find_entities([{"entity_id": "sensor.x"}]) == {}


def test_history_is_replayed_in_order():
    ents = {"last_trip": "sensor.c_last_trip", "soc": "sensor.c_battery", "temperature": "sensor.c_temperature"}
    history = {
        "sensor.c_battery": [{"s": "70", "lu": T0 - 1900}, {"s": "62", "lu": T0 + 30}],
        "sensor.c_temperature": [{"s": "41", "lu": T0 - 1000}],
        "sensor.c_last_trip": [{"s": "unknown", "lu": T0 - 5000}, {"s": "25", "a": TRIP_ATTRS, "lu": T0}],
    }
    events = history_events(history, ents)
    assert [e[1] for e in events] == ["last_trip", "soc", "temperature", "last_trip", "soc"]
    s = EvStats()
    feed = Feed(s)
    units = {"temperature": "°F"}
    for ts, key, state, attrs in events:
        feed.apply(key, ts, state, attrs, units.get(key))
    (trip,) = s.trips
    assert trip["temp_c"] == 5.0 and trip["soc_start"] == 70 and trip["soc_end"] == 62


class _Link:
    def __init__(self):
        self.settings = {"last_trip": "sensor.c_last_trip", "soc": "sensor.c_battery", "range": "sensor.c_range",
                         "temperature": "sensor.c_temperature"}
        self.states = {}
        self.connected = True

    def key_for(self, entity_id):
        return [k for k, v in self.settings.items() if v == entity_id]


class _Settings:
    data = {"min_trip_mi": 2, "usable_kwh": 50}


def test_live_readings_update_the_page_and_sensors():
    from src.ha_entities import values

    state = SharedState()
    runner = Runner(_Link(), EvStats(), _Settings(), state)

    async def feed():
        await runner.entity_changed("sensor.c_temperature", {"state": "8", "attributes": {"unit_of_measurement": "°C"}, "ts": T0 - 900})
        await runner.entity_changed("sensor.c_battery", {"state": "60", "attributes": {}, "ts": T0 - 1900})
        await runner.entity_changed("sensor.c_range", {"state": "100", "attributes": {"unit_of_measurement": "mi"}, "ts": T0 - 1800})
        await runner.entity_changed("sensor.c_last_trip", {"state": "30", "attributes": {**TRIP_ATTRS}, "ts": T0})
        await runner.entity_changed("sensor.c_battery", {"state": "52", "attributes": {}, "ts": T0 + 60})
    _run(feed())
    assert state.trips == 1 and state.status == "Recording"
    now = state.brief["now"]
    assert now["band"] == 5 and now["mi_per_kwh"] == round(30 / 4 / KM_PER_MI, 2)
    assert now["real_full_mi"] == round(30 / 4 / KM_PER_MI * 50) and now["car_range_mi"] == 100
    v = values(state)
    assert v["real_range_full"][0] == now["real_full_mi"] and v["usable_capacity"][0] == 50 and v["trips"] == 1
