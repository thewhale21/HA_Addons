"""The decisions (src/controller.py) and the manager that feeds and acts on
them (src/manager.py), with plain dictionaries for Home Assistant."""

import asyncio
import json
from dataclasses import replace

import pytest

from src.app_settings import AppSettings
from src.controller import Inputs, decide
from src.ha_link import default_settings
from src.manager import Manager, power_kw


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# A car plugged in, in V2X mode, between the limits, charger off for a while, house quiet
BASE = Inputs(plugged_in=True, mode_on=True, running_state="Occupied", active=False, discharging=False,
              inactive_for=600, soc=60, high=80, low=40, battery_kw=0.0, grid_kw=0.0, export_kw=0.0,
              export_held_s=0, ems_mode="Maximum Self Consumption", charge_signal=None)


def d(**changes):
    return decide(replace(BASE, **changes))


# --- what makes it do nothing --------------------------------------------------------


def test_left_alone_unless_plugged_in_v2x_with_a_soc_and_limits():
    assert d(plugged_in=False).rule == "not_plugged_in"
    assert d(mode_on=False).rule == "not_v2x" and d(mode_on=None).rule == "mode_unknown"
    assert d(soc=None).rule == "no_soc"
    assert d(high=None).rule == "no_limits"
    assert d(low=80).rule == "bad_limits" and d(low=80).action is None


# --- starts --------------------------------------------------------------------------


def test_between_the_limits_it_starts_once_the_restart_wait_is_over():
    assert d().action == "start" and d().rule == "in_range"
    waiting = d(inactive_for=100)
    assert waiting.action is None and waiting.rule == "restart_wait" and "80 s" in waiting.reason
    assert d(inactive_for=180).action == "start"
    assert decide(replace(BASE, inactive_for=100), {"restart_wait_s": 60}).action == "start"


def test_house_needing_power_starts_it_above_the_low_limit_even_above_high():
    for power in ({"battery_kw": -2.0}, {"grid_kw": 0.5}):
        assert d(soc=85, **power).rule == "house_needs_power"
        assert d(soc=41, **power).rule == "house_needs_power"
        assert d(soc=40, **power).action is None  # at the low limit: not for discharging
    assert d(soc=85, battery_kw=-0.05).action is None  # below the level: not "needs power"
    assert d(soc=85, battery_kw=None, grid_kw=None).rule == "held_high"  # unknown power doesn't start it


def test_spare_power_starts_it_below_the_high_limit_even_below_low():
    exporting = {"export_kw": 1.2, "export_held_s": 15}
    assert d(soc=30, **exporting).rule == "charge_opportunity"
    assert d(soc=30, export_kw=1.2, export_held_s=5).rule == "held_low"  # not held for 10 s yet
    assert d(soc=30, export_kw=0.4, export_held_s=60).action is None  # below the export level
    assert d(soc=30, ems_blocked=True, **exporting).action is None  # the EMS is force-discharging
    assert d(soc=30, charge_signal=True).rule == "charge_opportunity"  # e.g. Predbat charging
    assert "charge signal" in d(soc=30, charge_signal=True).reason
    assert d(soc=80, charge_signal=True).action is None  # at the high limit: no room


def test_nothing_starts_while_it_is_running_or_resting():
    running = {"active": True, "inactive_for": None, "running_state": "Charging"}
    assert d(battery_kw=-3.0, **running).action is None and d(**running).status == "Charging"
    assert d(charge_signal=True, inactive_for=10).action is None


# --- stops ---------------------------------------------------------------------------


def test_stops_at_the_high_limit_once_the_house_is_quiet_and_it_isnt_discharging():
    charging = {"active": True, "inactive_for": None, "running_state": "Charging"}
    assert d(soc=80, **charging).rule == "high_limit" and d(soc=80, **charging).action == "stop"
    assert d(soc=80, battery_kw=-1.0, **charging).action is None  # the house needs power: leave it
    assert d(soc=80, battery_kw=None, **charging).action is None  # can't tell: leave it
    discharging = {**charging, "running_state": "Discharging", "discharging": True}
    assert d(soc=85, **discharging).action is None  # discharging above high is what's wanted
    assert d(soc=80).action is None  # already off: no button press


def test_stops_at_the_low_limit_when_discharging_unless_told_to_charge():
    discharging = {"active": True, "inactive_for": None, "running_state": "Discharging", "discharging": True}
    assert d(soc=40, **discharging).rule == "low_limit"
    assert d(soc=38, charge_signal=False, **discharging).action == "stop"
    assert d(soc=38, charge_signal=True, **discharging).action is None
    charging = {**discharging, "running_state": "Charging", "discharging": False}
    assert d(soc=38, **charging).action is None  # charging at the low limit is fine


def test_a_margin_keeps_starts_away_from_the_limits():
    t = {"margin_pct": 2}
    assert decide(replace(BASE, soc=79), t).rule == "held_high"
    assert decide(replace(BASE, soc=41), t).rule == "held_low"
    assert decide(replace(BASE, soc=60), t).rule == "in_range"
    on = {"active": True, "inactive_for": None, "running_state": "Charging"}
    assert decide(replace(BASE, soc=80, **on), t).rule == "high_limit"  # stops are still at the limit


# --- the manager: reading Home Assistant and pressing buttons -----------------------------


RS = "sensor.sigen_inverter_dc_charger_running_state"


def _states(running="Occupied", soc="60", battery="0", grid="0", export="0", mode="V2X", lc=0.0,
            high="80", low="40", battery_unit="kW"):
    return {
        RS: {"state": running, "attributes": {}, "last_changed": lc},
        "sensor.sigen_inverter_dc_charger_vehicle_soc": {"state": soc, "attributes": {}},
        "sensor.sigen_plant_battery_power": {"state": battery, "attributes": {"unit_of_measurement": battery_unit}},
        "sensor.sigen_plant_grid_active_power": {"state": grid, "attributes": {"unit_of_measurement": "kW"}},
        "sensor.sigen_plant_grid_export_power": {"state": export, "attributes": {"unit_of_measurement": "kW"}},
        "input_select.sigenergy_evdc_charging_mode": {"state": mode, "attributes": {}},
        "input_number.high": {"state": high, "attributes": {}},
        "input_number.low": {"state": low, "attributes": {}},
        "input_number.cap": {"state": "64", "attributes": {}},
    }


def _entities(**extra):
    return {**default_settings(), "v2x_mode": "input_select.sigenergy_evdc_charging_mode",
            "soc_high": "input_number.high", "soc_low": "input_number.low", "capacity": "input_number.cap", **extra}


def _settings(**changes):
    return {**AppSettings().data, **changes}


class Presses:
    def __init__(self):
        self.pressed, self.notes = [], []

    async def press(self, entity_id):
        self.pressed.append(entity_id)

    async def notify(self, title, message):
        self.notes.append(title)


def test_power_units_are_converted_to_kw():
    assert power_kw({"state": "1500", "attributes": {"unit_of_measurement": "W"}}) == 1.5
    assert power_kw({"state": "-0.2", "attributes": {"unit_of_measurement": "kW"}}) == -0.2
    assert power_kw({"state": "unavailable", "attributes": {}}) is None and power_kw(None) is None


def test_manager_starts_in_range_after_the_restart_wait_and_presses_start(tmp_path):
    p = Presses()
    m = Manager(str(tmp_path), press=p.press, notify=p.notify)
    ent, st = _entities(), _settings()
    first = _run(m.step(_states(lc=1000.0), ent, st, now=1100.0))  # stopped 100 s ago
    assert first.rule == "restart_wait" and p.pressed == []
    second = _run(m.step(_states(lc=1000.0), ent, st, now=1200.0))
    assert second.rule == "in_range" and p.pressed == ["button.sigen_inverter_dc_charger_start_charging"]
    assert m.presses_today == 1 and m.log[-1]["pressed"] and m.log[-1]["soc"] == 60
    # The charger takes a moment to start: no second press within the press gap
    third = _run(m.step(_states(lc=1000.0), ent, st, now=1230.0))
    assert third.rule == "press_gap" and len(p.pressed) == 1
    assert p.notes == []  # no notify service set


def test_manager_follows_the_charger_stopping_on_its_own(tmp_path):
    p = Presses()
    m = Manager(str(tmp_path), press=p.press)
    ent, st = _entities(), _settings()
    _run(m.step(_states(running="Discharging", battery="-1"), ent, st, now=5000.0))
    assert m.active and p.pressed == []
    # The car stops discharging by itself (some cars do): wait before starting it again
    d1 = _run(m.step(_states(running="Occupied", battery="-1"), ent, st, now=5010.0))
    assert d1.rule == "restart_wait" and p.pressed == []
    d2 = _run(m.step(_states(running="Occupied", battery="-1"), ent, st, now=5010.0 + 180))
    assert d2.rule == "house_needs_power" and p.pressed == ["button.sigen_inverter_dc_charger_start_charging"]


def test_manager_stops_at_the_low_limit_and_watch_only_presses_nothing(tmp_path):
    p = Presses()
    m = Manager(str(tmp_path), press=p.press, notify=p.notify)
    ent = _entities()
    watch = _run(m.step(_states(running="Discharging", soc="39"), ent, _settings(observe_only=True), now=100.0))
    assert watch.rule == "low_limit" and p.pressed == [] and m.log[-1]["observe_only"]
    real = _run(m.step(_states(running="Discharging", soc="39"), ent,
                       _settings(notify_service="notify.mobile_app_phone"), now=500.0))
    assert real.rule == "low_limit" and p.pressed == ["button.sigen_inverter_dc_charger_stop_charging"]
    assert p.notes == ["V2X: charger stopped"]


def test_manager_waits_for_export_to_be_held(tmp_path):
    p = Presses()
    m = Manager(str(tmp_path), press=p.press)
    ent, st = _entities(), _settings()
    assert _run(m.step(_states(soc="30", export="2"), ent, st, now=1000.0)).rule == "held_low"
    assert _run(m.step(_states(soc="30", export="2"), ent, st, now=1011.0)).rule == "charge_opportunity"


def test_last_known_soc_is_kept_and_saved(tmp_path):
    m = Manager(str(tmp_path))
    ent, st = _entities(), _settings()
    _run(m.step(_states(soc="62"), ent, st, now=10.0))
    _run(m.step(_states(soc="0"), ent, st, now=20.0))  # the charger reads 0 while it's off
    _run(m.step(_states(soc="unavailable"), ent, st, now=30.0))
    assert m.inputs.soc == 62
    again = Manager(str(tmp_path))
    assert again.soc == 62  # kept after a restart
    # Unplugged and plugged in again: the old SoC is still used, but marked as such
    _run(again.step(_states(running="Idle", soc="0"), ent, st, now=40.0))
    _run(again.step(_states(running="Occupied", soc="0"), ent, st, now=50.0))
    assert again.soc_before_plug_in and again.snapshot(60.0)["soc_before_plug_in"]
    _run(again.step(_states(running="Charging", soc="64"), ent, st, now=70.0))
    assert not again.soc_before_plug_in and again.soc == 64


def test_v2x_mode_can_be_a_select_or_a_switch(tmp_path):
    m = Manager(str(tmp_path))
    st = _settings()
    assert _run(m.step(_states(mode="Fast Charging"), _entities(), st, now=1.0)).rule == "not_v2x"
    sw = {**_states(), "input_boolean.evdc_v2x_mode": {"state": "on", "attributes": {}}}
    ent = _entities(v2x_mode="input_boolean.evdc_v2x_mode")
    assert _run(m.step(sw, ent, st, now=2.0)).rule != "not_v2x"


def test_energy_sensors_like_the_v2x_templates(tmp_path):
    m = Manager(str(tmp_path))
    _run(m.step(_states(soc="60"), _entities(), _settings(), now=1.0))
    assert m.energy() == {"available_kwh": 12.8, "window_kwh": 25.6, "window_pct": 50.0}
    _run(m.step(_states(soc="30"), _entities(), _settings(), now=2.0))
    assert m.energy()["available_kwh"] == 0.01  # below the low limit
    _run(m.step(_states(mode="Fast Charging"), _entities(), _settings(), now=3.0))
    assert m.energy() == {"available_kwh": 0.01, "window_kwh": 0.01, "window_pct": 0.0}


def test_tuning_settings_are_checked(tmp_path):
    s = AppSettings(str(tmp_path))
    s.update({"restart_wait_s": 240, "notify_service": "mobile_app_phone", "active_states": "Charging, Discharging"})
    again = AppSettings(str(tmp_path)).data
    assert again["restart_wait_s"] == 240 and again["notify_service"] == "notify.mobile_app_phone"
    assert again["active_states"] == ["Charging", "Discharging"]
    for bad in ({"restart_wait_s": -1}, {"observe_only": "yes"}, {"active_states": []},
                {"notify_service": "notify.bad name"}, {"nope": 1}):
        with pytest.raises(ValueError):
            s.update(bad)
    json.dumps(again)


def test_missing_helpers_are_found_or_made(tmp_path):
    from src.ha_link import HaLink
    from src.helpers import ensure_helpers
    from src.shared_state import SharedState

    class FakeLink(HaLink):
        def __init__(self, existing, folder):
            folder.mkdir()
            super().__init__(str(folder), SharedState(), token="")
            self.existing, self.made = existing, []

        async def all_states(self, fresh=False):
            return [{"entity_id": e, "state": v} for e, v in self.existing.items()]

        async def query(self, payload, timeout=30):
            self.made.append(payload)
            return {"id": payload["name"].lower().replace(" ", "_")}

    link = FakeLink({"input_select.sigenergy_evdc_charging_mode": "V2X", "input_number.v2x_cut_off_threshold": "35",
                     "input_number.evdc_vehicle_battery_capacity": "64"}, tmp_path / "a")
    done = _run(ensure_helpers(link))
    assert link.settings["v2x_mode"] == "input_select.sigenergy_evdc_charging_mode"  # already there
    assert link.settings["capacity"] == "input_number.evdc_vehicle_battery_capacity"  # already there
    assert link.settings["soc_high"] == "input_number.evdc_soc_high_limit"
    made = {p["name"]: p for p in link.made}
    assert set(made) == {"EVDC SoC High Limit", "EVDC SoC Low Limit"}
    assert made["EVDC SoC Low Limit"]["initial"] == 35.0  # from the automation's own helper
    assert made["EVDC SoC High Limit"]["initial"] == 80 and made["EVDC SoC High Limit"]["type"] == "input_number/create"
    assert len(done) == 4 and _run(ensure_helpers(link)) == []  # nothing left to do

    fresh = FakeLink({}, tmp_path / "b")
    _run(ensure_helpers(fresh))
    assert fresh.settings["v2x_mode"] == "input_boolean.evdc_v2x_mode"
