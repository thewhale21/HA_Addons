import datetime

from src.automation import Automation
from src.plan_check import check_plan

TZ = datetime.timezone.utc


def _at(h, m=0, day=5):
    return datetime.datetime(2026, 10, day, h, m, tzinfo=TZ)


def _slot(a, b):
    return {"start": a.isoformat(), "end": b.isoformat()}


def test_slots_inside_the_stretch_are_fine():
    out = check_plan([_slot(_at(16), _at(17, 30))], _at(16), _at(18))
    assert out["status"] == "ok" and out["problems"] == [] and out["slots"][0]["ok"]


def test_slot_past_the_unplug_is_an_error():
    out = check_plan([_slot(_at(16), _at(17)), _slot(_at(17, 30), _at(19))], _at(16), _at(18),
                     provider="Octopus Energy")
    assert out["status"] == "error"
    assert out["problems"] == ["Octopus Energy plans a slot 17:30–19:00, past the schedule's unplug at 18:00"]
    assert [s["ok"] for s in out["slots"]] == [True, False]


def test_only_up_to_the_ready_time():
    # Stretches 16-18 and 20-22: the 20:00 slot belongs to the next stretch
    out = check_plan([_slot(_at(16), _at(17)), _slot(_at(20), _at(21))], _at(16), _at(18), until=_at(18))
    assert out["status"] == "ok" and len(out["slots"]) == 1
    # Nothing before the ready time
    assert check_plan([_slot(_at(20), _at(21))], _at(16), _at(18))["status"] == "none"
    assert check_plan([], _at(16), _at(18))["status"] == "none"


def test_a_minute_over_is_tolerated():
    assert check_plan([_slot(_at(17), _at(18, 1))], _at(16), _at(18))["status"] == "ok"


def test_ready_time_changed_on_the_supplier_side():
    out = check_plan([_slot(_at(16), _at(17))], _at(16), _at(18), ready_set="18:00", supplier_ready="07:00:00")
    assert out["status"] == "error" and "ready time is 07:00, not the 18:00" in out["problems"][0]
    assert check_plan([], _at(16), _at(18), ready_set="18:00", supplier_ready="18:00:00")["status"] == "none"
    assert check_plan([], _at(16), _at(18), ready_set="18:00", supplier_ready="unavailable")["status"] == "none"


class Clock:
    def __init__(self, start):
        self.dt = start

    def now(self):
        return self.dt

    def epoch(self):
        return self.dt.timestamp()


def _automation(clock, ready_time=True):
    a = Automation(None, now=clock.now, clock=clock.epoch, localize=lambda naive: naive.replace(tzinfo=TZ))
    every = list(range(7))
    a.set_schedule(enabled=True, ready_time=ready_time, entries=[
        {"time": t, "action": act, "days": every}
        for t, act in (("16:00", "plug"), ("18:00", "unplug"), ("20:00", "plug"), ("22:00", "unplug"))])
    return a


def _plan(*slots, ready=None):
    return {"found": True, "provider": "Octopus Energy", "slots": list(slots), "supplier_ready": ready}


def test_automation_checks_the_current_stretch():
    clock = Clock(_at(16, 2))
    a = _automation(clock)
    a.ready_status = {"ready": "18:00", "ready_at": _at(18).isoformat(), "at": _at(16).isoformat()}
    bad = _plan(_slot(_at(17), _at(19)), _slot(_at(20), _at(21)), ready="18:00:00")
    # Just plugged in: give the supplier time to plan
    assert a.update_plan_check(bad, plugged_in=True)["status"] == "waiting"
    clock.dt = _at(16, 10)
    out = a.update_plan_check(bad, plugged_in=True)
    assert out["status"] == "error" and len(out["problems"]) == 1 and "17:00–19:00" in out["problems"][0]
    assert a.snapshot()["schedule"]["plan_check"]["status"] == "error"
    assert a.update_plan_check(_plan(_slot(_at(16, 30), _at(17, 30)), ready="18:00"), True)["status"] == "ok"
    # Supplier's ready time changed in its app
    assert "ready time is 07:00" in a.update_plan_check(_plan(ready="07:00"), True)["problems"][0]
    # Not plugged in, or between stretches: nothing to check
    assert a.update_plan_check(bad, plugged_in=False) is None
    clock.dt = _at(19)
    assert a.update_plan_check(bad, plugged_in=True) is None
    # The second stretch is checked from 20:00, up to its own unplug
    clock.dt = _at(20, 10)
    a.ready_status = {"ready": "22:00", "ready_at": _at(22).isoformat(), "at": _at(20).isoformat()}
    out = a.update_plan_check(_plan(_slot(_at(20), _at(21)), _slot(_at(23), _at(23, 30)), ready="22:00"), True)
    assert out["status"] == "ok" and len(out["slots"]) == 1 and out["until"].startswith("2026-10-05T22:00")


def test_automation_plan_check_only_with_force_on():
    clock = Clock(_at(16, 10))
    a = _automation(clock, ready_time=False)
    assert a.update_plan_check(_plan(_slot(_at(17), _at(19))), plugged_in=True) is None
    a.ready_time = True
    assert a.update_plan_check({"found": False}, plugged_in=True) is None
    # Ready time from an earlier stretch: check up to the unplug, ignore its ready time
    a.ready_status = {"ready": "07:00", "ready_at": _at(7, day=5).isoformat(), "at": _at(6, day=5).isoformat()}
    out = a.update_plan_check(_plan(_slot(_at(17), _at(19)), ready="07:00"), plugged_in=True)
    assert out["status"] == "error" and len(out["problems"]) == 1 and out["until"].startswith("2026-10-05T18:00")
