"""The add-on's building blocks, without Home Assistant or a web server."""

import asyncio
import json
import logging

import pytest

from src.app_settings import AppSettings
from src.config import Config, load_config
from src.debug_tools import DebugTools, LogBuffer, redacted_config
from src.ha_entities import SENSORS, SensorPublisher, entity_info
from src.ha_link import HaLink, entity_list, validate_settings
from src.log_filters import DemoteWebPageRequests
from src.shared_state import SharedState


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_options_are_read_with_defaults(tmp_path):
    path = tmp_path / "options.json"
    path.write_text(json.dumps({"something_old": 1}))
    assert load_config(str(path)) == Config()
    assert load_config(str(tmp_path / "missing.json")) == Config()


def test_app_settings_are_checked_and_saved(tmp_path):
    seen = []
    s = AppSettings(str(tmp_path), on_change=seen.append)
    assert s.log_level == "info"
    s.update({"log_level": "debug"})
    assert seen == [{"log_level": "debug"}]
    assert logging.getLogger().getEffectiveLevel() == logging.DEBUG  # applied straight away
    s.update({"log_level": "info"})
    assert AppSettings(str(tmp_path)).log_level == "info"  # kept after a restart
    for bad in ({"log_level": "loud"}, {}, "x"):
        with pytest.raises(ValueError):
            s.update(bad)


def test_entity_settings_are_checked():
    assert validate_settings({"weather_entity": " weather.home "})["weather_entity"] == "weather.home"
    assert validate_settings({"person_1": "person.matt", "person_2": "device_tracker.phone"})["person_2"] == "device_tracker.phone"
    assert validate_settings({"weather_entity": ""})["weather_entity"] == ""
    for bad in ({"weather_entity": "sensor.x"}, {"person_1": "weather.home"}, {"weather_entity": 3}, {"nope": 1}, {"person_7": "person.x"}, []):
        with pytest.raises(ValueError):
            validate_settings(bad)


def test_link_follows_changes_and_saves(tmp_path):
    seen = []

    async def changed(entity_id, st):
        seen.append((entity_id, (st or {}).get("state")))

    link = HaLink(str(tmp_path), SharedState(), token="", on_entity_changed=changed)
    assert not link.available and link.watched == []
    _run(link.update_settings({"person_1": "person.matt"}))
    assert link.watched == ["person.matt"]
    _run(link.handle_entities_event({"a": {"person.matt": {"s": "home", "a": {"friendly_name": "Matt"}}}}))
    _run(link.handle_entities_event({"c": {"person.matt": {"+": {"s": "not_home"}}}}))
    assert seen[-2:] == [("person.matt", "home"), ("person.matt", "not_home")]
    snap = link.snapshot()
    assert snap["entities"]["person_1"] == {"entity_id": "person.matt", "name": "Matt", "state": "not_home", "unit": None}
    assert HaLink(str(tmp_path), SharedState(), token="").settings["person_1"] == "person.matt"  # saved
    assert HaLink(str(tmp_path), SharedState(), token="x").watched == ["person.matt", "sun.sun"]  # (the sun, under HA)


def test_entity_list_for_the_pickers():
    out = entity_list([
        {"entity_id": "weather.b", "state": "rainy", "attributes": {"friendly_name": "B"}},
        {"entity_id": "automation.x", "state": "on", "attributes": {}},
        {"entity_id": "person.a", "state": "home", "attributes": {"friendly_name": "A"}},
    ])
    assert [e["entity_id"] for e in out] == ["person.a", "weather.b"]


def test_own_sensors_are_posted_when_they_change():
    pub, state = SensorPublisher(), SharedState(status="Running")
    first = pub.due(state, 0)
    assert {e for e, _, _ in first} == {e for e, _ in SENSORS.values()}
    assert pub.due(state, 10) == []  # nothing changed
    state.status = "Ready"
    assert [(e, v) for e, v, _ in pub.due(state, 20)] == [(SENSORS["status"][0], "Ready")]
    assert len(pub.due(state, 10_000)) == len(SENSORS)  # posted again now and then
    assert all(v == "unavailable" for _, v, _ in SensorPublisher.unavailable())
    assert entity_info({}, "") is None


def test_debug_tools_hide_secrets_and_set_the_log_level(tmp_path):
    class Opts:
        def __init__(self):
            self.name, self.password, self.api_token = "x", "hunter2", "abc"

    assert redacted_config(Opts()) == {"name": "x", "password": "***", "api_token": "***"}
    settings = AppSettings(str(tmp_path), on_change=lambda c: settings.apply_log_level())
    buf = LogBuffer(5)
    buf.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger("t").addHandler(buf)
    logging.getLogger("t").warning("hello")
    debug = DebugTools(config=Config(), log_buffer=buf, settings=settings)
    assert debug.info()["logs"] == ["hello"] and debug.info()["config"] == {}
    debug.set_log_level("debug")
    assert settings.log_level == "debug" and logging.getLogger().getEffectiveLevel() == logging.DEBUG
    with pytest.raises(ValueError):
        debug.set_log_level("loud")
    settings.update({"log_level": "info"})
    logging.getLogger("t").removeHandler(buf)


def test_page_polling_is_kept_out_of_the_log():
    f = DemoteWebPageRequests()

    def rec(msg):
        return logging.LogRecord("aiohttp.access", logging.INFO, "", 0, msg, None, None)

    logging.getLogger().setLevel(logging.INFO)
    assert not f.filter(rec('1.2.3.4 "GET /api/state HTTP/1.1" 200 12'))
    assert f.filter(rec('1.2.3.4 "POST /api/sensors HTTP/1.1" 200 12'))
    assert f.filter(rec('1.2.3.4 "GET /api/state HTTP/1.1" 500 12'))


def test_whats_happening_now():
    from src.live import compute, entities
    settings = {"weather_entity": "weather.home", "person_1": "person.matt", "person_3": "person.jo_bloggs", "person_2": ""}
    assert entities(settings) == {"weather": "weather.home", "people": ["person.matt", "person.jo_bloggs"], "sun": "sun.sun",
                                  "energy": {"solar": "", "car": "", "heat": ""},
                                  "house": {"bins": "", "door": "", "garage": "", "lights": ""}}
    states = {
        "sun.sun": {"state": "below_horizon"},
        "weather.home": {"state": "rainy", "attributes": {"temperature": 9.4, "temperature_unit": "°C"}},
        "person.matt": {"state": "home", "attributes": {"friendly_name": "Matt Lee", "entity_picture": "/api/image/serve/x/512x512"}},
        "person.jo_bloggs": {"state": "Work", "attributes": {}},
    }
    live = compute(settings, states)
    assert live["night"] is True and live["weather"] == {"entity": "weather.home", "state": "rainy", "temperature": 9.4, "unit": "°C"}
    assert [(p["name"], p["initials"], p["home"], p["state"]) for p in live["people"]] == [("Matt Lee", "ML", True, "home"), ("Jo Bloggs", "JB", False, "Work")]
    assert compute({}, {})["night"] is None and compute({}, {})["weather"] is None
    assert live["sun"] is None and live["energy"] == {"solar": None, "car": False, "charging": False, "heat": None}


def test_the_sun_and_your_energy():
    from src.live import active, compute
    settings = {"solar_entity": "sensor.pv", "car_entity": "binary_sensor.ev", "heat_pump_entity": "climate.hp"}
    states = {"sun.sun": {"state": "above_horizon", "attributes": {"azimuth": 213.4, "elevation": 7.6}},
              "sensor.pv": {"state": "1.4", "attributes": {"unit_of_measurement": "kW"}},
              "binary_sensor.ev": {"state": "off"},
              "climate.hp": {"state": "heat", "attributes": {"hvac_action": "idle"}}}
    live = compute(settings, states)
    assert live["sun"] == {"az": 215, "el": 8}
    assert live["energy"] == {"solar": True, "car": True, "charging": False, "heat": False}  # (in heat mode, but idle)
    assert not active({"state": "12", "attributes": {"unit_of_measurement": "W"}}) and active({"state": "350"})
    assert active({"state": "idle", "attributes": {"hvac_action": "heating"}}) and not active({"state": "unavailable"})


def test_occasions_settings(tmp_path):
    import pytest
    from src.app_settings import OCCASIONS, AppSettings
    s = AppSettings(str(tmp_path))
    assert s.data["occasions"] == OCCASIONS
    s.update({"occasions": {"xmas": {"on": True, "from": "12-10", "to": "01-02"}, "easter": {"on": True, "auto": False, "from": "04-01", "to": "04-08"},
                            "birthdays": {"on": True, "dates": [{"date": "2000-11-27", "name": "Laura"}, "03-14"]}, "gone": {"on": True}}})
    o = AppSettings(str(tmp_path)).data["occasions"]
    assert o["xmas"]["from"] == "12-10" and o["easter"]["auto"] is False and o["cny"]["auto"] is True
    assert o["birthdays"]["dates"] == [{"date": "11-27", "name": "Laura"}, {"date": "03-14", "name": ""}] and "gone" not in o
    for bad in ({"xmas": {"on": True, "from": "13-01", "to": "01-01"}}, {"halloween": {"on": True, "from": "", "to": ""}},
                {"birthdays": {"dates": ["31st"]}}):
        with pytest.raises(ValueError):
            s.update({"occasions": bad})
    s.update({"occasions": {"halloween": {"on": False, "from": "", "to": ""}}})  # (off: no days needed)


def test_your_house_bins_door_garage_lights():
    import datetime as dt
    from src.live import bin_day, compute
    morning, evening = dt.datetime(2026, 11, 27, 9), dt.datetime(2026, 11, 27, 19)
    assert bin_day({"state": "Today"}, morning) and bin_day({"state": "on"}, morning) and bin_day({"state": "0"}, morning)
    assert not bin_day({"state": "1"}, morning) and bin_day({"state": "1"}, evening)
    assert not bin_day({"state": "tomorrow"}, morning) and bin_day({"state": "Tomorrow"}, evening)
    assert bin_day({"state": "2026-11-27"}, morning) and not bin_day({"state": "2026-11-28"}, morning) and bin_day({"state": "2026-11-28"}, evening)
    assert bin_day({"state": "off", "attributes": {"start_time": "2026-11-27 07:00:00"}}, morning)
    assert not bin_day({"state": "3"}, evening) and not bin_day(None, morning)
    s = {"door_entity": "binary_sensor.front", "garage_entity": "cover.garage", "garden_lights_entity": "light.garden"}
    live = compute(s, {"binary_sensor.front": {"state": "on"}, "cover.garage": {"state": "closed"}, "light.garden": {"state": "on"}})
    assert live["house"] == {"bins": None, "bin_today": False, "bin_kinds": [], "door": True, "garage": False, "lights": True}


def test_bins_from_a_calendar_or_sensor():
    import datetime as dt
    from src.live import bins
    cal = {"state": "off", "attributes": {"message": "Recycling and food waste", "all_day": True, "start_time": "2026-11-28 00:00:00", "end_time": "2026-11-29 00:00:00"}}
    # (the evening before: out; the morning of: out, the lorry's about; that evening: back in)
    assert bins(cal, dt.datetime(2026, 11, 27, 12)) == {"out": False, "today": False, "kinds": ["recycling", "food"]}
    assert bins(cal, dt.datetime(2026, 11, 27, 19))["out"] is True and bins(cal, dt.datetime(2026, 11, 27, 19))["today"] is False
    on = dict(cal, state="on")
    assert bins(on, dt.datetime(2026, 11, 28, 8)) == {"out": True, "today": True, "kinds": ["recycling", "food"]}
    assert bins(on, dt.datetime(2026, 11, 28, 20))["out"] is False
    assert bins({"state": "Garden waste in 1 day"}, dt.datetime(2026, 11, 27, 18))["kinds"] == ["garden"]
    assert bins({"state": "Garden waste in 1 day"}, dt.datetime(2026, 11, 27, 18))["out"] is True
    assert bins({"state": "Today: General waste"}, dt.datetime(2026, 11, 27, 7)) == {"out": True, "today": True, "kinds": ["general"]}
    assert bins({"state": "5", "attributes": {"friendly_name": "Bins"}}, dt.datetime(2026, 11, 27, 19))["out"] is False


def test_your_houses_look():
    from src.app_settings import AppSettings
    s = AppSettings()
    assert s.data["look"] == {"door": "", "plate": True, "houses": "brick", "walls": "", "roof": ""}
    s.update({"look": {"door": "Red", "plate": False, "houses": "Stone", "walls": "red_brick", "roof": "slate"}})
    assert s.data["look"] == {"door": "red", "plate": False, "houses": "stone", "walls": "red_brick", "roof": "slate"}
    with pytest.raises(ValueError):
        s.update({"look": {"walls": "gingerbread"}})
    with pytest.raises(ValueError):
        s.update({"look": {"houses": "igloo"}})
    with pytest.raises(ValueError):
        s.update({"look": {"door": "tartan"}})
