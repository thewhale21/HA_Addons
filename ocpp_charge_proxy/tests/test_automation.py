import asyncio
import datetime
import json

import pytest

from src.automation import Automation, ReplugOptions, automation_loop, validate_entry
from src.shared_state import SharedState

TZ = datetime.timezone.utc


class Clock:
    """Fake local time (UTC here) and epoch clock moving together."""

    def __init__(self, start: datetime.datetime):
        self.dt = start

    def now(self):
        return self.dt

    def epoch(self):
        return self.dt.timestamp()

    def advance(self, **kw):
        self.dt += datetime.timedelta(**kw)


def _automation(tmp_path=None, options=ReplugOptions(), start=datetime.datetime(2026, 10, 5, 23, 0, tzinfo=TZ)):
    clock = Clock(start)  # Monday 5 Oct 2026
    a = Automation(str(tmp_path) if tmp_path else None, options, now=clock.now, clock=clock.epoch,
                   localize=lambda naive: naive.replace(tzinfo=TZ))
    return a, clock


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --- entries -----------------------------------------------------------------


def test_validate_entry():
    e = validate_entry({"time": "7:05", "action": "unplug", "days": [4, 0, 0]})
    assert e["time"] == "07:05" and e["days"] == [0, 4] and e["enabled"] is True and e["id"]
    assert validate_entry({"time": "23:30", "action": "plug"})["days"] == list(range(7))
    for bad in ({"time": "24:00", "action": "plug"}, {"time": "x", "action": "plug"},
                {"time": "10:00", "action": "toggle"}, {"time": "10:00", "action": "plug", "days": []},
                {"time": "10:00", "action": "plug", "days": [7]}):
        with pytest.raises(ValueError):
            validate_entry(bad)


# --- schedule ----------------------------------------------------------------


def test_due_fires_once_at_the_time():
    a, clock = _automation()
    a.set_schedule(enabled=True, entries=[
        {"time": "23:30", "action": "plug", "days": [0, 1, 2, 3, 4]},
        {"time": "07:00", "action": "unplug"},
    ])
    assert a.due() == []  # first check only sets the starting point
    clock.advance(minutes=29)
    assert a.due() == []
    clock.advance(seconds=75)  # 23:30:15
    assert [e["action"] for e in a.due()] == ["plug"]
    clock.advance(seconds=15)
    assert a.due() == []  # not again
    clock.advance(hours=7, minutes=29)  # Tue 06:59:30
    assert a.due() == []
    clock.advance(seconds=45)  # 07:00:15
    assert [e["action"] for e in a.due()] == ["unplug"]


def test_schedule_respects_days_and_disabled():
    a, clock = _automation(start=datetime.datetime(2026, 10, 10, 23, 29, tzinfo=TZ))  # Saturday
    a.set_schedule(enabled=True, entries=[{"time": "23:30", "action": "plug", "days": [0, 1, 2, 3, 4]}])
    a.due()
    clock.advance(minutes=2)
    assert a.due() == []  # weekdays only
    a.set_schedule(enabled=False)
    assert a.next_action() is None


def test_missed_times_are_not_caught_up_after_a_long_gap():
    a, clock = _automation()
    a.set_schedule(enabled=True, entries=[{"time": "23:30", "action": "plug"}])
    a.due()
    clock.advance(hours=2)  # stopped / asleep through 23:30
    assert a.due() == []


def test_next_action():
    a, clock = _automation()  # Monday 23:00
    a.set_schedule(enabled=True, entries=[
        {"time": "07:00", "action": "unplug", "days": [1]},
        {"time": "23:30", "action": "plug", "days": [0]},
        {"time": "22:00", "action": "plug", "enabled": False},
    ])
    nxt = a.next_action()
    assert nxt["action"] == "plug" and nxt["time"].startswith("2026-10-05T23:30")
    clock.advance(minutes=31)
    assert a.next_action()["time"].startswith("2026-10-06T07:00")


def test_schedule_saved(tmp_path):
    a, _ = _automation(tmp_path)
    a.set_schedule(enabled=True, entries=[{"time": "23:30", "action": "plug"}])
    b, _ = _automation(tmp_path)
    assert b.schedule_enabled is True and b.entries[0]["time"] == "23:30"


def test_bad_schedule_rejected_and_unchanged(tmp_path):
    a, _ = _automation(tmp_path)
    a.set_schedule(entries=[{"time": "23:30", "action": "plug"}])
    with pytest.raises(ValueError):
        a.set_schedule(entries=[{"time": "99:00", "action": "plug"}])
    assert len(a.entries) == 1


# --- re-plug -----------------------------------------------------------------


def test_replug_after_wait_up_to_the_limit():
    a, clock = _automation(options=ReplugOptions(True, 10, 2))
    assert not a.replug_due(True, False, True)  # starts the wait
    clock.advance(minutes=9)
    assert not a.replug_due(True, False, True)
    assert a.replug_status()["status"] == "waiting"
    clock.advance(minutes=1)
    assert a.replug_due(True, False, True)

    calls = []

    async def unplug(source=None):
        calls.append("unplug")

    async def plug(source=None):
        calls.append("plug")

    _run(a.run_replug(unplug, plug, wait_s=0))
    assert calls == ["unplug", "plug"] and a.attempts_used == 1
    assert not a.replug_due(True, False, True)  # waits again from the re-plug
    clock.advance(minutes=10)
    assert a.replug_due(True, False, True)
    _run(a.run_replug(unplug, plug, wait_s=0))
    clock.advance(minutes=10)
    assert not a.replug_due(True, False, True)  # 2 tries used: give up
    assert a.replug_status()["status"] == "gave_up"


def test_replug_resets_when_session_starts_or_unplugged():
    a, clock = _automation()
    a.replug_due(True, False, True)
    a.attempts_used = 3
    a.gave_up = True
    assert not a.replug_due(True, True, True)  # session started
    assert a.attempts_used == 0 and not a.gave_up and a.replug_status()["status"] == "idle"
    a.attempts_used = 2
    assert not a.replug_due(False, False, True)  # unplugged
    assert a.attempts_used == 0


def test_replug_waits_only_while_online_and_enabled():
    a, clock = _automation()
    a.replug_due(True, False, True)
    clock.advance(minutes=9)
    assert not a.replug_due(True, False, False)  # offline: the wait restarts
    clock.advance(minutes=5)
    assert not a.replug_due(True, False, True)
    clock.advance(minutes=10)
    assert a.replug_due(True, False, True)
    a.set_replug(enabled=False)
    assert not a.replug_due(True, False, True)
    assert a.replug_status()["status"] == "off"


def test_replug_settings_saved_win_over_defaults(tmp_path):
    a, _ = _automation(tmp_path, ReplugOptions(True, 10, 3))
    assert a.replug["after_min"] == 10  # nothing saved: the defaults
    a.set_replug(after_min=15, attempts=5)
    b, _ = _automation(tmp_path, ReplugOptions(True, 20, 3))
    assert (b.replug["after_min"], b.replug["attempts"]) == (15, 5)


def test_replug_settings_validated():
    a, _ = _automation()
    for bad in ({"after_min": 0}, {"attempts": -1}, {"after_min": "x"}):
        with pytest.raises(ValueError):
            a.set_replug(**bad)


# --- the loop ----------------------------------------------------------------


def test_loop_runs_schedule_and_publishes():
    a, clock = _automation()
    # (an unplug too, so 23:00 isn't inside a plugged-in stretch at start-up)
    a.set_schedule(enabled=True, entries=[{"time": "23:30", "action": "plug"}, {"time": "07:00", "action": "unplug"}])
    state = SharedState(connected_to_server=True)
    calls = []

    async def plug(source=None):
        calls.append("plug")
        state.plugged_in = True
        state.state = "Preparing"

    async def unplug(source=None):
        calls.append("unplug")

    async def scenario():
        task = asyncio.ensure_future(automation_loop(a, state, plug, unplug, tick_s=0.01))
        await asyncio.sleep(0.03)
        clock.advance(minutes=30)
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    _run(scenario())
    assert calls == ["plug"]
    assert state.schedule_enabled is True
    assert state.replug["status"] == "waiting"
    assert state.schedule_next["action"] == "unplug"  # 07:00 next
    json.dumps(state.to_dict())  # serialisable for the API


def test_no_replug_while_supplier_has_a_slot_planned():
    a, clock = _automation(options=ReplugOptions(True, 10, 3))
    assert not a.replug_due(True, False, True, scheduled=False)  # plugged in, nothing planned yet
    clock.advance(minutes=5)
    # Octopus plans a slot for tonight: no re-plug, however long until it starts
    assert not a.replug_due(True, False, True, scheduled=True)
    assert a.replug_status()["status"] == "scheduled"
    clock.advance(hours=3)
    assert not a.replug_due(True, False, True, scheduled=True)
    # The plan is dropped: the wait starts again from now
    assert not a.replug_due(True, False, True, scheduled=False)
    assert a.replug_status()["status"] == "waiting"
    clock.advance(minutes=10)
    assert a.replug_due(True, False, True, scheduled=False)


def test_replug_without_supplier_info_waits_for_a_session():
    a, clock = _automation(options=ReplugOptions(True, 10, 3))
    a.replug_due(True, False, True, scheduled=None)
    clock.advance(minutes=10)
    assert a.replug_due(True, False, True, scheduled=None)


def test_automation_loop_publishes_scheduled():
    from src.automation import automation_loop
    from src.shared_state import SharedState, display_status
    a, clock = _automation()
    state = SharedState(state="Preparing", plugged_in=True, connected_to_server=True)

    async def noop(source=None):
        pass

    async def one_tick():
        task = asyncio.ensure_future(automation_loop(a, state, noop, noop, tick_s=60, scheduled=lambda: True))
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    _run(one_tick())
    assert state.scheduled is True and display_status(state) == "Scheduled"
    assert state.replug["status"] == "scheduled"
    state.state = "Charging"
    assert display_status(state) == "Charging"


def test_octopus_six_hours_a_day():
    every = list(range(7))
    six = [{"time": "23:30", "action": "plug", "days": every}, {"time": "05:30", "action": "unplug", "days": every}]
    seven = [{"time": "23:30", "action": "plug", "days": every}, {"time": "06:30", "action": "unplug", "days": every}]
    a, clock = _automation()
    a.set_schedule(entries=seven, daily_cap_min=360)  # ready time off: no limit
    a.set_schedule(entries=six, ready_time=True, daily_cap_min=360)  # exactly 6 hours: fine
    try:
        a.set_schedule(entries=seven, daily_cap_min=360, provider="Octopus Energy")
        raise AssertionError("should have refused")
    except ValueError as err:
        assert "6 hours" in str(err) and "7h 00m" in str(err)
    assert a.entries[1]["time"] == "05:30"  # unchanged
    # Two 4-hour stretches 12 hours apart are 8 hours in 24
    split = [{"time": "00:00", "action": "plug", "days": every}, {"time": "04:00", "action": "unplug", "days": every},
             {"time": "12:00", "action": "plug", "days": every}, {"time": "16:00", "action": "unplug", "days": every}]
    try:
        a.set_schedule(entries=split, daily_cap_min=360)
        raise AssertionError("should have refused")
    except ValueError as err:
        assert "8h 00m" in str(err)
    a.set_schedule(entries=split)  # no cap (not Octopus): fine
    a.set_schedule(ready_time=False)
    a.set_schedule(entries=seven, daily_cap_min=360)  # ready time off again: fine
    try:
        a.set_schedule(ready_time=True, daily_cap_min=360)  # can't turn it on while over
        raise AssertionError("should have refused")
    except ValueError:
        assert a.ready_time is False
    a.set_schedule(enabled=False, daily_cap_min=360)  # switching off is always allowed
    assert a.schedule_enabled is False


def test_in_plug_window():
    every = list(range(7))
    a, clock = _automation(start=datetime.datetime(2026, 10, 6, 2, 0, tzinfo=TZ))  # Tuesday 02:00
    a.set_schedule(enabled=True, entries=[
        {"time": "23:30", "action": "plug", "days": every}, {"time": "07:00", "action": "unplug", "days": every}])
    assert a.in_plug_window().strftime("%a %H:%M") == "Mon 23:30"
    clock.advance(hours=6)  # 08:00: unplugged by then
    assert a.in_plug_window() is None
    a.set_schedule(enabled=False)
    clock.advance(hours=16)  # 00:00, inside again, but the schedule is off
    assert a.in_plug_window() is None


def test_startup_plugs_in_inside_a_scheduled_stretch():
    from src.automation import automation_loop
    from src.shared_state import SharedState
    every = list(range(7))

    def run(plugged_in, ready_results):
        a, clock = _automation(start=datetime.datetime(2026, 10, 6, 2, 0, tzinfo=TZ))
        a.set_schedule(enabled=True, ready_time=True, entries=[
            {"time": "23:30", "action": "plug", "days": every}, {"time": "07:00", "action": "unplug", "days": every}])
        state = SharedState(plugged_in=plugged_in)
        calls, asked = [], []

        async def plug(source=None):
            calls.append(("plug", source))
            state.plugged_in = True

        async def unplug(source=None):
            calls.append(("unplug", source))

        async def set_ready(unplug_at):
            asked.append(unplug_at)
            return ready_results.pop(0) if ready_results else {"ready": "07:00"}

        async def ticks():
            task = asyncio.ensure_future(automation_loop(a, state, plug, unplug, tick_s=0.01, set_ready_time=set_ready))
            await asyncio.sleep(0.1)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        _run(ticks())
        return a, calls, asked

    a, calls, asked = run(False, [{"error": "Not connected to Home Assistant"}])
    assert calls == [("plug", "schedule")]
    assert len(asked) == 2 and a.ready_status["ready"] == "07:00"  # tried again once HA was there
    assert a.last_run["startup"] is True
    _, calls, asked = run(True, [])  # already plugged in: nothing to do
    assert calls == [] and asked == []


# --- 2.9.0: one-off times and skips ---------------------------------------------


def test_one_off_time_runs_once_and_is_removed(tmp_path):
    a, clock = _automation(tmp_path)  # Monday 5 Oct 2026, 23:00
    a.set_schedule(enabled=True, entries=[{"time": "23:30", "action": "plug", "date": "2026-10-06"}])
    assert a.entries[0]["days"] == [1] and a.entries[0]["date"] == "2026-10-06"
    a.due()
    clock.advance(minutes=31)  # Monday 23:31: not today
    assert a.due() == []
    assert a.next_action()["time"].startswith("2026-10-06T23:30")
    clock.advance(days=1)  # Tuesday 23:31
    assert [e["action"] for e in a.due()] == ["plug"]
    clock.advance(days=13)  # kept for the Sessions tab...
    a.due()
    assert len(a.entries) == 1
    clock.advance(days=2)  # ... 14 days, then gone (and saved)
    a.due()
    assert a.entries == [] and Automation(str(tmp_path)).entries == []
    try:
        validate_entry({"time": "07:00", "action": "unplug", "date": "06/10/2026"})
        raise AssertionError("should have refused")
    except ValueError:
        pass


def test_skip_one_time(tmp_path):
    every = list(range(7))
    a, clock = _automation(tmp_path)  # Monday 23:00
    a.set_schedule(enabled=True, entries=[
        {"time": "23:30", "action": "plug", "days": every}, {"time": "07:00", "action": "unplug", "days": every}])
    plug_id = a.entries[0]["id"]
    a.set_skip(plug_id, "2026-10-05")  # tonight
    assert Automation(str(tmp_path)).skips == [{"entry_id": plug_id, "date": "2026-10-05"}]
    nxt = a.next_action()
    assert nxt["action"] == "unplug" and nxt["time"].startswith("2026-10-06T07:00")
    up = a.upcoming()
    assert up[0]["skipped"] is True and up[0]["action"] == "plug" and not up[1]["skipped"]
    a.due()
    clock.advance(minutes=31)
    assert a.due() == []  # skipped
    clock.advance(days=1)  # Tuesday 23:31: runs again
    assert [e["action"] for e in a.due()] == ["plug"]
    clock.advance(days=15)
    a.due()
    assert a.skips == []  # Monday's skip forgotten (after 14 days)
    a.set_skip(plug_id, "2026-10-09")
    a.set_skip(plug_id, "2026-10-09", skip=False)  # undo
    assert a.skips == []
    try:
        a.set_skip("nope", "2026-10-07")
        raise AssertionError("should have refused")
    except ValueError:
        pass


def test_skipped_unplug_moves_the_ready_time_and_start_up():
    every = list(range(7))
    a, clock = _automation(start=datetime.datetime(2026, 10, 6, 2, 0, tzinfo=TZ))  # Tuesday 02:00
    a.set_schedule(enabled=True, entries=[
        {"time": "23:30", "action": "plug", "days": every}, {"time": "07:00", "action": "unplug", "days": every}])
    plug_id, unplug_id = a.entries[0]["id"], a.entries[1]["id"]
    a.set_skip(unplug_id, "2026-10-06")
    assert a.next_unplug(clock.now()).strftime("%a %H:%M") == "Wed 07:00"
    a.set_skip(plug_id, "2026-10-05")  # last night's plug-in skipped: not inside a stretch
    assert a.in_plug_window() is None


def test_skip_a_whole_slot():
    every = list(range(7))
    a, clock = _automation()  # Monday 23:00
    a.set_schedule(enabled=True, entries=[
        {"time": "23:30", "action": "plug", "days": every}, {"time": "07:00", "action": "unplug", "days": every}])
    plug_id, unplug_id = a.entries[0]["id"], a.entries[1]["id"]
    slot = [{"entry_id": plug_id, "date": "2026-10-05"}, {"entry_id": unplug_id, "date": "2026-10-06"}]
    a.set_skips(slot)
    nxt = a.next_action()
    assert nxt["action"] == "plug" and nxt["time"].startswith("2026-10-06T23:30")  # the whole night skipped
    try:
        a.set_skips(slot + [{"entry_id": "nope", "date": "2026-10-07"}], skip=False)  # all or nothing
        raise AssertionError("should have refused")
    except ValueError:
        assert len(a.skips) == 2
    a.set_skips(slot, skip=False)
    assert a.skips == []


def test_graceful_unplug_waits_for_the_supplier():
    from src import automation as auto_mod
    from src.automation import automation_loop
    every = list(range(7))

    def run(ready_time, in_session, supplier_stops):
        a, clock = _automation(start=datetime.datetime(2026, 10, 6, 6, 59, tzinfo=TZ))
        a.set_schedule(enabled=True, ready_time=ready_time, entries=[
            {"time": "23:30", "action": "plug", "days": every}, {"time": "07:00", "action": "unplug", "days": every}])
        state = SharedState(plugged_in=True, transaction_id=1 if in_session else None)
        calls = []

        async def plug(source=None):
            calls.append("plug")

        async def unplug(source=None):
            calls.append(("unplug", round(clock.epoch() - start)))
            state.plugged_in = False

        start = 0

        async def scenario():
            nonlocal start
            task = asyncio.ensure_future(automation_loop(a, state, plug, unplug, tick_s=0.01))
            await asyncio.sleep(0.03)
            clock.advance(minutes=1, seconds=1)  # 07:00:01: unplug due
            start = clock.epoch()
            await asyncio.sleep(0.05)
            waiting = a.unplug_at is not None
            if supplier_stops:
                clock.advance(seconds=20)
                state.transaction_id = None  # RemoteStop
            else:
                clock.advance(seconds=61)
            await asyncio.sleep(0.05)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return waiting

        old = auto_mod.PENDING_TICK_S
        auto_mod.PENDING_TICK_S = 0.01
        try:
            waiting = _run(scenario())
        finally:
            auto_mod.PENDING_TICK_S = old
        return calls, waiting

    assert run(False, True, False) == ([("unplug", 0)], False)  # ready time off: straight away
    assert run(True, False, False) == ([("unplug", 0)], False)  # no session: straight away
    assert run(True, True, True) == ([("unplug", 20)], True)  # supplier stopped it after 20 s
    assert run(True, True, False) == ([("unplug", 61)], True)  # gave it a minute


def test_unplug_wait_setting(tmp_path):
    a, _ = _automation(tmp_path)
    assert a.unplug_wait_s == 60 and a.snapshot()["schedule"]["unplug_wait_s"] == 60
    a.set_schedule(unplug_wait_s=120)
    assert _automation(tmp_path)[0].unplug_wait_s == 120  # saved
    for bad in (-1, 601, "x"):
        try:
            a.set_schedule(unplug_wait_s=bad)
            raise AssertionError("accepted %r" % (bad,))
        except ValueError:
            pass
    assert a.unplug_wait_s == 120


def test_unplug_wait_zero_unplugs_straight_away():
    every = list(range(7))
    a, clock = _automation(start=datetime.datetime(2026, 10, 6, 6, 59, tzinfo=TZ))
    a.set_schedule(enabled=True, ready_time=True, unplug_wait_s=0, entries=[
        {"time": "23:30", "action": "plug", "days": every}, {"time": "07:00", "action": "unplug", "days": every}])
    state = SharedState(plugged_in=True, transaction_id=1)
    calls = []

    async def plug(source=None):
        calls.append("plug")

    async def unplug(source=None):
        calls.append("unplug")
        state.plugged_in = False

    async def scenario():
        task = asyncio.ensure_future(automation_loop(a, state, plug, unplug, tick_s=0.01))
        await asyncio.sleep(0.03)
        clock.advance(minutes=1, seconds=1)
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    _run(scenario())
    assert calls == ["unplug"] and a.unplug_at is None



def test_slot_running_with_no_session_re_plugs_after_the_half_hour():
    from src.shared_state import SharedState, display_status
    # The add-on restarted mid-slot at 16:41:50; the supplier may start at 17:00
    a, clock = _automation(start=datetime.datetime(2026, 10, 3, 16, 41, 50, tzinfo=TZ))
    a.set_replug(enabled=True, after_min=10, attempts=2)
    state = SharedState(state="Preparing", plugged_in=True, connected_to_server=True)
    calls = []
    seen = {}

    async def plug(source=None):
        calls.append("plug")

    async def unplug(source=None):
        calls.append("unplug")

    async def run():
        task = asyncio.ensure_future(automation_loop(a, state, plug, unplug, tick_s=0.01,
                                                     scheduled=lambda: True, slot_now=lambda: True))
        await asyncio.sleep(0.05)
        seen["status"] = display_status(state)
        seen["replug"] = a.replug_status()  # "waiting", not "scheduled": a slot is running
        clock.advance(minutes=23)  # 17:04:50: not yet
        await asyncio.sleep(0.05)
        seen["at_1705"] = list(calls)
        clock.advance(minutes=6)  # 17:10:50
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    _run(run())
    assert seen["status"] == "Waiting for supplier"
    assert seen["replug"]["status"] == "waiting" and "T17:10:00" in seen["replug"]["next_replug_at"]
    assert seen["at_1705"] == []
    assert calls == ["unplug"]  # re-plug started (it plugs back in 30 s later)
    state.slot_now = False
    assert display_status(state) == "Scheduled"
    state.state = "Charging"
    assert display_status(state) == "Charging"


def test_planned_slot_still_holds_off_re_plug():
    a, clock = _automation()
    a.set_replug(enabled=True, after_min=10, attempts=2)
    assert not a.replug_due(True, False, True, scheduled=True, slot_now=False)
    clock.advance(minutes=30)
    assert not a.replug_due(True, False, True, scheduled=True, slot_now=False)
    assert a.replug_status()["status"] == "scheduled"


# --- auto plug-in charge (plan_auto_plug) -------------------------------------


def _sched_18_22(start, enabled=True):
    a, clock = _automation(start=start)
    a.set_schedule(enabled=enabled, entries=[{"time": "18:00", "action": "plug", "days": list(range(7))},
                                             {"time": "22:00", "action": "unplug", "days": list(range(7))}])
    return a, clock


def _today_windows(a, clock):
    day = clock.now().date()
    return [(x.strftime("%H:%M"), y.strftime("%H:%M")) for x, y in a.windows() if x.date() == day]


def _at(h, m=0):
    return datetime.datetime(2026, 10, 3, h, m, tzinfo=TZ)  # Saturday


def test_auto_plug_adds_a_one_off_slot():
    a, clock = _sched_18_22(_at(12, 10))
    out = a.plan_auto_plug(90, cap_min=360)  # 13:40 -> next half hour 14:00
    assert out["ready_for"].startswith("2026-10-03T14:00") and not out["combined"] and out["moved"] is None
    autos = [(e["time"], e["action"]) for e in a.entries if e.get("source") == "auto_plug"]
    assert autos == [("12:10", "plug"), ("14:00", "unplug")]
    assert _today_windows(a, clock) == [("12:10", "14:00"), ("18:00", "22:00")]
    assert a.next_unplug(clock.now()).strftime("%H:%M") == "14:00"


def test_auto_plug_joins_an_overlapping_slot():
    a, clock = _sched_18_22(_at(16, 30))
    out = a.plan_auto_plug(120, cap_min=360)  # to 18:30, overlaps 18:00-22:00: 5.5 h in all
    assert out["combined"] and out["end"].startswith("2026-10-03T22:00")
    assert _today_windows(a, clock) == [("16:30", "22:00")]
    assert a.next_unplug(clock.now()).strftime("%H:%M") == "22:00"  # the ready time is set for 22:00


def _sat_slots(*pairs, start=None):
    """Saturday-only slots (so the previous day has none), now 12:00 Saturday."""
    a, clock = _automation(start=start or _at(12))
    entries = []
    for p, u in pairs:
        entries += [{"time": p, "action": "plug", "days": [5]}, {"time": u, "action": "unplug", "days": [5]}]
    a.set_schedule(enabled=True, entries=entries)
    return a, clock


def test_auto_plug_over_the_cap_trims_just_enough():
    a, clock = _sat_slots(("18:00", "22:00"))
    out = a.plan_auto_plug(180, cap_min=360)  # 12-15 + 18-22 = 7 h: the slot loses 1 h
    assert not out["combined"] and "19:00" in out["moved"]
    assert out["over"] == {"before": 420, "after": 360, "added": 60, "left": 0}
    assert _today_windows(a, clock) == [("12:00", "15:00"), ("19:00", "22:00")]
    # Without a cap (EDF, E.ON) nothing moves
    b, clock_b = _sat_slots(("18:00", "22:00"))
    assert b.plan_auto_plug(180)["over"] is None
    assert _today_windows(b, clock_b) == [("12:00", "15:00"), ("18:00", "22:00")]


def test_auto_plug_over_the_cap_trims_a_daily_slot():
    a, clock = _sched_18_22(_at(12))
    out = a.plan_auto_plug(180, cap_min=360)  # tonight's slot loses 1 h
    assert "19:00" in out["moved"]
    assert _today_windows(a, clock) == [("12:00", "15:00"), ("19:00", "22:00")]
    # yesterday's 18-22 and this charge are 7 h in the 24 hours from yesterday 18:00: nothing to trim for that
    assert out["over"] == {"before": 420, "after": 420, "added": 60, "left": 60}


def test_auto_plug_over_the_cap_can_skip_the_next_slot():
    a, clock = _sat_slots(("18:00", "22:00"))
    out = a.plan_auto_plug(360, cap_min=360)  # 12-18 and 18-22: the slot has to go
    assert "skipped" in out["moved"] and out["over"]["after"] == 360
    assert _today_windows(a, clock) == [("12:00", "18:00")]
    nxt = clock.now().date() + datetime.timedelta(days=7)
    assert any(x.date() == nxt for x, _ in a.windows())  # only this week's is skipped


def test_auto_plug_counts_the_previous_24_hours():
    a, clock = _sat_slots(("02:00", "06:00"), ("20:00", "22:00"))
    out = a.plan_auto_plug(180, cap_min=360)  # 02-06 + 12-15 + 20-22 = 9 h in the 24 from 02:00
    assert out["over"] == {"before": 540, "after": 420, "added": 180, "left": 60}  # skipping 20-22 helps, but 7 h is left
    assert "skipped" in out["moved"]


def test_charge_isnt_blamed_for_the_schedules_own_hours():
    # 23:30-07:00 is already 7.5 h: a charge that doesn't add to any 24 hours with it trims nothing
    a, clock = _automation(start=datetime.datetime(2026, 10, 5, 8, 0, tzinfo=TZ))  # Monday 08:00
    a.set_schedule(enabled=True, entries=[{"time": "23:30", "action": "plug", "days": [0, 1, 2, 3, 4]},
                                          {"time": "07:00", "action": "unplug", "days": list(range(7))}])
    out = a.plan_auto_plug(60, cap_min=360, dry_run=True)  # 08:00-09:00: 8.5 h in the 24 from 08:00
    assert out["over"] == {"before": 510, "after": 450, "added": 60, "left": 0}
    assert "00:30" in out["moved"]  # only the hour the charge adds comes off, not the schedule's own extra 1.5


def test_a_daily_unplug_doesnt_cut_the_charge_short():
    a, clock = _automation(start=datetime.datetime(2026, 10, 5, 5, 30, tzinfo=TZ))  # Monday 05:30
    a.set_schedule(enabled=True, entries=[{"time": "07:00", "action": "unplug", "days": list(range(7))}])
    a.plan_auto_plug(180)
    day = clock.now().date()
    assert [(x.strftime("%H:%M"), y.strftime("%H:%M")) for x, y in a.windows() if x.date() == day] == [("05:30", "08:30")]


def test_auto_plug_dry_run_changes_nothing():
    a, clock = _sat_slots(("18:00", "22:00"))
    entries, skips = list(a.entries), list(a.skips)
    out = a.plan_auto_plug(180, cap_min=360, dry_run=True)
    assert "19:00" in out["moved"] and a.entries == entries and a.skips == skips and a.auto_plug_last is None


def test_an_already_over_schedule_can_still_be_changed():
    a, clock = _sat_slots(("18:00", "22:00"))
    a.set_schedule(ready_time=True, daily_cap_min=360)
    a.plan_auto_plug(360, cap_min=None)  # e.g. before the cap applied: 12-18 + 18-22 = 10 h
    weekly = [e for e in a.entries if not e.get("date")]
    shorter = [dict(e, time="21:00") if e["action"] == "plug" and not e.get("date") else e for e in a.entries]
    a.set_schedule(entries=shorter, daily_cap_min=360)  # still over, but no worse: saved
    longer = [dict(e, time="23:00") if e["action"] == "unplug" and not e.get("date") else e for e in a.entries]
    try:
        a.set_schedule(entries=longer, daily_cap_min=360)
        raise AssertionError("should have refused")
    except ValueError as err:
        assert "6 hours" in str(err)
    assert weekly


def test_auto_plug_ready_time_rounds_to_what_the_supplier_accepts():
    from src.ready_time import DEFAULT_TIMES
    a, clock = _sched_18_22(_at(14), enabled=False)
    out = a.plan_auto_plug(120, ready_times=DEFAULT_TIMES)  # EDF: 04:00-11:00 only
    assert out["ready_for"].startswith("2026-10-04T04:00")


def test_auto_plug_slot_runs_with_the_schedule_off():
    a, clock = _sched_18_22(_at(12), enabled=False)
    a.plan_auto_plug(60)
    assert [x.strftime("%H:%M") for x, _ in a.windows()] == ["12:00"]  # the schedule's own are off
    a.due()
    clock.advance(minutes=61)
    assert [e["action"] for e in a.due()] == ["unplug"]
    assert a.snapshot()["schedule"]["auto_plug_last"]["end"].startswith("2026-10-03T13:00")


def test_auto_plug_charge_sets_the_ready_time():
    from src.automation import auto_plug_charge
    a, clock = _sched_18_22(_at(16, 30))
    asked = []

    async def set_ready(unplug):
        asked.append(unplug.strftime("%H:%M"))
        return {"ready": unplug.strftime("%H:%M"), "unplug": unplug.isoformat()}

    _run(auto_plug_charge(a, 2, set_ready, cap_min=360))
    assert asked == ["22:00"]  # joined with the 18:00-22:00 slot


def test_one_offs_kept_14_days_and_listed_as_runs():
    a, clock = _sched_18_22(_at(12))
    a.plan_auto_plug(60)  # 12:00-13:00, auto plug-in
    a.set_schedule(entries=a.entries + [{"time": "08:00", "action": "plug", "date": "2026-10-04"},
                                         {"time": "09:00", "action": "unplug", "date": "2026-10-04"}])
    clock.advance(days=2)
    runs = a.one_off_runs()
    assert [(r["start"][:16], r["source"]) for r in runs] == [
        ("2026-10-04T08:00", "one_off"), ("2026-10-03T12:00", "auto_plug")]
    clock.advance(days=10)
    a.set_schedule(enabled=True)  # prunes
    assert len([e for e in a.entries if e.get("date")]) == 4  # 12 days on: still kept
    clock.advance(days=3)
    a.set_schedule(enabled=True)
    assert [e for e in a.entries if e.get("date")] == []  # over 14 days: gone
    assert a.snapshot()["schedule"]["one_off_runs"] == []


def test_six_hour_limit_only_with_force_schedule_on():
    long_day = [{"time": "12:00", "action": "plug", "days": list(range(7))},
                {"time": "22:00", "action": "unplug", "days": list(range(7))}]  # 10 h a day
    a, clock = _automation()
    a.set_schedule(enabled=True, ready_time=False, entries=long_day, daily_cap_min=360)  # off: fine
    assert len(a.entries) == 2
    try:
        a.set_schedule(ready_time=True, daily_cap_min=360)
        raise AssertionError("should have refused")
    except ValueError as err:
        assert "6 hours" in str(err)
    assert a.ready_time is False
    # Auto plug-in with no cap (Force off) adds to it without moving anything
    b, clock_b = _sched_18_22(_at(12))
    b.plan_auto_plug(300, cap_min=None)  # 12-17 + 18-22 = 9 h
    assert _today_windows(b, clock_b) == [("12:00", "17:00"), ("18:00", "22:00")]


def test_charge_now_is_planned_like_auto_plug_in():
    from src.automation import CHARGE_NOW_SOURCE
    a, clock = _sched_18_22(_at(12), enabled=False)
    out = a.plan_auto_plug(120, source=CHARGE_NOW_SOURCE)
    assert out["source"] == "charge_now"
    assert {e["source"] for e in a.entries if e.get("date")} == {"charge_now"}
    assert [x.strftime("%H:%M") for x, _ in a.windows()] == ["12:00"]  # runs with the schedule off
    a.due()
    clock.advance(minutes=121)
    assert [e["action"] for e in a.due()] == ["unplug"]
    assert a.one_off_runs()[0]["source"] == "charge_now"


def test_charge_capped_at_six_hours_for_octopus():
    a, clock = _sched_18_22(_at(8, 10), enabled=False)
    out = a.plan_auto_plug(480, cap_min=360, provider="Octopus Energy")  # 8 h asked
    assert out["ready_for"].startswith("2026-10-03T14:00")  # 08:10 + 6 h = 14:10: not rounded up past 6 h
    assert "shortened to 6 hours" in out["notes"][0]
    b, clock_b = _sched_18_22(_at(8, 10), enabled=False)
    assert b.plan_auto_plug(480)["ready_for"].startswith("2026-10-03T16:30")  # no cap: 8 h, rounded up
    c, clock_c = _sched_18_22(_at(8), enabled=False)
    assert c.plan_auto_plug(360, cap_min=360)["ready_for"].startswith("2026-10-03T14:00")  # exactly 6 h



def test_unskip_cant_go_over_six_hours():
    def sunday_slot():
        a, clock = _automation(start=_at(12))  # Saturday 3 Oct
        a.set_schedule(enabled=True, ready_time=True, daily_cap_min=360, entries=[
            {"time": "18:00", "action": "plug", "days": [6]}, {"time": "22:00", "action": "unplug", "days": [6]}])
        plug = next(e for e in a.entries if e["action"] == "plug")
        unplug = next(e for e in a.entries if e["action"] == "unplug")
        return a, plug, unplug

    a, plug, unplug = sunday_slot()
    slot = [{"entry_id": plug["id"], "date": "2026-10-04"}, {"entry_id": unplug["id"], "date": "2026-10-04"}]
    a.set_skips(slot, True, daily_cap_min=360)  # skip Sunday's 18-22
    # While it's skipped, a 13:00-16:00 one-off on Sunday fits (3 h)
    a.set_schedule(entries=a.entries + [{"time": "13:00", "action": "plug", "date": "2026-10-04"},
                                         {"time": "16:00", "action": "unplug", "date": "2026-10-04"}], daily_cap_min=360)
    try:
        a.set_skips(slot, False, daily_cap_min=360, provider="Octopus Energy")  # back on: 7 h
        raise AssertionError("should have refused")
    except ValueError as err:
        assert "6 hours" in str(err)
    assert {"entry_id": plug["id"], "date": "2026-10-04"} in a.skips  # nothing changed
    # With Force schedule on supplier off, there's no limit
    a.set_schedule(ready_time=False)
    a.set_skips(slot, False, daily_cap_min=360)
    assert a.skips == []

    # Skipping only the unplug would leave it plugged in until next Sunday: refused
    b, plug, unplug = sunday_slot()
    try:
        b.set_skips([{"entry_id": unplug["id"], "date": "2026-10-04"}], True, daily_cap_min=360)
        raise AssertionError("should have refused")
    except ValueError:
        pass
    b.set_skips([{"entry_id": plug["id"], "date": "2026-10-04"}, {"entry_id": unplug["id"], "date": "2026-10-04"}],
                True, daily_cap_min=360)  # the whole slot: fine


def test_override_guards_lifts_the_six_hours():
    every = list(range(7))
    seven = [{"time": "23:30", "action": "plug", "days": every}, {"time": "06:30", "action": "unplug", "days": every}]
    six = [{"time": "23:30", "action": "plug", "days": every}, {"time": "05:30", "action": "unplug", "days": every}]
    a, clock = _automation()
    a.set_schedule(entries=six, ready_time=True, daily_cap_min=360)
    a.set_schedule(override_guards=True, daily_cap_min=360)
    a.set_schedule(entries=seven, daily_cap_min=360)  # over 6 hours, allowed
    assert a.override_guards and a.snapshot()["schedule"]["override_guards"]
    try:
        a.set_schedule(override_guards=False, daily_cap_min=360, provider="Octopus Energy")  # back on while over
        raise AssertionError("should have refused")
    except ValueError as err:
        assert "6 hours" in str(err)
    assert a.override_guards
    a.set_schedule(entries=six, override_guards=False, daily_cap_min=360)
    assert not a.override_guards


NIGHT = {"start": "23:30", "end": "05:30", "days": list(range(7))}


def _blocked(start, entries=()):
    a, clock = _automation(start=start)
    a.set_schedule(enabled=True, entries=list(entries), blocks=[NIGHT])
    return a, clock


def _spans(out):
    return [(x["start"][11:16], x["end"][11:16]) for x in out["segments"]]


def test_slots_cant_overlap_a_no_charging_time():
    a, clock = _blocked(_at(12))
    for slot in (("22:00", "00:00"), ("05:00", "07:00")):
        try:
            a.set_schedule(entries=[{"time": slot[0], "action": "plug"}, {"time": slot[1], "action": "unplug"}])
            raise AssertionError("should have refused %s" % (slot,))
        except ValueError as err:
            assert "no-charging time" in str(err)
    a.set_schedule(entries=[{"time": "05:30", "action": "plug"}, {"time": "07:00", "action": "unplug"}])  # just after: fine
    try:
        a.set_schedule(blocks=[{"start": "05:00", "end": "06:00", "days": list(range(7))}])  # over that slot
        raise AssertionError("should have refused")
    except ValueError:
        pass
    assert a.blocks[0]["start"] == "23:30"


def test_a_charge_is_cut_around_a_no_charging_time():
    a, clock = _blocked(_at(18))
    out = a.plan_auto_plug(12 * 60)  # 18:00 for 12 h, no limit: 18:00-23:30, then 05:30-06:00
    assert _spans(out) == [("18:00", "23:30"), ("05:30", "06:00")] and out["plug_now"]
    day = clock.now().date()
    wins = [(x.strftime("%a %H:%M"), y.strftime("%a %H:%M")) for x, y in a.windows() if x.date() >= day]
    assert wins[:2] == [("Sat 18:00", "Sat 23:30"), ("Sun 05:30", "Sun 06:00")]


def test_only_the_daily_limit_is_scheduled():
    a, clock = _blocked(_at(18))
    out = a.plan_auto_plug(12 * 60, cap_min=360)  # 5.5 h before the night, 0.5 h after it
    assert _spans(out) == [("18:00", "23:30"), ("05:30", "06:00")] and out["minutes"] == 360
    b, _ = _blocked(_at(12))
    out = b.plan_auto_plug(12 * 60, cap_min=360)  # all 6 before the night
    assert _spans(out) == [("12:00", "18:00")] and "shortened to 6 hours" in out["notes"][0]


def test_a_charge_during_a_no_charging_time_waits_for_its_end():
    a, clock = _blocked(datetime.datetime(2026, 10, 3, 1, 0, tzinfo=TZ))
    out = a.plan_auto_plug(6 * 60)  # 01:00 for 6 h would end 07:00: 05:30-07:00, same end
    assert not out["plug_now"] and _spans(out) == [("05:30", "07:00")]
    b, _ = _blocked(datetime.datetime(2026, 10, 3, 1, 0, tzinfo=TZ))
    out = b.plan_auto_plug(3 * 60)  # would end at 04:00, inside it: nothing
    assert out["nothing"] and not out["plug_now"] and b.entries == []
    assert b.blocked() is not None


def test_deleting_a_charge_puts_back_the_slot_it_trimmed():
    a, clock = _sat_slots(("18:00", "22:00"))
    a.plan_auto_plug(180, cap_min=360, source="charge_now")  # tonight's slot now starts at 19:00
    later = next(e for e in a.entries if e["time"] == "19:00")
    assert later.get("source") is None  # still a plain slot, not a Charge now one
    assert _today_windows(a, clock) == [("12:00", "15:00"), ("19:00", "22:00")]
    charge = [e for e in a.entries if e.get("source") == "charge_now"]
    a.set_schedule(entries=[e for e in a.entries if e not in charge], daily_cap_min=360)
    assert _today_windows(a, clock) == [("18:00", "22:00")] and a.skips == []
    assert not any(e["time"] == "19:00" for e in a.entries)


def test_daily_limit_that_resets_at_midday():
    # Octopus's limit resets at 12:00: 6 hours before it and 6 after are fine
    sat = [{"time": "06:00", "action": "plug", "days": [5]}, {"time": "18:00", "action": "unplug", "days": [5]}]
    a, clock = _automation(start=_at(1))
    try:
        a.set_schedule(entries=sat, ready_time=True, daily_cap_min=360)  # any 24 hours: 12 h
        raise AssertionError("should have refused")
    except ValueError as err:
        assert "12h 00m" in str(err)
    a.limit_reset = "12:00"
    a.set_schedule(entries=sat, ready_time=True, daily_cap_min=360)  # 06-12 and 12-18: 6 h each
    assert a.entries[1]["time"] == "18:00"
    try:
        a.set_schedule(entries=[{"time": "11:00", "action": "plug", "days": [5]},
                                {"time": "19:00", "action": "unplug", "days": [5]}], daily_cap_min=360)
        raise AssertionError("should have refused")
    except ValueError as err:  # 12-19: 7 h after 12:00
        assert "7h 00m" in str(err) and "resets at 12:00" in str(err) and "Sat 12:00" in str(err)


def test_charge_across_the_limit_reset():
    a, clock = _automation(start=_at(8))  # Saturday 08:00, nothing scheduled
    a.limit_reset = "12:00"
    out = a.plan_auto_plug(720, cap_min=360, provider="Octopus Energy")  # 08-12 (4 h) + 12-18 (6 h, the limit)
    assert out["ready_for"].startswith("2026-10-03T18:00") and "shortened to 10 hours" in out["notes"][0]
    assert out["over"]["left"] == 0
    b, clock_b = _automation(start=_at(6))
    b.limit_reset = "12:00"
    out = b.plan_auto_plug(720, cap_min=360)  # 06-12 and 12-18: 6 h each, all of it
    assert out["ready_for"].startswith("2026-10-03T18:00") and not any("shortened" in n for n in out["notes"])
    c, clock_c = _automation(start=_at(8))  # any 24 hours: 6 h
    assert c.plan_auto_plug(720, cap_min=360)["ready_for"].startswith("2026-10-03T14:00")


def test_limit_reset_trims_only_within_the_limit_day():
    # 10:00-12:00 charge with an 18:00-22:00 slot: rolling, 6 h in 24 (fine);
    # a 3 h charge from 10:00 is 1 h before 12:00 and 2 h after: with 18-22 that's 6 h
    a, clock = _sat_slots(("18:00", "22:00"), start=_at(10))
    a.limit_reset = "12:00"
    out = a.plan_auto_plug(180, cap_min=360)
    assert out["moved"] is None and _today_windows(a, clock) == [("10:00", "13:00"), ("18:00", "22:00")]
    b, clock_b = _sat_slots(("18:00", "22:00"), start=_at(10))  # rolling: 7 h, the slot loses 1 h
    assert "19:00" in b.plan_auto_plug(180, cap_min=360)["moved"]


def test_daily_limit_over_any_48_hours():
    # 4 h on Saturday and 4 h on Sunday: fine in any 24 hours, 8 h in 48
    two = [{"time": "18:00", "action": "plug", "days": [5, 6]}, {"time": "22:00", "action": "unplug", "days": [5, 6]}]
    a, clock = _automation(start=_at(1))
    a.set_schedule(entries=two, ready_time=True, daily_cap_min=360)
    a.set_schedule(entries=[], daily_cap_min=360)
    a.limit_reset = "48h"
    try:
        a.set_schedule(entries=two, daily_cap_min=360)
        raise AssertionError("should have refused")
    except ValueError as err:
        assert "8h 00m" in str(err) and "48 hours" in str(err)
    # A charge counts the 48 hours around it: 12-15 with tonight's 18-22 (Saturday only)
    b, clock_b = _sat_slots(("18:00", "22:00"))
    b.limit_reset = "48h"
    out = b.plan_auto_plug(180, cap_min=360)  # 7 h in 48: the slot loses 1 h
    assert "19:00" in out["moved"] and out["over"]["left"] == 0
    c, clock_c = _automation(start=_at(8))
    c.limit_reset = "48h"
    assert c.plan_auto_plug(720, cap_min=360)["ready_for"].startswith("2026-10-03T14:00")  # 6 h, then it stops


def test_daily_limit_over_any_rolling_period():
    # A 12-hour rolling period: 18-22 Saturday and 08-11 Sunday are 14 h apart, fine
    two = [{"time": "18:00", "action": "plug", "days": [5]}, {"time": "22:00", "action": "unplug", "days": [5]},
           {"time": "08:00", "action": "plug", "days": [6]}, {"time": "11:00", "action": "unplug", "days": [6]}]
    a, clock = _automation(start=_at(1))
    a.limit_reset = "12h"
    a.set_schedule(entries=two, ready_time=True, daily_cap_min=360)
    a.limit_reset = None  # any 24 hours: 7 h
    try:
        a.check_daily_cap(a.entries, 360, "Octopus Energy")
        raise AssertionError("should have refused")
    except ValueError as err:
        assert "7h 00m" in str(err) and "24 hours" in str(err)
    a.limit_reset = "72h"
    try:
        a.check_daily_cap(a.entries, 360, "Octopus Energy")
        raise AssertionError("should have refused")
    except ValueError as err:
        assert "the 72 hours from" in str(err) and "in any 72 hours" in str(err)


def test_back_to_back_slots_are_one_stretch():
    thu = "2026-10-08"
    first = [{"time": "06:00", "action": "plug", "date": thu}, {"time": "12:00", "action": "unplug", "date": thu}]
    second = [{"time": "12:00", "action": "plug", "date": thu}, {"time": "23:00", "action": "unplug", "date": thu}]
    a, clock = _automation(start=datetime.datetime(2026, 10, 5, 14, 0, tzinfo=TZ))  # Monday
    a.set_schedule(enabled=True, entries=first + second)
    # plugged in for both (it used to unplug at 12:00 and stay unplugged)
    assert [(x.strftime("%H:%M"), y.strftime("%H:%M")) for x, y in a.windows()] == [("06:00", "12:00"), ("12:00", "23:00")]
    assert a.in_plug_window(datetime.datetime(2026, 10, 8, 15, 0, tzinfo=TZ)) is not None
    # Each slot has its own ready time: 12:00 for the first, 23:00 for the second
    assert a.next_unplug(datetime.datetime(2026, 10, 8, 6, 0, tzinfo=TZ)).strftime("%H:%M") == "12:00"
    assert a.next_unplug(datetime.datetime(2026, 10, 8, 12, 1, tzinfo=TZ)).strftime("%H:%M") == "23:00"
    # At 12:00 it unplugs (straight away) and plugs back in: two charges
    clock.dt = datetime.datetime(2026, 10, 8, 11, 59, tzinfo=TZ)
    a.due()
    clock.dt = datetime.datetime(2026, 10, 8, 12, 0, 30, tzinfo=TZ)
    due = a.due()
    assert [(e["action"], bool(e.get("back_to_back"))) for e in due] == [("unplug", True), ("plug", False)]
    # Octopus, resetting at 12:00: 12:00-23:00 is 11 hours in the day from 12:00
    b, clock_b = _automation(start=datetime.datetime(2026, 10, 5, 14, 0, tzinfo=TZ))
    b.limit_reset = "12:00"
    b.set_schedule(enabled=True, ready_time=True, entries=first, daily_cap_min=360)
    try:
        b.set_schedule(entries=b.entries + second, daily_cap_min=360, provider="Octopus Energy")
        raise AssertionError("should have refused")
    except ValueError as err:
        assert "11h 00m" in str(err) and "Thu 12:00" in str(err)


def _over_cap(fn):
    try:
        fn()
    except ValueError as err:
        assert "6 hours" in str(err)
        return True
    return False


def _fresh_cap(reset=None):
    a, clock = _automation(start=datetime.datetime(2026, 10, 5, 14, 0, tzinfo=TZ))  # Monday 14:00
    a.limit_reset = reset
    a.set_schedule(enabled=True, ready_time=True, daily_cap_min=360)
    return a


def _slot(p, u, **k):
    return [{"time": p, "action": "plug", **k}, {"time": u, "action": "unplug", **k}]


def test_already_over_cant_add_another_day_over():
    a = _fresh_cap()
    a.override_guards = True  # e.g. Charge anyway: Tuesday is 7 h
    a.set_schedule(entries=_slot("10:00", "17:00", date="2026-10-06"), daily_cap_min=360)
    a.override_guards = False
    assert _over_cap(lambda: a.set_schedule(entries=a.entries + _slot("10:00", "17:00", date="2026-10-08"), daily_cap_min=360))
    # Shortening the one that's over is fine
    a.set_schedule(entries=_slot("10:00", "16:00", date="2026-10-06"), daily_cap_min=360)


def test_one_offs_weeks_ahead_are_checked():
    a = _fresh_cap()
    assert _over_cap(lambda: a.set_schedule(entries=_slot("06:00", "18:00", date="2026-10-26"), daily_cap_min=360))
    a.set_schedule(entries=_slot("06:00", "12:00", date="2026-10-26"), daily_cap_min=360)  # 6 h: fine


def test_plug_in_that_never_unplugs_counts():
    a = _fresh_cap()
    assert _over_cap(lambda: a.set_schedule(entries=[{"time": "06:00", "action": "plug", "days": [2]}], daily_cap_min=360))


def test_unskipping_into_a_no_charging_time_is_refused():
    a = _fresh_cap()
    a.set_schedule(entries=[{"time": "23:30", "action": "plug", "date": "2026-10-07"},
                            {"time": "03:30", "action": "unplug", "date": "2026-10-08"}], daily_cap_min=360)
    p = next(e for e in a.entries if e["action"] == "plug")
    u = next(e for e in a.entries if e["action"] == "unplug")
    keys = [{"entry_id": p["id"], "date": "2026-10-07"}, {"entry_id": u["id"], "date": "2026-10-08"}]
    a.set_skips(keys, True, daily_cap_min=360)
    a.set_schedule(blocks=[{"start": "23:00", "end": "05:00", "days": [2]}])  # fine while it's skipped
    try:
        a.set_skips(keys, False, daily_cap_min=360)
        raise AssertionError("should have refused")
    except ValueError as err:
        assert "no-charging time" in str(err)
    assert keys[0] in a.skips


def test_clock_change_nights_count_real_hours():
    """Octopus counts the night the clocks go back as 25 hours: 23:30-05:30 is
    7 hours then (5 when they go forward). Limit days are 12:00 to 12:00 by the clock."""
    import os
    import time as _time
    from src.automation import Automation, ReplugOptions, limit_end, period_start
    old = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/London"
    _time.tzset()
    try:
        now = datetime.datetime(2026, 10, 23, 12, 0).astimezone()
        a = Automation(None, ReplugOptions(), now=lambda: now, clock=_time.time)  # the add-on's own clock handling
        night = [{"time": "23:30", "action": "plug", "date": "2026-10-24"},
                 {"time": "05:30", "action": "unplug", "date": "2026-10-25"}]
        a.set_schedule(enabled=True, ready_time=True, daily_cap_min=360)
        for reset in (None, "12:00"):
            a.limit_reset = reset
            try:
                a.set_schedule(entries=night, daily_cap_min=360)
                raise AssertionError("should have refused")
            except ValueError as err:
                assert "7h 00m" in str(err)
        # 23:30-04:30 is the 6 hours that night
        a.set_schedule(entries=[dict(night[0]), dict(night[1], time="04:30")], daily_cap_min=360)
        # The limit day from Sat 12:00 ends Sun 12:00 by the clock: 25 hours
        sat = datetime.datetime(2026, 10, 24, 15, 0).astimezone()
        start = period_start(sat, "12:00")
        assert start.hour == 12 and start.day == 24
        end = limit_end(start, "12:00")
        assert end.hour == 12 and end.day == 25 and (end - start) == datetime.timedelta(hours=25)
        # After the change: Sun 13:00 is in the day from Sun 12:00
        sun = datetime.datetime(2026, 10, 25, 13, 0).astimezone()
        assert period_start(sun, "12:00").day == 25
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        _time.tzset()


def test_auto_plug_trims_every_later_slot_it_needs_to():
    # 14:00 + 6 h with 21:00-22:00 and 01:00-05:00 after it: both go (6 h in 24 already)
    a = _fresh_cap()
    a.set_schedule(entries=_slot("21:00", "22:00", days=[0]) + [{"time": "01:00", "action": "plug", "days": [1]},
                   {"time": "05:00", "action": "unplug", "days": [1]}], daily_cap_min=360)
    out = a.plan_auto_plug(360, cap_min=360)
    assert out["over"]["left"] == 0 and out["over"]["after"] == 360
    assert "21:00–22:00 slot is skipped" in out["moved"] and "01:00–05:00 slot is skipped" in out["moved"]
    assert a._longest_day(a.entries)[0] == 360
    # 14:00 + 3 h is 2 h over: the next slot first (21-22 skipped), then 01:00-05:00 starts at 02:00
    b = _fresh_cap()
    b.set_schedule(entries=_slot("21:00", "22:00", days=[0]) + [{"time": "01:00", "action": "plug", "days": [1]},
                   {"time": "05:00", "action": "unplug", "days": [1]}], daily_cap_min=360)
    out = b.plan_auto_plug(180, cap_min=360)
    assert out["moved"] == "the 21:00–22:00 slot is skipped; the 05:00 slot now starts at 02:00"
    assert out["over"] == {"before": 480, "after": 360, "added": 120, "left": 0}
    # Deleting the charge puts both back
    c = _fresh_cap()
    c.set_schedule(entries=_slot("21:00", "22:00", days=[0]) + [{"time": "01:00", "action": "plug", "days": [1]},
                   {"time": "05:00", "action": "unplug", "days": [1]}], daily_cap_min=360)
    weekly = [e for e in c.entries if not e.get("date")]
    c.plan_auto_plug(360, cap_min=360)
    assert c.skips
    c.set_schedule(entries=weekly)
    assert c.skips == [] and all(not e.get("date") for e in c.entries)


def test_replug_unplugged_for_is_a_setting():
    a, clock = _automation()
    assert a.replug["off_s"] == 30
    a.set_replug(off_s=60)
    assert a.replug["off_s"] == 60
    for bad in (2, 301, "x"):
        try:
            a.set_replug(off_s=bad)
            raise AssertionError("should have refused")
        except ValueError:
            pass
    waits = []

    async def unplug(source):
        pass

    async def plug(source):
        pass

    async def fake_sleep(s):
        waits.append(s)

    import src.automation as mod
    real = mod.asyncio.sleep
    mod.asyncio.sleep = fake_sleep
    try:
        _run(a.run_replug(unplug, plug))
    finally:
        mod.asyncio.sleep = real
    assert waits == [60]


def test_back_to_back_slots_replug_at_the_join():
    """06:00-12:00 then 12:00-18:00 (Octopus resets at 12:00): at 12:00 it
    unplugs straight away (even mid-session with Force schedule on) and plugs
    back in after the re-plug time, then sets the ready time to 18:00."""
    from src.shared_state import SharedState
    thu = "2026-10-08"
    a, clock = _automation(start=datetime.datetime(2026, 10, 8, 11, 59, 50, tzinfo=TZ))
    a.set_schedule(enabled=True, ready_time=True, entries=[
        {"time": "06:00", "action": "plug", "date": thu}, {"time": "12:00", "action": "unplug", "date": thu},
        {"time": "12:00", "action": "plug", "date": thu}, {"time": "18:00", "action": "unplug", "date": thu}])
    a.set_replug(off_s=5)
    state = SharedState(plugged_in=True)
    state.transaction_id = 7  # a session is going
    calls, asked, slept = [], [], []

    async def plug(source=None):
        calls.append("plug")
        state.plugged_in = True

    async def unplug(source=None):
        calls.append("unplug")
        state.plugged_in = False

    async def set_ready(unplug_at):
        asked.append(unplug_at.strftime("%H:%M"))
        return {"ready": unplug_at.strftime("%H:%M")}

    import src.automation as mod
    real_sleep = mod.asyncio.sleep

    async def fake_sleep(s):
        if s == 5:
            slept.append(s)
        await real_sleep(0)

    async def ticks():
        task = asyncio.ensure_future(automation_loop(a, state, plug, unplug, tick_s=0.01, set_ready_time=set_ready))
        await real_sleep(0.03)
        clock.dt = datetime.datetime(2026, 10, 8, 12, 0, 10, tzinfo=TZ)
        await real_sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    mod.asyncio.sleep = fake_sleep
    try:
        _run(ticks())
    finally:
        mod.asyncio.sleep = real_sleep
    assert calls == ["unplug", "plug"] and slept == [5]
    assert asked and asked[-1] == "18:00"


def _pairs(a, day):
    return sorted((x.strftime("%H:%M"), y.strftime("%H:%M")) for x, y in a.windows() if x.date() == day)


def test_charge_across_the_reset_is_split_there():
    a, clock = _automation(start=_at(8))  # Saturday 08:00
    a.limit_reset = "12:00"
    out = a.plan_auto_plug(720, cap_min=360)  # 08-12 and 12-18
    day = clock.now().date()
    assert _pairs(a, day) == [("08:00", "12:00"), ("12:00", "18:00")]
    assert any("fresh charge from 12:00" in n for n in out["notes"])
    assert a.next_unplug(clock.now()).strftime("%H:%M") == "12:00"  # the first ready time
    # Deleting the charge takes the split with it
    a.set_schedule(entries=[])
    assert a.entries == []
    # Not with a rolling limit, nor a charge within the limit
    b, clock_b = _automation(start=_at(8))
    b.plan_auto_plug(720, cap_min=360)
    assert _pairs(b, day) == [("08:00", "14:00")]
    c, clock_c = _automation(start=_at(10))
    c.limit_reset = "12:00"
    c.plan_auto_plug(180, cap_min=360)  # 10-13: 3 h
    assert _pairs(c, day) == [("10:00", "13:00")]


def test_charge_joining_a_slot_across_the_reset_is_split():
    a, clock = _sat_slots(("12:00", "18:00"), start=_at(8))
    a.limit_reset = "12:00"
    out = a.plan_auto_plug(240, cap_min=360)  # 08-12 meets 12-18: 10 h as one
    assert out["combined"]
    assert _pairs(a, clock.now().date()) == [("08:00", "12:00"), ("12:00", "18:00")]
    assert a.next_unplug(clock.now()).strftime("%H:%M") == "12:00"


def test_saved_slots_across_the_reset_are_split():
    a, clock = _automation(start=datetime.datetime(2026, 10, 5, 7, 0, tzinfo=TZ))  # Monday 07:00
    a.limit_reset = "12:00"
    a.set_schedule(enabled=True, ready_time=True, daily_cap_min=360, entries=[
        {"time": "09:00", "action": "plug", "days": [1, 3]}, {"time": "17:00", "action": "unplug", "days": [1, 3]},
        {"time": "08:00", "action": "plug", "date": "2026-10-10"}, {"time": "18:00", "action": "unplug", "date": "2026-10-10"},
        {"time": "13:00", "action": "plug", "days": [0]}, {"time": "15:00", "action": "unplug", "days": [0]}])
    assert not any(e["time"] == "12:00" and 0 in e["days"] for e in a.entries)  # 13-15 isn't across 12:00
    weekly = sorted((e["time"], e["action"], tuple(e["days"])) for e in a.entries if not e.get("date"))
    assert ("12:00", "plug", (1, 3)) in weekly and ("12:00", "unplug", (1, 3)) in weekly
    once = sorted((e["time"], e["action"], e["date"]) for e in a.entries if e.get("date"))
    assert once == [("08:00", "plug", "2026-10-10"), ("12:00", "plug", "2026-10-10"),
                    ("12:00", "unplug", "2026-10-10"), ("18:00", "unplug", "2026-10-10")]
    tue = datetime.date(2026, 10, 6)
    assert _pairs(a, tue) == [("09:00", "12:00"), ("12:00", "17:00")]
    n = len(a.entries)
    a.set_schedule(entries=a.entries, daily_cap_min=360)  # saving again adds nothing
    assert len(a.entries) == n
    # Force schedule off: left as it is
    b, clock_b = _automation(start=datetime.datetime(2026, 10, 5, 7, 0, tzinfo=TZ))
    b.limit_reset = "12:00"
    b.set_schedule(enabled=True, entries=[{"time": "09:00", "action": "plug", "days": [1]},
                                          {"time": "17:00", "action": "unplug", "days": [1]}], daily_cap_min=360)
    assert len(b.entries) == 2
