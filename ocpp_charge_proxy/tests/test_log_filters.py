import json
import logging

from src.log_filters import DemoteRoutineMessages


def _record(direction: str, frame: list) -> logging.LogRecord:
    # Same shape as the ocpp library's log calls: "%s: send %s" / "%s: receive message %s"
    fmt = "%s: send %s" if direction == "send" else "%s: receive message %s"
    return logging.LogRecord("ocpp", logging.INFO, __file__, 1, fmt, ("CP1", json.dumps(frame)), None)


def test_heartbeat_and_reply_hidden_at_info(monkeypatch):
    monkeypatch.setattr(logging.getLogger(), "level", logging.INFO)
    f = DemoteRoutineMessages()
    assert f.filter(_record("send", [2, "hb1", "Heartbeat", {}])) is False
    assert f.filter(_record("receive", [3, "hb1", {"currentTime": "2026-10-02T12:00:00Z"}])) is False


def test_heartbeat_shown_as_debug_when_debugging(monkeypatch):
    monkeypatch.setattr(logging.getLogger(), "level", logging.DEBUG)
    f = DemoteRoutineMessages()
    rec = _record("send", [2, "hb2", "Heartbeat", {}])
    assert f.filter(rec) is True
    assert rec.levelname == "DEBUG"


def test_other_messages_untouched(monkeypatch):
    monkeypatch.setattr(logging.getLogger(), "level", logging.INFO)
    f = DemoteRoutineMessages()
    for rec in (
        _record("send", [2, "s1", "StatusNotification", {"connectorId": 1}]),
        _record("receive", [3, "s1", {}]),  # reply to a non-heartbeat
        _record("receive", [2, "r1", "RemoteStartTransaction", {"idTag": "x"}]),
        _record("send", [3, "b1", {"currentTime": "t", "interval": 10, "status": "Accepted"}]),
    ):
        assert f.filter(rec) is True
        assert rec.levelname == "INFO"


def test_unparseable_lines_untouched(monkeypatch):
    monkeypatch.setattr(logging.getLogger(), "level", logging.INFO)
    f = DemoteRoutineMessages()
    rec = logging.LogRecord("ocpp", logging.INFO, __file__, 1, "something else", (), None)
    assert f.filter(rec) is True


def _reading(uid, context="Sample.Periodic", transaction_id=None):
    payload = {"connectorId": 1, "meterValue": [{"timestamp": "t", "sampledValue": [
        {"measurand": "Energy.Active.Import.Register", "value": "1", "context": context},
    ]}]}
    if transaction_id is not None:
        payload["transactionId"] = transaction_id
    return [2, uid, "MeterValues", payload]


def test_periodic_meter_values_hidden_at_info(monkeypatch):
    """Idle and in-session periodic readings, and their replies."""
    monkeypatch.setattr(logging.getLogger(), "level", logging.INFO)
    f = DemoteRoutineMessages()
    for uid, frame in (("idle", _reading("idle")), ("tx", _reading("tx", transaction_id=1))):
        assert f.filter(_record("send", frame)) is False
        assert f.filter(_record("receive", [3, uid, {}])) is False


def test_clock_aligned_meter_values_shown_only_in_a_session(monkeypatch):
    monkeypatch.setattr(logging.getLogger(), "level", logging.INFO)
    f = DemoteRoutineMessages()
    # In a session: shown
    rec = _record("send", _reading("txclk", context="Sample.Clock", transaction_id=1))
    assert f.filter(rec) is True and rec.levelname == "INFO"
    reply = _record("receive", [3, "txclk", {}])
    assert f.filter(reply) is True and reply.levelname == "INFO"
    # Idle (every 15 min, 0 W): hidden, reply too
    assert f.filter(_record("send", _reading("clk", context="Sample.Clock"))) is False
    assert f.filter(_record("receive", [3, "clk", {}])) is False


# --- 2.1.6: the web page's requests ---

from src.log_filters import DemoteWebPageRequests as _DemoteWeb


def _access(line):
    return logging.LogRecord("aiohttp.access", logging.INFO, __file__, 1, line, (), None)


def test_web_page_gets_hidden_at_info():
    f = _DemoteWeb()
    root = logging.getLogger()
    old = root.level
    root.setLevel(logging.INFO)
    try:
        assert not f.filter(_access('172.30.32.2 [x] "GET /api/state HTTP/1.1" 200 4893 "-" "Mozilla"'))
        assert not f.filter(_access('172.30.32.2 [x] "GET / HTTP/1.1" 304 180 "-" "Mozilla"'))
        assert f.filter(_access('172.30.32.2 [x] "POST /api/plug HTTP/1.1" 200 175 "-" "Mozilla"'))
        assert f.filter(_access('172.30.32.2 [x] "GET /api/state HTTP/1.1" 500 10 "-" "Mozilla"'))
    finally:
        root.setLevel(old)


def test_web_page_gets_shown_at_debug():
    f = _DemoteWeb()
    root = logging.getLogger()
    old = root.level
    root.setLevel(logging.DEBUG)
    try:
        rec = _access('172.30.32.2 [x] "GET /api/state HTTP/1.1" 200 4893 "-" "Mozilla"')
        assert f.filter(rec) and rec.levelno == logging.DEBUG
    finally:
        root.setLevel(old)
