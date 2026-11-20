"""Notifications for warnings and errors in the log (src/log_notify.py)."""

import logging

from src.log_notify import GATHER_S, REPEAT_S, LogNotifier, LogNotifyHandler


def test_lines_close_together_come_in_one_notification_once_settled():
    n = LogNotifier()
    n.add(0, logging.WARNING, "src.ha_link", "Couldn't read the saving sessions (calendar.x): timeout")
    n.add(2, logging.ERROR, "src.client", "Connection to the server lost")
    assert n.due(5, "warning") is None  # (still gathering)
    title, text = n.due(2 + GATHER_S, "warning")
    assert title == "OCPP Charge Proxy: errors"
    assert text.splitlines() == ["Couldn't read the saving sessions (calendar.x): timeout", "Error: Connection to the server lost"]
    assert n.due(100, "warning") is None  # (sent: nothing waiting)


def test_errors_only_and_none():
    n = LogNotifier()
    n.add(0, logging.WARNING, "src.x", "A warning")
    assert n.due(60, "error") is None
    n.add(0, logging.ERROR, "src.x", "An error")
    n.add(0, logging.WARNING, "src.x", "A warning")
    assert n.due(60, "error") == ("OCPP Charge Proxy: error", "Error: An error")
    n.add(0, logging.ERROR, "src.x", "Another error")
    assert n.due(60, "none") is None and n.due(120, "error") is None  # (none: dropped, not kept for later)


def test_the_same_problem_isnt_sent_again_for_an_hour():
    n = LogNotifier()
    n.add(0, logging.WARNING, "src.x", "Home Assistant unreachable after 3 tries")
    assert n.due(GATHER_S, "warning")
    n.add(600, logging.WARNING, "src.x", "Home Assistant unreachable after 4 tries")  # (numbers aside, the same)
    assert n.due(600 + GATHER_S, "warning") is None
    n.add(REPEAT_S + 100, logging.WARNING, "src.x", "Home Assistant unreachable after 9 tries")
    assert n.due(REPEAT_S + 100 + GATHER_S, "warning")


def test_some_lines_are_never_sent_and_secrets_are_hidden():
    n = LogNotifier()
    n.add(0, logging.WARNING, "src.ha_link", "Couldn't send a notification through notify.x: boom")
    n.add(0, logging.WARNING, "aiohttp.access", "GET / 500")
    assert n.due(60, "warning") is None
    n.add(0, logging.WARNING, "ocpp", 'receive [2,"x","ChangeConfiguration",{"key":"AuthorizationKey","value":"s3cret"}]')
    _, text = n.due(60, "warning")
    assert "s3cret" not in text


def test_many_lines_are_cut_short():
    n = LogNotifier()
    for k in range(8):
        n.add(0, logging.WARNING, "src.x", f"Problem {chr(97 + k)}")
    _, text = n.due(60, "warning")
    assert len(text.splitlines()) == 6 and text.endswith("…and 3 more (Diagnostics › Debug)")


def test_the_handler_passes_warnings_on():
    n = LogNotifier()
    log = logging.getLogger("test.log_notify")
    h = LogNotifyHandler(n, lambda: 0.0)
    log.addHandler(h)
    try:
        log.info("fine")
        log.warning("Something odd: %s", 42)
    finally:
        log.removeHandler(h)
    assert n.due(60, "warning") == ("OCPP Charge Proxy: warning", "Something odd: 42")
