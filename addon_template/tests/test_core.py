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
    path.write_text(json.dumps({"example_option": "hi", "something_old": 1}))
    assert load_config(str(path)) == Config(example_option="hi")
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
    assert validate_settings({"example_entity": " sensor.temp "})["example_entity"] == "sensor.temp"
    assert validate_settings({"example_entity": ""})["example_entity"] == ""
    for bad in ({"example_entity": "automation.x"}, {"example_entity": 3}, {"nope": 1}, []):
        with pytest.raises(ValueError):
            validate_settings(bad)


def test_link_follows_changes_and_saves(tmp_path):
    seen = []

    async def changed(entity_id, st):
        seen.append((entity_id, (st or {}).get("state")))

    link = HaLink(str(tmp_path), SharedState(), token="", on_entity_changed=changed)
    assert not link.available and link.watched == []
    _run(link.update_settings({"example_entity": "sensor.temp"}))
    assert link.watched == ["sensor.temp"]
    _run(link.handle_entities_event({"a": {"sensor.temp": {"s": "20.5", "a": {"friendly_name": "Temp", "unit_of_measurement": "°C"}}}}))
    _run(link.handle_entities_event({"c": {"sensor.temp": {"+": {"s": "21"}}}}))
    assert seen[-2:] == [("sensor.temp", "20.5"), ("sensor.temp", "21")]
    snap = link.snapshot()
    assert snap["entities"]["example_entity"] == {"entity_id": "sensor.temp", "name": "Temp", "state": "21", "unit": "°C"}
    assert HaLink(str(tmp_path), SharedState(), token="").settings["example_entity"] == "sensor.temp"  # saved


def test_entity_list_for_the_pickers():
    out = entity_list([
        {"entity_id": "sensor.b", "state": "1", "attributes": {"friendly_name": "B", "unit_of_measurement": "W"}},
        {"entity_id": "automation.x", "state": "on", "attributes": {}},
        {"entity_id": "light.a", "state": "off", "attributes": {"friendly_name": "A"}},
    ])
    assert [e["entity_id"] for e in out] == ["light.a", "sensor.b"]


def test_own_sensors_are_posted_when_they_change():
    pub, state = SensorPublisher(), SharedState(status="Running")
    first = pub.due(state, 0)
    assert {e for e, _, _ in first} == {e for e, _ in SENSORS.values()}
    assert pub.due(state, 10) == []  # nothing changed
    state.ticks = 1
    assert [(e, v) for e, v, _ in pub.due(state, 20)] == [(SENSORS["ticks"][0], "1")]
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
    assert debug.info()["logs"] == ["hello"] and debug.info()["config"] == {"example_option": "hello"}
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
