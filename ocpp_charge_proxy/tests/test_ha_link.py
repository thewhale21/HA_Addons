import asyncio

import pytest

from src.ha_link import HaLink, power_kw, soc_value, validate_settings
from src.shared_state import SharedState


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class Fake:
    def __init__(self):
        self.state = SharedState()
        self.power = []
        self.soc = []
        self.plugs = 0

    def set_power(self, kw):
        self.power.append(kw)

    async def set_soc(self, soc):
        self.soc.append(soc)

    async def plug(self, source=None):
        self.plugs += 1
        self.state.plugged_in = True


def _link(tmp_path=None, **settings):
    fake = Fake()
    link = HaLink(str(tmp_path) if tmp_path else None, fake.state, fake.set_power, fake.set_soc, fake.plug, token="t")
    if settings:
        _run(link.update_settings(settings))
    fake.power.clear()
    fake.soc.clear()
    return link, fake


def _added(**states):
    return {"a": {k: {"s": v, "a": {}} for k, v in states.items()}}


def _changed(entity_id, state):
    return {"c": {entity_id: {"+": {"s": state}}}}


# --- values ------------------------------------------------------------------


def test_power_units():
    assert power_kw({"state": "1370", "attributes": {"unit_of_measurement": "W"}}) == 1.37
    assert power_kw({"state": "1.37", "attributes": {"unit_of_measurement": "kW"}}) == 1.37
    assert power_kw({"state": "1370", "attributes": {}}) == 1.37  # W assumed
    assert power_kw({"state": "unavailable", "attributes": {}}) is None
    assert soc_value({"state": "64"}) == 64 and soc_value({"state": "140"}) is None


def test_validate_settings():
    s = validate_settings({"power_entity": "sensor.p", "auto_plug_soc": "25"})
    assert s["power_entity"] == "sensor.p" and s["auto_plug_soc"] == 25 and s["soc_entity"] == ""
    for bad in ({"plug_entity": "sensor.x"}, {"soc_entity": "binary_sensor.x"},
                {"auto_plug_soc": 0}, {"auto_plug_soc": "x"}, {"power_entity": 5}):
        with pytest.raises(ValueError):
            validate_settings(bad)


# --- following entities -------------------------------------------------------


def test_power_and_soc_sent_on_change():
    link, fake = _link(power_entity="sensor.p", soc_entity="sensor.soc")
    _run(link.handle_entities_event({"a": {
        "sensor.p": {"s": "2000", "a": {"unit_of_measurement": "W"}},
        "sensor.soc": {"s": "64", "a": {}},
    }}))
    assert fake.power == [2.0] and fake.soc == [64.0]
    _run(link.handle_entities_event({"c": {"sensor.p": {"+": {"s": "1.5", "a": {"unit_of_measurement": "kW"}}}}}))
    assert fake.power[-1] == 1.5
    _run(link.handle_entities_event(_changed("sensor.soc", "unavailable")))
    assert fake.soc[-1] is None


def test_unset_sensors_cleared():
    link, fake = _link(power_entity="sensor.p", soc_entity="sensor.soc")
    _run(link.update_settings({"power_entity": "", "soc_entity": ""}))
    assert fake.power == [None] and fake.soc == [None]
    assert link.watched == []


def test_car_connected_plugs_in_on_off_to_on_only():
    link, fake = _link(plug_entity="binary_sensor.cable")
    _run(link.handle_entities_event(_added(**{"binary_sensor.cable": "on"})))
    assert fake.plugs == 0  # first reading only
    _run(link.handle_entities_event(_changed("binary_sensor.cable", "off")))
    _run(link.handle_entities_event(_changed("binary_sensor.cable", "on")))
    assert fake.plugs == 1
    fake.state.plugged_in = True
    _run(link.handle_entities_event(_changed("binary_sensor.cable", "off")))
    assert fake.plugs == 1  # never unplugs


def test_auto_plug_on_soc_drop_watching_reporting_sensor():
    link, fake = _link(soc_entity="sensor.soc", auto_plug=True, auto_plug_soc=30)
    assert link.watched == ["sensor.soc"]
    _run(link.handle_entities_event(_added(**{"sensor.soc": "50"})))
    _run(link.handle_entities_event(_changed("sensor.soc", "29")))
    assert fake.plugs == 1
    snap = link.snapshot()["monitored_soc"]
    assert snap["soc"] == 29 and snap["source"] == "reporting SoC sensor" and snap["auto_plug"] is True


def test_auto_plug_monitor_sensor_not_reported():
    link, fake = _link(auto_plug=True, auto_plug_entity="sensor.away_soc", auto_plug_soc=30)
    _run(link.handle_entities_event(_added(**{"sensor.away_soc": "40"})))
    _run(link.handle_entities_event(_changed("sensor.away_soc", "20")))
    assert fake.plugs == 1 and fake.soc == []
    assert link.snapshot()["monitored_soc"]["source"] == "monitor sensor"


def test_auto_plug_off_without_a_sensor():
    link, _ = _link(auto_plug=True)
    assert link.auto_plug.enabled is False and link.watched == []


def test_settings_saved_and_configured_flag(tmp_path):
    link, _ = _link(tmp_path)
    assert link.configured is False
    _run(link.update_settings({"soc_entity": "sensor.soc"}))
    again, _ = _link(tmp_path)
    assert again.configured is True and again.settings["soc_entity"] == "sensor.soc"


def test_no_supervisor_means_link_off():
    fake = Fake()
    link = HaLink(None, fake.state, fake.set_power, fake.set_soc, fake.plug, token="")
    _run(link.run())  # returns at once
    assert link.available is False and "Supervisor" in link.error


def test_supplier_settings_are_checked():
    s = validate_settings({"supplier_entity": "binary_sensor.x_intelligent_dispatching", "ready_entity": "select.x_target_time",
                           "daily_limit_h": "5.5", "ready_from": "04:00", "ready_to": "11:00"})
    assert s["daily_limit_h"] == 5.5 and s["ready_from"] == "04:00"
    assert validate_settings({"daily_limit_h": ""})["daily_limit_h"] is None  # back to automatic
    for bad in ({"supplier_entity": "switch.x"}, {"ready_entity": "sensor.x"}, {"daily_limit_h": 25},
                {"daily_limit_h": 1.2}, {"ready_from": "04:15"}, {"ready_from": "11:00", "ready_to": "04:00"},
                {"limit_reset": "12:15"}, {"limit_reset": "daily"}, {"limit_hours": 0}, {"limit_hours": 1.5},
                {"limit_hours": 200}, {"limit_hours": 4}, {"limit_hours": 8, "daily_limit_h": 10}):
        with pytest.raises(ValueError):
            validate_settings(bad)


def test_supplier_daily_limit_and_ready_times(tmp_path):
    link, fake = _link(tmp_path)
    assert link.daily_limit_min("Octopus Energy") == 360 and link.daily_limit_min("EDF Energy") is None
    _run(link.update_settings({"daily_limit_h": 5}))
    assert link.daily_limit_min("Octopus Energy") == 300 and link.daily_limit_min("EDF Energy") == 300
    _run(link.update_settings({"daily_limit_h": 0}))
    assert link.daily_limit_min("Octopus Energy") is None  # 0: no limit
    # Octopus's limit resets at 12:00; the others' over any 24 hours
    assert link.limit_reset("Octopus Energy") == "12:00" and link.limit_reset("EDF Energy") is None
    _run(link.update_settings({"limit_reset": "rolling"}))
    assert link.limit_reset("Octopus Energy") is None
    _run(link.update_settings({"limit_reset": "48h"}))  # 2.31.0's: rolling, 48 hours
    assert link.limit_reset("Octopus Energy") == "48h" and link.settings["limit_reset"] == "rolling"
    _run(link.update_settings({"limit_hours": 36}))
    assert link.limit_reset("Octopus Energy") == "36h"
    _run(link.update_settings({"limit_hours": None}))
    assert link.limit_reset("Octopus Energy") is None
    _run(link.update_settings({"limit_reset": "00:00"}))
    assert link.limit_reset("Octopus Energy") == "00:00" and link.limit_reset("EDF Energy") == "00:00"
    _run(link.update_settings({"limit_reset": ""}))
    assert link.limit_reset("Octopus Energy") == "12:00"
    octopus = {"entity_id": "time.octopus_energy_x_intelligent_target_time", "state": "07:00:00", "attributes": {}}
    assert len(link._allowed_times(octopus)) == 48  # any half hour
    _run(link.update_settings({"ready_from": "05:00", "ready_to": "09:30"}))
    assert link._allowed_times(octopus) == ["05:00", "05:30", "06:00", "06:30", "07:00", "07:30", "08:00",
                                            "08:30", "09:00", "09:30"]
    states = [octopus, {"entity_id": "select.mine_target_time", "state": "07:00"}]
    assert link._ready_entity_id(states, "binary_sensor.octopus_energy_x_intelligent_dispatching") == octopus["entity_id"]
    _run(link.update_settings({"ready_entity": "select.mine_target_time"}))
    assert link._ready_entity_id(states, "binary_sensor.octopus_energy_x_intelligent_dispatching") == "select.mine_target_time"


def test_car_plugged_in_sensor_can_add_a_charge():
    link, fake = _link(plug_entity="binary_sensor.cable", plug_ready=True, plug_hours=8)
    calls = []

    async def planned(hours, source, plug_source):
        calls.append((hours, source, plug_source))

    link.on_auto_plug = planned
    _run(link.handle_entities_event(_added(**{"binary_sensor.cable": "off"})))
    _run(link.handle_entities_event(_changed("binary_sensor.cable", "on")))
    assert calls == [(8, "car_plugged", "car plugged in sensor")] and fake.plugs == 0  # it plugs in, not us


def test_supply_voltage_from_a_sensor_or_set():
    from src.charger_sim import ChargerSimulator
    link, fake = _link()
    assert link.voltage() is None  # 230 V
    _run(link.update_settings({"voltage_v": 240}))
    assert link.voltage() == 240
    _run(link.update_settings({"voltage_entity": "sensor.mains_voltage"}))
    assert "sensor.mains_voltage" in link.watched
    link.states["sensor.mains_voltage"] = {"state": "243.6", "attributes": {}}
    assert link.voltage() == 243.6
    link.states["sensor.mains_voltage"] = {"state": "unavailable", "attributes": {}}
    assert link.voltage() == 240  # falls back to the set value
    for bad in ({"voltage_v": 50}, {"voltage_v": "x"}, {"voltage_entity": "switch.x"}):
        with pytest.raises(ValueError):
            validate_settings(bad)
    sim = ChargerSimulator(current_amps=32)
    assert sim.rated_power_kw == 7.4  # 230 V
    sim.voltage_source = lambda: 250.0
    assert sim.rated_power_kw == 8.0 and 248 <= sim.sample_full().voltage <= 252
    sim.voltage_source = lambda: 5.0  # nonsense: ignored
    assert sim.rated_power_kw == 7.4
