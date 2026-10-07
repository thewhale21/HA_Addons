import datetime
import json

from src.shared_state import SharedState
from src.traffic import RECENT_COMMANDS, TrafficRecorder, summarise_command


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _recorder():
    state, clock = SharedState(), _Clock()
    return TrafficRecorder(state, lambda: 10, clock=clock), state, clock


def _send(rec, frame):
    rec.record(json.dumps(frame), incoming=False)


def _recv(rec, frame):
    rec.record(json.dumps(frame), incoming=True)


def test_heartbeat_round_trip_and_clock_offset():
    rec, state, clock = _recorder()
    _send(rec, [2, "hb1", "Heartbeat", {}])
    assert state.last_heartbeat is None  # not answered yet
    assert state.last_command_sent is None  # heartbeats aren't commands
    clock.t += 0.018
    ahead = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=2))
    _recv(rec, [3, "hb1", {"currentTime": ahead.strftime("%Y-%m-%dT%H:%M:%SZ")}])
    hb = state.last_heartbeat
    assert hb["round_trip_ms"] == 18
    assert hb["interval_s"] == 10
    assert 0.5 <= hb["clock_offset_s"] <= 3.5  # server ~2s ahead
    assert hb["timestamp"].endswith("Z")


def test_unanswered_or_errored_heartbeat_leaves_last_one():
    rec, state, clock = _recorder()
    _send(rec, [2, "hb1", "Heartbeat", {}])
    _recv(rec, [3, "hb1", {"currentTime": "2026-10-02T12:00:00Z"}])
    first = state.last_heartbeat
    _send(rec, [2, "hb2", "Heartbeat", {}])
    _recv(rec, [4, "hb2", "InternalError", "oops", {}])
    assert state.last_heartbeat == first


def test_command_round_trip_and_summary():
    rec, state, clock = _recorder()
    _recv(rec, [2, "c1", "ChangeConfiguration", {"key": "chargingALimitConn1", "value": "32"}])
    clock.t += 0.002
    _send(rec, [3, "c1", {"status": "Accepted"}])
    last = state.last_command_received
    assert last["summary"] == "chargingALimitConn1 = 32"
    assert last["status"] == "Accepted"
    assert last["round_trip_ms"] == 2
    assert last["message_id"] == "c1"


def test_recent_newest_first_capped_and_late_reply_updates_status():
    rec, state, clock = _recorder()
    _send(rec, [2, "s0", "StatusNotification", {"connectorId": 1, "status": "Preparing"}])
    for i in range(1, RECENT_COMMANDS + 3):
        _send(rec, [2, f"s{i}", "StatusNotification", {"connectorId": 1, "status": "Charging"}])
    recent = state.last_command_sent["recent"]
    assert len(recent) == RECENT_COMMANDS
    assert recent[0]["summary"] == "connector 1: Charging"
    # A reply to an older (still listed) command updates its status in "recent"
    _recv(rec, [3, "s5", {}])
    statuses = [r["status"] for r in state.last_command_sent["recent"]]
    assert statuses.count("OK") == 1
    assert state.last_command_sent["status"] is None  # the latest is still waiting


def test_summaries():
    profile = {
        "chargingProfilePurpose": "TxProfile",
        "chargingSchedule": {"chargingRateUnit": "A", "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 32.0}]},
    }
    assert summarise_command("RemoteStartTransaction", {"idTag": "abc", "chargingProfile": profile}) == "idTag abc, TxProfile 32 A"
    assert summarise_command("StopTransaction", {"transactionId": 1, "meterStop": 6612523, "reason": "EVDisconnected"}) == \
        "transaction 1, meterStop 6612523 Wh, EVDisconnected"
    assert summarise_command("GetConfiguration", {"key": []}) == "all keys"
    assert summarise_command("GetConfiguration", {"key": ["V2GCapabilities"]}) == "V2GCapabilities"
    assert summarise_command("TriggerMessage", {"requestedMessage": "StatusNotification"}) == "StatusNotification"
    assert summarise_command("SendLocalList", {"updateType": "Full", "listVersion": 1, "localAuthorizationList": [{}]}) == "Full v1, 1 tag(s)"
    assert summarise_command("Unknown", {"x": 1}) == ""
    assert summarise_command("ChangeConfiguration", "not a dict") == ""
