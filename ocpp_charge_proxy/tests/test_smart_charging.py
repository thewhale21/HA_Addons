from src.smart_charging import find_dispatch_sensors, provider_name, smart_charging

NOW = 1_790_000_000.0  # 2026-09-21T14:13:20Z


def _iso(t):
    import datetime
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()


def _octopus(state="off", planned=(), completed=(), started=()):
    def items(slots):
        return [{"start": _iso(a), "end": _iso(b), "charge_in_kwh": k, "source": "smart-charge"} for a, b, k in slots]
    return {
        "entity_id": "binary_sensor.octopus_energy_a1b2_intelligent_dispatching",
        "state": state,
        "attributes": {"planned_dispatches": items(planned), "completed_dispatches": items(completed),
                       "started_dispatches": items(started), "friendly_name": "Intelligent Dispatching"},
    }


def test_not_found():
    states = [{"entity_id": "sensor.x", "state": "1", "attributes": {}},
              {"entity_id": "binary_sensor.y", "state": "on", "attributes": {"planned_dispatches": "nope"}}]
    assert smart_charging(states, NOW) == {"found": False}


def test_octopus_plan_merged_and_split_into_now_and_next():
    h = 3600
    sensor = _octopus(
        state="on",
        planned=[(NOW - 600, NOW + 1200, -1.5), (NOW + 1200, NOW + 3000, -2.0),  # now, joined
                 (NOW + 3 * h, NOW + 3.5 * h, -1.0)],
        completed=[(NOW - 10 * h, NOW - 9 * h, -6.0)],
    )
    out = smart_charging([{"entity_id": "sensor.other", "attributes": {}}, sensor], NOW)
    assert out["found"] and out["provider"] == "Octopus Energy" and out["dispatching"] is True
    assert out["current"]["end"] == _iso(NOW + 3000).replace("+00:00", "Z")
    assert out["current"]["charge_kwh"] == -3.5
    assert len(out["planned"]) == 1 and out["planned_kwh"] == -1.0
    assert [p["charge_kwh"] for p in out["periods"]] == [-6.0, -3.5, -1.0]


def test_edf_and_unknown_suppliers():
    edf = dict(_octopus(), entity_id="binary_sensor.edf_energy_x_intelligent_dispatching")
    other = dict(_octopus(), entity_id="binary_sensor.my_renamed_dispatching")
    sensors = find_dispatch_sensors([other, edf])
    assert [s["entity_id"] for s in sensors] == [edf["entity_id"], other["entity_id"]]  # known first
    out = smart_charging([other, edf], NOW)
    assert out["provider"] == "EDF Energy" and out["others"] == [other["entity_id"]]
    assert out["planned"] == [] and out["planned_kwh"] is None and out["current"] is None
    assert provider_name(other["entity_id"]) == "Your supplier"


def test_bad_items_ignored():
    sensor = _octopus()
    sensor["attributes"]["planned_dispatches"] = [{"start": "x", "end": None}, "junk",
                                                  {"start": _iso(NOW + 60), "end": _iso(NOW + 30)}]
    assert smart_charging([sensor], NOW)["planned"] == []


def test_eon_next_schedule_sensor():
    eon = {"entity_id": "sensor.ab12345_smart_charging_schedule", "state": "Active",
           "attributes": {"schedule": [
               {"start": _iso(NOW + 3600), "end": _iso(NOW + 7200), "type": "SMART", "energy_added_kwh": 3.2},
               {"start": _iso(NOW - 60), "end": _iso(NOW + 600), "type": "SMART", "energy_added_kwh": 0.5}]}}
    lookalike = {"entity_id": "sensor.bins_schedule", "state": "x", "attributes": {"schedule": []}}
    assert [s["entity_id"] for s in find_dispatch_sensors([lookalike, eon])] == [eon["entity_id"]]
    out = smart_charging([eon], NOW)
    assert out["provider"] == "E.ON Next" and out["dispatching"] is True
    assert out["current"]["charge_kwh"] == 0.5
    assert [p["charge_kwh"] for p in out["planned"]] == [3.2]


def test_started_dispatches_ignored():
    # Started 16:01 planned until 22:00; the add-on restarted at 16:41 and
    # Octopus re-planned 17:00-21:30. At 16:48 there's no slot running.
    m = 60
    now = NOW
    sensor = _octopus(
        planned=[(now - 47 * m, now - 6.4 * m, -0.92), (now + 12 * m, now + 282 * m, -6.12)],
        started=[(now - 47 * m, now + 312 * m, -7.0)],
    )
    out = smart_charging([sensor], now)
    assert out["current"] is None and out["dispatching"] is False
    assert [p["start"] for p in out["planned"]] == [_iso(now + 12 * m).replace("+00:00", "Z")]
    # Not on the chart either: the 16:41-17:00 gap stays a gap
    assert [p["charge_kwh"] for p in out["periods"]] == [-0.92, -6.12]
