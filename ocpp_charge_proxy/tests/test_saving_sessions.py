import datetime

from src.automation import SAVING_SOURCE, Automation, ReplugOptions, validate_entry
from src.saving_sessions import find_calendar, is_saving_calendar, parse_events, supplier_of

TZ = datetime.timezone.utc


class Clock:
    def __init__(self, start):
        self.dt = start

    def now(self):
        return self.dt

    def epoch(self):
        return self.dt.timestamp()


def _automation(tmp_path=None, start=datetime.datetime(2026, 10, 5, 12, 0, tzinfo=TZ)):  # Monday
    clock = Clock(start)
    a = Automation(str(tmp_path) if tmp_path else None, ReplugOptions(), now=clock.now, clock=clock.epoch,
                   localize=lambda naive: naive.replace(tzinfo=TZ))
    return a, clock


def _at(day, hh, mm=0):
    return datetime.datetime(2026, 10, day, hh, mm, tzinfo=TZ)


def _session(day, h1, h2, m1=0, m2=0):
    return {"start": _at(day, h1, m1), "end": _at(day, h2, m2), "summary": "Saving session"}


def _windows(a):
    return [(x.strftime("%d %H:%M"), y.strftime("%d %H:%M")) for x, y in a.windows() if y > a._now()]


# --- finding the calendar and reading it -----------------------------------------


def test_calendars_found_by_name():
    assert is_saving_calendar("calendar.octopus_energy_a_1_octoplus_power_down")
    assert is_saving_calendar("calendar.octopus_energy_a_1_octoplus_saving_sessions")
    assert not is_saving_calendar("calendar.octopus_energy_a_1_octoplus_power_up")
    assert not is_saving_calendar("calendar.octopus_energy_a_1_octoplus_free_electricity_session")
    assert is_saving_calendar("calendar.eon_next_saver_sessions")
    assert is_saving_calendar("calendar.x", "EDF Demand Flexibility")
    assert not is_saving_calendar("calendar.family") and not is_saving_calendar("sensor.saving_session")
    assert supplier_of("calendar.eon_next_saver_sessions") == "E.ON Next"
    states = [{"entity_id": "calendar.octopus_energy_a_1_octoplus_saving_sessions"},
              {"entity_id": "calendar.octopus_energy_a_1_octoplus_power_down"}, {"entity_id": "calendar.home"}]
    assert find_calendar(states) == "calendar.octopus_energy_a_1_octoplus_power_down"
    assert find_calendar([{"entity_id": "calendar.home"}]) is None


def test_events_parsed():
    now = _at(5, 12)
    resp = {"calendar.x": {"events": [
        {"start": "2026-10-05T17:00:00+00:00", "end": "2026-10-05T18:00:00+00:00", "summary": "Saving Session"},
        {"start": "2026-10-04T17:00:00+00:00", "end": "2026-10-04T18:00:00+00:00"},  # over
        {"start": "2026-10-06", "end": "2026-10-07"},  # all day
        {"start": "2026-10-05T17:30:00+00:00", "end": "2026-10-05T18:30:00+00:00"},  # overlaps: merged
    ]}}
    out = parse_events(resp, "calendar.x", now)
    assert [(s["start"].hour, s["end"].hour, s["end"].minute) for s in out] == [(17, 18, 30)]
    assert parse_events(None, "calendar.x", now) == []


# --- the schedule around a session --------------------------------------------------


def test_slot_keeps_its_end_and_starts_earlier():
    a, _ = _automation()
    a.set_schedule(enabled=True, entries=[{"time": "15:30", "action": "plug"}, {"time": "21:30", "action": "unplug"}])
    assert a.sync_saving_sessions([_session(5, 18, 19)], block=True)
    assert _windows(a)[:2] == [("05 14:30", "05 18:00"), ("05 19:00", "05 21:30")]
    assert _windows(a)[2] == ("06 15:30", "06 21:30")  # only that day
    assert a.saving_sessions[0]["notes"][0] == "the 15:30–21:30 slot is now 14:30–18:00, 19:00–21:30"
    assert not a.sync_saving_sessions([_session(5, 18, 19)], block=True)  # nothing more to do
    # cancelled: put back
    assert a.sync_saving_sessions([], block=True)
    assert _windows(a)[0] == ("05 15:30", "05 21:30") and a.saving_sessions == []


def test_slot_moved_earlier_joins_the_slot_before():
    a, _ = _automation()
    a.set_schedule(enabled=True, entries=[{"time": "13:00", "action": "plug"}, {"time": "14:00", "action": "unplug"},
                                          {"time": "14:30", "action": "plug"}, {"time": "18:30", "action": "unplug"}])
    a.sync_saving_sessions([_session(5, 17, 18)], block=True)
    assert _windows(a)[:2] == [("05 13:00", "05 17:00"), ("05 18:00", "05 18:30")]


def test_slot_starting_in_a_session_moves_whole():
    a, _ = _automation()
    a.set_schedule(enabled=True, entries=[{"time": "17:30", "action": "plug"}, {"time": "18:30", "action": "unplug"}])
    a.sync_saving_sessions([_session(5, 17, 19)], block=True)
    assert _windows(a)[0] == ("05 16:00", "05 17:00")  # ends before the session instead


def test_block_off_puts_slots_back_and_charges_avoid_sessions():
    a, clock = _automation()
    a.set_schedule(enabled=True, entries=[{"time": "16:00", "action": "plug"}, {"time": "19:00", "action": "unplug"}])
    a.sync_saving_sessions([_session(5, 17, 18)], block=True)
    assert _windows(a)[:2] == [("05 15:00", "05 17:00"), ("05 18:00", "05 19:00")]
    a.sync_saving_sessions([_session(5, 17, 18)], block=False)
    assert _windows(a)[0] == ("05 16:00", "05 19:00")
    assert a.session_windows() == []
    # with it on, Charge now is planned around the session
    b, clock = _automation(start=_at(5, 16, 30))
    b.sync_saving_sessions([_session(5, 17, 18)], block=True)
    plan = b.plan_auto_plug(180)
    assert [(s["start"][11:16], s["end"][11:16]) for s in plan["segments"]] == [("16:30", "17:00"), ("18:00", "19:30")]
    assert any("saving session" in n for n in plan["notes"])


def test_saving_a_schedule_isnt_refused_for_a_session():
    a, _ = _automation()
    a.sync_saving_sessions([_session(5, 17, 18)], block=True)
    a.set_schedule(enabled=True, entries=[{"time": "16:00", "action": "plug"}, {"time": "19:00", "action": "unplug"}])
    a.sync_saving_sessions([_session(5, 17, 18)], block=True)
    assert _windows(a)[:2] == [("05 15:00", "05 17:00"), ("05 18:00", "05 19:00")]


def test_charge_before_a_session(tmp_path):
    a, clock = _automation(tmp_path, start=_at(5, 14, 0))
    a.sync_saving_sessions([_session(5, 17, 18)], block=True)
    assert a.saving_precharge_due(2) is None  # 3 hours away
    clock.dt = _at(5, 15, 0)
    record, minutes = a.saving_precharge_due(2)
    assert minutes == 120
    plan = a.plan_auto_plug(minutes, source=SAVING_SOURCE)
    assert plan["end"][11:16] == "17:00"
    a.mark_precharged(record, plan)
    assert a.saving_precharge_due(2) is None
    assert "charge before it from 15:00 to 17:00" in a.saving_sessions[0]["notes"]
    # remembered after a restart
    b = Automation(str(tmp_path), ReplugOptions(), now=clock.now, clock=clock.epoch,
                   localize=lambda naive: naive.replace(tzinfo=TZ))
    assert b.saving_sessions[0]["precharged"] and b.saving_block


def test_session_found_late_charges_for_what_is_left():
    a, clock = _automation(start=_at(5, 16, 20))
    a.sync_saving_sessions([_session(5, 17, 18)], block=True)
    assert a.saving_precharge_due(2)[1] == 40
    clock.dt = _at(5, 16, 50)
    b, _ = _automation(start=_at(5, 16, 50))
    b.sync_saving_sessions([_session(5, 17, 18)], block=True)
    assert b.saving_precharge_due(2) is None and b.saving_sessions[0]["precharged"]  # 10 minutes: too close


def test_session_already_running_unplugs_now():
    a, clock = _automation(start=_at(5, 16, 0))
    a.set_schedule(enabled=True, entries=[{"time": "15:00", "action": "plug"}, {"time": "18:00", "action": "unplug"}])
    clock.dt = _at(5, 16, 30)
    a.sync_saving_sessions([_session(5, 16, 17)], block=True)
    w = [(x.strftime("%H:%M"), y.strftime("%H:%M")) for x, y in a.windows() if y > _at(5, 15)]
    assert w[:2] == [("15:00", "16:31"), ("17:00", "18:29")]  # it had begun: carries on after its end
    assert "ends later" in a.saving_sessions[0]["notes"][0]


def test_turning_it_off_clears_everything():
    a, _ = _automation()
    a.set_schedule(enabled=True, entries=[{"time": "16:00", "action": "plug"}, {"time": "19:00", "action": "unplug"}])
    a.sync_saving_sessions([_session(5, 17, 18)], block=True)
    assert a.clear_saving_sessions()
    assert _windows(a)[0] == ("05 16:00", "05 19:00") and a.saving_sessions == [] and not a.saving_block
    assert not a.clear_saving_sessions()


def test_slots_moved_by_2_43_0_are_moved_again():
    a, _ = _automation()
    a.set_schedule(enabled=True, entries=[{"time": "15:30", "action": "plug"}, {"time": "21:30", "action": "unplug"}])
    a.sync_saving_sessions([_session(5, 18, 19)], block=True)
    r = a.saving_sessions[0]
    # as 2.43.0 left it: no version, its own one-offs (19:00-22:30)
    a._undo_session(r)
    extra = [validate_entry({"time": t, "date": "2026-10-05", "action": act}) for t, act in
             (("18:00", "unplug"), ("19:00", "plug"), ("22:30", "unplug"))]
    a.entries += extra
    a.skips.append({"entry_id": a.entries[1]["id"], "date": "2026-10-05"})
    r["changes"] = {"skips": [{"entry_id": a.entries[1]["id"], "date": "2026-10-05"}], "added": [e["id"] for e in extra]}
    del r["v"]
    assert a.sync_saving_sessions([_session(5, 18, 19)], block=True)
    assert _windows(a)[:2] == [("05 14:30", "05 18:00"), ("05 19:00", "05 21:30")]


def test_charge_before_a_session_only_adds_what_the_schedule_doesnt_cover():
    a, clock = _automation(start=_at(5, 12, 0))
    a.set_schedule(enabled=True, entries=[{"time": "15:30", "action": "plug"}, {"time": "21:30", "action": "unplug"}])
    a.sync_saving_sessions([_session(5, 18, 19)], block=True)  # 14:30-18:00, 19:00-21:30
    clock.dt = _at(5, 16, 0)
    assert a.saving_precharge_due(2) is None  # plugged in already
    assert a.saving_sessions[0]["precharged"] and "already" in a.saving_sessions[0]["notes"][-1]
    # partly covered: the charge joins the slot, adding only the missing hour
    b, clock = _automation(start=_at(5, 12, 0))
    b.set_schedule(enabled=True, entries=[{"time": "17:00", "action": "plug"}, {"time": "18:00", "action": "unplug"}])
    b.sync_saving_sessions([_session(5, 18, 19)], block=True)
    clock.dt = _at(5, 16, 0)
    record, minutes = b.saving_precharge_due(2)
    plan = b.plan_auto_plug(minutes, source=SAVING_SOURCE)
    assert plan["end"][11:16] == "18:00"
    assert [w for w in _windows(b) if w[0].startswith("05")] == [("05 16:00", "05 18:00")]


def test_start_in_the_past_ends_later_instead():
    a, clock = _automation(start=_at(5, 12, 0))
    a.set_schedule(enabled=True, entries=[{"time": "15:30", "action": "plug"}, {"time": "21:30", "action": "unplug"}])
    clock.dt = _at(5, 14, 40)  # 14:30 has gone
    a.sync_saving_sessions([_session(5, 18, 19)], block=True)
    assert [w for w in _windows(a) if w[0].startswith("05")] == [("05 15:30", "05 18:00"), ("05 19:00", "05 22:30")]
    assert "ends later" in a.saving_sessions[0]["notes"][0]


def test_ending_later_goes_around_a_no_charging_time_and_joins_the_next_slot():
    a, clock = _automation(start=_at(5, 12, 0))
    a.set_schedule(enabled=True, entries=[{"time": "15:30", "action": "plug"}, {"time": "21:30", "action": "unplug"},
                                          {"time": "23:00", "action": "plug"}, {"time": "23:30", "action": "unplug"}],
                   blocks=[{"start": "21:30", "end": "22:00"}])
    clock.dt = _at(5, 14, 40)
    a.sync_saving_sessions([_session(5, 18, 19)], block=True)
    assert [w for w in _windows(a) if w[0].startswith("05")] == [
        ("05 15:30", "05 18:00"), ("05 19:00", "05 21:30"), ("05 22:00", "05 23:30")]
    assert "joined with the next slot" in a.saving_sessions[0]["notes"][0]
