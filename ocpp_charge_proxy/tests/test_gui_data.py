import json

from src.gui_data import Health, MessageLog, PowerHistory, SessionLog, daily_from_sessions, remove_old_history_files
from src.shared_state import SharedState


def test_message_log_pairs_replies_with_their_call():
    log = MessageLog()
    log.record(json.dumps([2, "a1", "ChangeConfiguration", {"key": "minSoC", "value": "25"}]), incoming=True)
    log.record(json.dumps([3, "a1", {"status": "Accepted"}]), incoming=False)
    log.record(json.dumps([4, "b2", "NotImplemented", "nope", {}]), incoming=True)
    entries = log.since(0)
    assert [e["type"] for e in entries] == ["call", "result", "error"]
    assert entries[0]["direction"] == "received" and entries[0]["summary"] == "minSoC = 25"
    assert entries[1]["action"] == "ChangeConfiguration" and entries[1]["direction"] == "sent"
    assert entries[2]["payload"]["errorCode"] == "NotImplemented"
    assert [e["seq"] for e in log.since(1)] == [2, 3]


def test_message_log_keeps_the_newest_and_ignores_junk():
    log = MessageLog(size=3)
    for i in range(5):
        log.record([2, str(i), "Heartbeat", {}], incoming=False)
    log.record("not json", incoming=True)
    assert [e["message_id"] for e in log.since(0)] == ["2", "3", "4"]
    assert log.last_seq == 5


def test_sessions_survive_a_restart(tmp_path):
    log = SessionLog(str(tmp_path))
    log.start(1, "TAG", 1000, "2026-10-02T15:00:00Z")
    log.sample(1.2)
    log.sample(1.4)
    log.stop(3500, "Remote", "2026-10-02T16:30:00Z")
    again = SessionLog(str(tmp_path))
    assert again.current is None
    s = again.history[0]
    assert s["energy_kwh"] == 2.5 and s["duration_s"] == 5400
    assert s["peak_power_kw"] == 1.4 and s["reason"] == "Remote"


def test_running_session_saved_and_snapshot_live(tmp_path):
    log = SessionLog(str(tmp_path))
    log.start(-5, "TAG", 1000)
    log.remap_transaction_id(-5, 7)
    again = SessionLog(str(tmp_path))
    assert again.current["transaction_id"] == 7
    snap = again.snapshot(energy_register_wh=1750)
    assert snap["current"]["energy_kwh"] == 0.75 and snap["current"]["duration_s"] >= 0


def test_history_is_capped(tmp_path):
    log = SessionLog(str(tmp_path), size=2)
    for i in range(3):
        log.start(i, "T", 0)
        log.stop(1000, "Remote")
    assert [s["transaction_id"] for s in log.history] == [2, 1]


def test_session_log_without_disk():
    log = SessionLog(None)
    log.start(1, "T", 0)
    log.stop(10, None)
    assert log.history[0]["reason"] is None


def test_power_history_since():
    now = [100.0]
    history = PowerHistory(size=3, clock=lambda: now[0])
    state = SharedState(power_kw=1.37, current_a=6.0, soc_percent=55)
    for _ in range(4):
        history.sample(state)
        now[0] += 10
    assert [s["t"] for s in history.since(0)] == [110.0, 120.0, 130.0]
    assert [s["t"] for s in history.since(115)] == [120.0, 130.0]
    assert history.since(0)[0]["soc"] == 55


def test_health_counts_reconnects():
    now = [1000.0]
    health = Health(version="1.1.0", clock=lambda: now[0])
    health.disconnected("refused")  # before ever connecting: not a drop
    health.connected()
    now[0] += 60
    health.disconnected("timeout")
    health.connected()
    now[0] += 5
    snap = health.snapshot()
    assert snap["version"] == "1.1.0" and snap["uptime_s"] == 65
    assert snap["reconnects"] == 1 and snap["disconnects"] == 1
    assert snap["connected_for_s"] == 5 and snap["last_disconnect"]["reason"] == "timeout"


def test_plug_in_without_session_recorded(tmp_path):
    log = SessionLog(str(tmp_path))
    log.plugged(True, "schedule", "2026-10-02T22:30:00Z")
    assert SessionLog(str(tmp_path)).plug["plugged_by"] == "schedule"  # survives a restart
    log.plugged(False, "auto re-plug", "2026-10-02T22:40:00Z")
    entry = log.history[0]
    assert entry["type"] == "no_session" and entry["reason"] == "replugged"
    assert entry["duration_s"] == 600 and entry["plugged_by"] == "schedule"
    assert entry["unplugged_by"] == "auto re-plug" and log.plug is None


def test_plug_in_that_gets_a_session_is_not_recorded_as_failed(tmp_path):
    log = SessionLog(str(tmp_path))
    log.plugged(True, "web page")
    log.start(1, "TAG", 0)
    log.stop(1000, "Remote")
    log.plugged(False, "web page")
    assert [e.get("type") for e in log.history] == [None]


def test_no_session_entries_kept_separately(tmp_path):
    log = SessionLog(str(tmp_path), size=2)
    log.start(1, "T", 0)
    log.stop(10, "Remote")
    for _ in range(3):
        log.plugged(True, "web page")
        log.plugged(False, "web page")
    kinds = [e.get("type", "session") for e in log.history]
    assert kinds.count("no_session") == 2 and kinds.count("session") == 1
    snap = log.snapshot()
    assert snap["waiting"] is None
    log.plugged(True, "Home Assistant")
    assert log.snapshot()["waiting"]["plugged_by"] == "Home Assistant"


def test_message_log_kept_across_restarts(tmp_path):
    log = MessageLog(data_dir=str(tmp_path))
    log.record('[2,"a","Heartbeat",{}]', incoming=False)
    log.record('[3,"a",{"currentTime":"2026-10-02T15:00:00Z"}]', incoming=True)
    log.save()
    again = MessageLog(data_dir=str(tmp_path))
    entries = again.since(0)
    assert [e["type"] for e in entries] == ["call", "result", "restart"]
    assert again.last_seq == 3
    again.record('[2,"b","Heartbeat",{}]', incoming=False)
    assert again.since(3)[0]["seq"] == 4  # numbering carries on


def test_message_log_saves_only_when_changed(tmp_path):
    log = MessageLog(data_dir=str(tmp_path))
    log.save()
    assert not (tmp_path / "messages.json").exists()  # nothing to save
    log.record('[2,"a","Heartbeat",{}]', incoming=False)
    log.save()
    assert (tmp_path / "messages.json").exists()
    assert MessageLog(data_dir=str(tmp_path / "empty")).since(0) == []


def test_power_history_is_memory_only_and_capped():
    now = [10_000.0]
    history = PowerHistory(clock=lambda: now[0])
    for _ in range(400):  # more than an hour of 10 s samples
        history.sample(SharedState(power_kw=1.4, state="Charging"))
        now[0] += 10
    assert len(history.since(0)) == 360
    assert history.since(0)[-1]["state"] == "Charging"


def test_daily_from_sessions_and_metered():
    import datetime
    today = datetime.date.today()
    start = datetime.datetime.combine(today, datetime.time(12, 0)).astimezone().isoformat()
    sessions = [{"start": start, "energy_kwh": 0.52}, {"start": start, "type": "no_session"}]
    days = daily_from_sessions(3, sessions, today)
    assert [d["kwh"] for d in days] == [0.0, 0.0, 0.52]
    yesterday = (today - datetime.timedelta(days=1)).isoformat()
    days = daily_from_sessions(3, sessions, today, {yesterday: 7.5, today.isoformat(): 0.3})
    assert [d["kwh"] for d in days] == [0.0, 7.5, 0.52]  # the larger figure for today


def test_old_history_files_removed(tmp_path):
    for name in ("history.json", "history_long.json.bak", "daily_energy.json", "sessions.json"):
        (tmp_path / name).write_text("[]")
    remove_old_history_files(str(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sessions.json"]
    remove_old_history_files(None)  # no data dir: nothing to do


def test_session_marked_against_supplier_slots(tmp_path):
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    iso = lambda m: (now + dt.timedelta(minutes=m)).isoformat()
    log = SessionLog(str(tmp_path))
    log.start(1, "tag", 0, timestamp=iso(-180))
    log.stop(5000, "Remote", timestamp=iso(-120))   # 60 min, all in a slot
    log.start(1, "tag", 5000, timestamp=iso(-100))
    log.stop(9000, "Remote", timestamp=iso(-40))    # 60 min, half in a slot
    periods = [{"start": iso(-190), "end": iso(-110)}, {"start": iso(-70), "end": iso(-10)}]
    assert log.mark_supplier(periods, "Octopus Energy")
    newer, older = log.history[0], log.history[1]
    assert older["supplier_s"] == 3600 and older["supplier"] == "Octopus Energy"
    assert newer["supplier_s"] == 1800
    # finished slots dropping out of the list don't lower it; kept across restarts
    assert not log.mark_supplier([{"start": iso(-70), "end": iso(-60)}], "Octopus Energy")
    again = SessionLog(str(tmp_path))
    assert again.history[1]["supplier_s"] == 3600


def test_plugged_in_stretches_are_kept(tmp_path):
    log = SessionLog(str(tmp_path))
    log.plugged(True, "schedule", timestamp="2026-10-04T15:30:00+00:00")
    log.plugged(False, "schedule", timestamp="2026-10-04T21:30:00+00:00")
    log.plugged(True, "charge now", timestamp="2026-10-05T06:03:00+00:00")
    snap = SessionLog(str(tmp_path)).snapshot()  # kept across restarts
    assert snap["plugged"][0] == {"start": "2026-10-05T06:03:00+00:00", "by": "charge now", "end": None}
    assert snap["plugged"][1] == {"start": "2026-10-04T15:30:00+00:00", "end": "2026-10-04T21:30:00+00:00",
                                  "by": "schedule", "unplugged_by": "schedule"}
    assert snap["plugged_since"]
