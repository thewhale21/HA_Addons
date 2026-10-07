import asyncio
import logging

from src.config import Config
from src.debug_tools import DebugTools, install_log_buffer, mask_id, redacted_config
from src.gui_data import MessageLog, SessionLog


def _config(**kw):
    base = dict(server_hostname="ocpp.example.com", chargepoint_id="ABCDEF123456", password="secret",
                charger_model="m", charger_vendor="v", charger_serial="", firmware_version="1",
                initial_energy_wh=0)
    base.update(kw)
    return Config(**base)


def test_config_is_redacted():
    out = redacted_config(_config())
    assert out["password"] == "***" and out["chargepoint_id"] == "…3456"
    assert out["server_hostname"] == "ocpp.example.com"
    assert redacted_config(_config(password=""))["password"] == ""
    assert mask_id("abc") == "***" and mask_id("") == ""


def test_log_buffer_and_level():
    root = logging.getLogger()
    old = root.level
    buf = install_log_buffer("%(levelname)s %(message)s", size=3)
    try:
        root.setLevel(logging.INFO)
        log = logging.getLogger("t")
        for n in range(5):
            log.info("line %d", n)
        log.debug("hidden")
        d = DebugTools(log_buffer=buf, config=_config())
        info = d.info(lines=10)
        assert info["logs"] == ["INFO line 2", "INFO line 3", "INFO line 4"]
        assert info["log_level"] == "info" and info["config"]["password"] == "***"
        assert d.set_log_level("debug") == {"log_level": "debug"}
        log.debug("shown")
        assert d.info()["logs"][-1] == "DEBUG shown"
        try:
            d.set_log_level("loud")
            raise AssertionError("should have refused")
        except ValueError:
            pass
    finally:
        root.removeHandler(buf)
        root.setLevel(old)


def test_clear_sessions_and_messages(tmp_path):
    sessions = SessionLog(str(tmp_path))
    sessions.start(1, "tag", 0, timestamp="2026-10-01T10:00:00+00:00")
    sessions.stop(1000, "Remote", timestamp="2026-10-01T11:00:00+00:00")
    messages = MessageLog(data_dir=str(tmp_path))
    messages.record('[2, "1", "Heartbeat", {}]', incoming=False)
    d = DebugTools(sessions=sessions, messages=messages)
    d.clear("sessions")
    d.clear("messages")
    assert SessionLog(str(tmp_path)).history == []
    assert messages.since(0) == [] and MessageLog(data_dir=str(tmp_path)).since(0) == []
    try:
        d.clear("everything")
        raise AssertionError("should have refused")
    except ValueError:
        pass


def test_drop_checks_seconds():
    seen = []

    async def drop(s):
        seen.append(s)
        return {"seconds": s}

    d = DebugTools(drop=drop)
    assert asyncio.run(d.drop("30")) == {"seconds": 30.0}
    for bad in (-1, 601, "x"):
        try:
            asyncio.run(d.drop(bad))
            raise AssertionError("should have refused")
        except ValueError:
            pass
    assert seen == [30.0]
