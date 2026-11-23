"""Notifications by how important they are (src/log_notify.py, Settings › notify level)."""
import asyncio
import logging

from src.app_settings import AppSettings
from src.log_notify import GATHER_S, REPEAT_S, LogNotifier, LogNotifyHandler, redact, wanted


def test_what_each_level_sends():
    assert [lv for lv in ("info", "warning", "error") if wanted("info", lv)] == ["info", "warning", "error"]
    assert [lv for lv in ("info", "warning", "error") if wanted("warning", lv)] == ["warning", "error"]
    assert [lv for lv in ("info", "warning", "error") if wanted("error", lv)] == ["error"]
    assert not any(wanted(s, lv) for s in ("none", None, "x") for lv in ("info", "warning", "error"))


def test_log_lines_gathered_once_an_hour_and_by_level():
    n = LogNotifier()
    n.add(100, logging.WARNING, "src.manager", "Couldn't read the SoC: timeout 5")
    n.add(103, logging.ERROR, "src.ha_link", "Lost Home Assistant")
    n.add(104, logging.WARNING, "aiohttp.access", "ignored")
    assert n.due(105, "warning") is None  # (still gathering)
    title, msg = n.due(104 + GATHER_S, "warning")
    assert title == "EVDC: errors" and msg.splitlines() == ["Couldn't read the SoC: timeout 5", "Error: Lost Home Assistant"]
    n.add(200, logging.WARNING, "src.manager", "Couldn't read the SoC: timeout 9")  # (the same, numbers aside)
    assert n.due(200 + GATHER_S, "warning") is None
    n.add(300, logging.WARNING, "src.manager", "Something else")
    assert n.due(300 + GATHER_S, "error") is None  # (errors only: a warning isn't sent)
    n.add(200 + REPEAT_S + 1, logging.WARNING, "src.manager", "Couldn't read the SoC: timeout 7")
    assert n.due(200 + REPEAT_S + 1 + GATHER_S, "info")[1] == "Couldn't read the SoC: timeout 7"
    n.add(5000, logging.ERROR, "src.x", "Boom")
    assert n.due(5000 + GATHER_S, "none") is None


def test_handler_and_secrets():
    n = LogNotifier()
    h = LogNotifyHandler(n, lambda: 10.0)
    log = logging.getLogger("t.notify")
    log.addHandler(h)
    log.warning("Login failed: password=hunter2 token: abc")
    log.info("not sent")
    log.removeHandler(h)
    assert n.due(10 + GATHER_S, "warning")[1] == "Login failed: password=*** token: ***"
    assert "hunter2" not in redact("api_key=hunter2")


def test_the_notify_level_setting(tmp_path):
    s = AppSettings(str(tmp_path))
    assert s.data["notify_level"] == "info"  # (as before: starts and stops too)
    s.update({"notify_level": "warning"})
    assert AppSettings(str(tmp_path)).data["notify_level"] == "warning"
    for bad in ("debug", "", None):
        try:
            s.update({"notify_level": bad})
        except ValueError:
            continue
        raise AssertionError(bad)


def test_starts_and_stops_are_info():
    """A start or stop isn't sent with Warnings and errors; a charger alarm is (the Runner's notify)."""
    import pytest
    pytest.importorskip("aiohttp")
    from src.__main__ import Runner

    sent = []

    class Link:
        async def call_service(self, domain, service, data=None, target=None):
            sent.append((service, data["title"]))

    class Settings:
        data = {"notify_service": "notify.mobile_app_phone", "notify_level": "warning"}

    r = Runner.__new__(Runner)
    r.link, r.settings = Link(), Settings()
    asyncio.run(r.notify("V2X: charger started", "because"))
    asyncio.run(r.notify("EVDC: charger alarm", "alarm", "error"))
    asyncio.run(r.notify("EVDC: test", "test", force=True))
    assert sent == [("mobile_app_phone", "EVDC: charger alarm"), ("mobile_app_phone", "EVDC: test")]
