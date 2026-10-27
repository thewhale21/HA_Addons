"""src/schedule_notify.py: notifications when the schedule changes."""
import datetime

from src.automation import Automation, ReplugOptions
from src.schedule_notify import Watcher, causes, describe, upcoming

TZ = datetime.timezone.utc


def _at(h, m=0, day=27):
    return datetime.datetime(2026, 10, day, h, m, tzinfo=TZ)


def test_a_change_is_told_once_settled_with_each_day_before_and_after():
    now = _at(13, 45)
    old = upcoming([(_at(15, 30), _at(21, 30)), (_at(15, 30, 28), _at(21, 30, 28))], now)
    new = upcoming([(_at(14), _at(18)), (_at(20), _at(22)), (_at(15, 30, 28), _at(21, 30, 28))], now)
    why = {datetime.date(2026, 10, 27): "saving session 18:00–20:00"}
    assert describe(old, new, now, why) == \
        "Today: 15:30–21:30 → 14:00–18:00, 20:00–22:00 (saving session 18:00–20:00)"
    w = Watcher()
    assert w.tick(now, 0, old) is None  # start-up: nothing to compare with
    assert w.tick(now, 10, new) is None  # changed: waits to settle
    assert w.tick(now, 40, new) is None
    assert w.tick(now, 75, new, why).startswith("Today: 15:30–21:30 → 14:00")
    assert w.tick(now, 200, new) is None  # told once


def test_time_passing_isnt_a_change():
    w = Watcher()
    slots = [(_at(15, 30), _at(21, 30)), (_at(15, 30, 28), _at(21, 30, 28))]
    w.tick(_at(15), 0, upcoming(slots, _at(15)))
    for t, clock in ((_at(16), 100), (_at(16), 200), (_at(22), 300), (_at(22), 400)):
        assert w.tick(t, clock, upcoming(slots, t)) is None


def test_new_days_and_removed_ones():
    now = _at(9)
    old = upcoming([(_at(15, 30, 28), _at(21, 30, 28))], now)
    new = upcoming([(_at(10), _at(13))], now)
    assert describe(old, new, now) == "Today: nothing → 10:00–13:00\nTomorrow: 15:30–21:30 → nothing"


def test_causes_from_the_schedule():
    entries = [{"time": "13:45", "date": "2026-10-27", "action": "plug", "source": "charge_now"},
               {"time": "15:30", "days": [1], "action": "plug"}]
    sessions = [{"start": "2026-10-27T18:00:00+00:00", "end": "2026-10-27T20:00:00+00:00"}]
    assert causes(entries, sessions, True) == {datetime.date(2026, 10, 27): "saving session 18:00–20:00, Charge now"}
    assert causes(entries, sessions, False) == {datetime.date(2026, 10, 27): "Charge now"}


def test_with_the_schedule_from_automation():
    clock_now = [_at(12)]
    a = Automation(None, ReplugOptions(), now=lambda: clock_now[0], clock=lambda: clock_now[0].timestamp(),
                   localize=lambda naive: naive.replace(tzinfo=TZ))
    a.set_schedule(enabled=True, entries=[{"time": "15:30", "action": "plug"}, {"time": "21:30", "action": "unplug"}])
    w = Watcher()
    w.tick(clock_now[0], 0, upcoming(a.windows(), clock_now[0]))
    a.sync_saving_sessions([{"start": _at(18), "end": _at(20), "summary": "x"}], block=True)
    cur = upcoming(a.windows(), clock_now[0])
    why = causes(a.entries, a.saving_sessions, a.saving_block)
    assert w.tick(clock_now[0], 5, cur, why) is None
    assert w.tick(clock_now[0], 70, cur, why) == \
        "Today: 15:30–21:30 → 13:30–18:00, 20:00–21:30 (saving session 18:00–20:00)"
