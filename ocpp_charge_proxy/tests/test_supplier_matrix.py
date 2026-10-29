"""The same scenarios with every supplier the add-on knows, an unlisted one and
none at all: how each one's integration is found, its daily limit (Octopus: 6
hours, reset at 12:00; the others: none unless set on the Settings tab, over
any 24 hours), its ready times (Octopus: any half hour; EDF and an unlisted
supplier: 04:00-11:00; E.ON Next: no ready time), and what the schedule, a
charge and the ready time then do with them.

Each scenario runs through what the add-on actually uses: HaLink finds the
supplier from Home Assistant's states (src/ha_link.py) and gives
smart_charging(); the schedule (src/automation.py) gets its limit, reset and
ready times from that, as __main__ and the API pass them."""
import asyncio
import datetime

import pytest

from src.automation import Automation, ReplugOptions, apply_ready_time
from src.ha_link import HaLink
from src.ready_time import ALL_DAY_TIMES
from src.shared_state import SharedState

TZ = datetime.timezone.utc
EDF_TIMES = [t for t in ALL_DAY_TIMES if "04:00" <= t <= "11:00"]


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _kraken(prefix, ready=True):
    """A Kraken-style integration's states (Octopus, EDF): the dispatching sensor and its ready time."""
    out = [{"entity_id": f"binary_sensor.{prefix}_intelligent_dispatching", "state": "off",
            "attributes": {"planned_dispatches": [], "completed_dispatches": []}}]
    if ready:
        out.append({"entity_id": f"time.{prefix}_intelligent_target_time", "state": "07:00:00", "attributes": {}})
    return out


# name -> (HA states, what the add-on should make of them)
SUPPLIERS = {
    "octopus": (_kraken("octopus_energy_a_1"),
                dict(provider="Octopus Energy", limit_min=360, limit_reset="12:00", has_ready_time=True,
                     ready_times=ALL_DAY_TIMES)),
    "edf": (_kraken("edf_energy_a_1"),
            dict(provider="EDF Energy", limit_min=None, limit_reset=None, has_ready_time=True,
                 ready_times=EDF_TIMES)),
    "eon": ([{"entity_id": "sensor.eon_next_123_smart_charging_schedule", "state": "off",
              "attributes": {"schedule": []}}],
            dict(provider="E.ON Next", limit_min=None, limit_reset=None, has_ready_time=False, ready_times=None)),
    "other": (_kraken("acme_power"),  # an unlisted supplier with a Kraken-style sensor
              dict(provider="Your supplier", limit_min=None, limit_reset=None, has_ready_time=True,
                   ready_times=EDF_TIMES)),
    "none": ([], None),
}
NAMES = list(SUPPLIERS)


class _HA:
    """Home Assistant's websocket, as far as finding the supplier and setting the ready time go."""

    def __init__(self, states):
        self.states = states
        self.calls = []

    async def __call__(self, msg, timeout=None):
        self.calls.append(msg)
        if msg.get("type") == "get_states":
            return self.states
        if msg.get("type") == "call_service":
            return {}
        return []


async def _noop(*a, **k):
    return None


def _link(name, **settings):
    link = HaLink(None, SharedState(), lambda kw: None, _noop, _noop, token="t")
    if settings:
        _run(link.update_settings(settings))
    ha = _HA(SUPPLIERS[name][0])
    link._call = ha
    _run(link._find_dispatch_sensor(ha))
    return link, ha


def _automation(now):
    clock = {"dt": now}
    a = Automation(None, ReplugOptions(), now=lambda: clock["dt"], clock=lambda: clock["dt"].timestamp(),
                   localize=lambda naive: naive.replace(tzinfo=TZ))
    return a, clock


def _at(day, h, m=0):
    return datetime.datetime(2026, 10, day, h, m, tzinfo=TZ)  # (Thu 8 Oct 2026 = day 8)


def _sched(a, sc, entries, **kw):
    """Save the schedule as the API does, with the supplier's limit, reset and ready times."""
    a.limit_reset = sc.get("limit_reset")
    a.set_schedule(entries=entries, ready_times=sc.get("ready_times"), provider=sc.get("provider") or "your supplier",
                   daily_cap_min=sc.get("limit_min"), **kw)


def _slot(start, end):
    return [{"time": start, "action": "plug"}, {"time": end, "action": "unplug"}]


# --- finding the supplier and what it allows ------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_each_supplier_is_found_with_its_limits_and_ready_times(name):
    link, _ = _link(name)
    sc = link.smart_charging()
    want = SUPPLIERS[name][1]
    if want is None:
        assert sc["found"] is False and "limit_min" not in sc
        return
    assert sc["found"] is True
    for key, value in want.items():
        assert sc[key] == value, key


@pytest.mark.parametrize("name", ["edf", "eon", "other"])
def test_a_limit_set_on_the_settings_tab_applies_to_any_supplier(name):
    link, _ = _link(name, daily_limit_h=4, limit_reset="00:00")
    sc = link.smart_charging()
    assert sc["limit_min"] == 240 and sc["limit_reset"] == "00:00"
    link, _ = _link(name, daily_limit_h=5, limit_reset="rolling", limit_hours=12)
    sc = link.smart_charging()
    assert sc["limit_min"] == 300 and sc["limit_reset"] == "12h"


def test_octopus_with_no_limit_set_on_the_settings_tab():
    link, _ = _link("octopus", daily_limit_h=0)  # 0: no limit
    assert link.smart_charging()["limit_min"] is None


# --- the schedule against each supplier's daily limit ---------------------------


@pytest.mark.parametrize("name", NAMES)
def test_seven_hours_a_day_with_the_ready_time_on(name):
    """Only Octopus (6 hours a day) refuses a 7 hour slot; the others have no limit.
    (02:00-09:00: it ends at a ready time every supplier accepts.)"""
    link, _ = _link(name)
    sc = link.smart_charging()
    a, _ = _automation(_at(8, 1))
    if name == "octopus":
        with pytest.raises(ValueError, match="6 hours"):
            _sched(a, sc, _slot("02:00", "09:00"), enabled=True, ready_time=True)
        assert not a.schedule_enabled
    else:
        _sched(a, sc, _slot("02:00", "09:00"), enabled=True, ready_time=True)
        assert a.schedule_enabled


@pytest.mark.parametrize("name", ["edf", "other"])
def test_unplug_times_must_be_ready_times_the_supplier_accepts(name):
    """With the ready time set by the schedule, EDF (and an unlisted supplier) only
    take 04:00-11:00: an unplug at 17:00 can't be one."""
    link, _ = _link(name)
    a, _ = _automation(_at(8, 1))
    with pytest.raises(ValueError, match="04:00 to 11:00"):
        _sched(a, link.smart_charging(), _slot("10:00", "17:00"), enabled=True, ready_time=True)


@pytest.mark.parametrize("name", NAMES)
def test_no_limit_while_the_ready_time_is_off(name):
    link, _ = _link(name)
    a, _ = _automation(_at(8, 8))
    _sched(a, link.smart_charging(), _slot("10:00", "17:00"), enabled=True, ready_time=False)
    assert a.schedule_enabled


def test_octopus_counts_its_day_from_12_00():
    """Its day runs 12:00 to 12:00: 08:00-14:00 every day is 2 hours (12-14) and the
    next morning's 4 (08-12) in each: 6, fine. 06:00-12:00 + 12:00-18:00 is 12."""
    link, _ = _link("octopus")
    sc = link.smart_charging()
    a, _ = _automation(_at(8, 7))
    _sched(a, sc, _slot("08:00", "14:00"), enabled=True, ready_time=True)
    with pytest.raises(ValueError, match="12h 00m in the day from"):
        _sched(a, sc, _slot("06:00", "12:00") + _slot("12:00", "18:00"), ready_time=True)
    with pytest.raises(ValueError, match="resets at 12:00"):
        _sched(a, sc, _slot("05:00", "12:00"), ready_time=True)


@pytest.mark.parametrize("name,reset,ok,over", [
    ("edf", "00:00", ("05:00", "09:00"), ("04:00", "09:00")),
    ("eon", "rolling", ("01:00", "05:00"), ("22:00", "03:00")),
    ("other", "00:00", ("05:00", "09:00"), ("04:00", "09:30")),
])
def test_a_limit_set_on_the_settings_tab_is_kept_to(name, reset, ok, over):
    """4 hours a day, set on the Settings tab: 4 is fine, more isn't."""
    link, _ = _link(name, daily_limit_h=4, limit_reset=reset)
    sc = link.smart_charging()
    a, _ = _automation(_at(8, 0, 30))
    _sched(a, sc, _slot(*ok), enabled=True, ready_time=True)
    with pytest.raises(ValueError, match="at most 4 hours"):
        _sched(a, sc, _slot(*over), ready_time=True)


# --- slots that meet: one charge, except where the limit resets -----------------


@pytest.mark.parametrize("name", NAMES)
def test_slots_meeting_at_12_00(name):
    """09:00-12:00 then 12:00-15:00: one charge to 15:00, but with Octopus it
    unplugs and plugs back in at 12:00 (its limit resets then), so the ready time
    is 12:00."""
    link, _ = _link(name)
    sc = link.smart_charging()
    a, _ = _automation(_at(8, 9, 30))
    _sched(a, sc, _slot("09:00", "12:00") + _slot("12:00", "15:00"), enabled=True)
    want = _at(8, 12) if name == "octopus" else _at(8, 15)
    assert a.next_unplug(_at(8, 9, 30)) == want


def test_slots_meeting_where_a_limit_set_on_the_settings_tab_resets():
    link, _ = _link("eon", daily_limit_h=6, limit_reset="15:00")
    sc = link.smart_charging()
    a, _ = _automation(_at(8, 13, 30))
    _sched(a, sc, _slot("13:00", "15:00") + _slot("15:00", "17:00"), enabled=True)
    assert a.next_unplug(_at(8, 13, 30)) == _at(8, 15)
    link, _ = _link("eon")  # (no limit: one charge)
    _sched(a, link.smart_charging(), _slot("13:00", "15:00") + _slot("15:00", "17:00"), enabled=True)
    assert a.next_unplug(_at(8, 13, 30)) == _at(8, 17)


# --- a charge (auto plug-in, Charge now) against each supplier -------------------


@pytest.mark.parametrize("name", NAMES)
def test_an_8_hour_charge(name):
    """At 08:10. Octopus: its limit resets at 12:00, so that's 3h50 one day and the
    rest the next: all 8 hours (to the half hour). EDF and an unlisted supplier end it
    at a ready time they accept (04:00-11:00: the next morning); E.ON Next and no
    supplier have neither: 8 hours, to the half hour."""
    link, _ = _link(name)
    sc = link.smart_charging()
    a, _ = _automation(_at(8, 8, 10))
    a.set_schedule(ready_time=True)
    a.limit_reset = sc.get("limit_reset")
    out = a.plan_auto_plug(480, sc.get("ready_times"), sc.get("limit_min"), sc.get("provider") or "your supplier")
    end = datetime.datetime.fromisoformat(out["ready_for"])
    if name == "octopus":
        assert end == _at(8, 16, 30) and "fresh charge from 12:00" in " ".join(out["notes"])
    elif name in ("edf", "other"):
        assert end == _at(9, 4, 0)  # 16:10 isn't a ready time it accepts: the next is 04:00
    else:
        assert end == _at(8, 16, 30)


def test_an_8_hour_charge_after_12_00_is_shortened_for_octopus():
    link, _ = _link("octopus")
    sc = link.smart_charging()
    a, _ = _automation(_at(8, 13))
    a.limit_reset = sc["limit_reset"]
    out = a.plan_auto_plug(480, sc["ready_times"], sc["limit_min"], sc["provider"])
    assert out["ready_for"].startswith("2026-10-08T19:00") and "6 hours" in " ".join(out["notes"])


# --- setting the ready time -------------------------------------------------------


@pytest.mark.parametrize("name,unplug,want", [
    ("octopus", _at(8, 22), "22:00"),
    ("octopus", _at(9, 7, 30), "07:30"),
    ("edf", _at(9, 7, 30), "07:30"),
    ("edf", _at(9, 13), "11:00"),  # (the latest it accepts before the unplug)
    ("edf", _at(8, 22), None),  # (none between now and then)
    ("other", _at(9, 6), "06:00"),
    ("eon", _at(8, 22), None),
    ("none", _at(8, 22), None),
])
def test_ready_time_set_for_each_supplier(name, unplug, want):
    """At 18:00: the latest ready time each supplier accepts, at or before the unplug."""
    link, ha = _link(name)
    out = _run(_ready(link, unplug))
    if want is None:
        assert out.get("error") and "ready" not in out
        assert not any(c.get("type") == "call_service" for c in ha.calls)
    else:
        assert out.get("ready") == want, out
        sent = [c for c in ha.calls if c.get("type") == "call_service"][-1]
        assert sent["service_data"] == {"time": want + ":00"}


async def _ready(link, unplug):
    real = datetime.datetime

    class _Now(real):
        @classmethod
        def now(cls, tz=None):
            return real(2026, 10, 8, 18, 0, tzinfo=tz or TZ)
    datetime.datetime = _Now
    try:
        return await link.set_ready_time(unplug)
    finally:
        datetime.datetime = real


@pytest.mark.parametrize("name", ["eon", "none"])
def test_no_ready_time_to_set_isnt_tried_again_and_again(name):
    """E.ON Next has no ready time and with no supplier there's nothing to set it on:
    that won't change in a few minutes, so it isn't tried again (Octopus's, failing
    for a moment, is)."""
    link, _ = _link(name)
    a, _ = _automation(_at(8, 18))
    a.set_schedule(entries=_slot("18:00", "22:00"), enabled=True)
    out = _run(apply_ready_time(a, link.set_ready_time, log_errors=False))
    assert out.get("error") and a.ready_retry is None


def test_a_failing_octopus_ready_time_is_tried_again():
    async def fails(unplug):
        return {"unplug": unplug.isoformat(), "error": "Home Assistant refused the ready time: timeout"}
    a, _ = _automation(_at(8, 18))
    a.set_schedule(entries=_slot("18:00", "22:00"), enabled=True)
    _run(apply_ready_time(a, fails, log_errors=False))
    assert a.ready_retry and a.ready_retry["tries"] == 1
