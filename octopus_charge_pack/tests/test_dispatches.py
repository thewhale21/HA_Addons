"""Planned dispatches into the sensors' values (src/dispatches.py), and the Octopus client
(src/octopus.py) with a fake API."""

import asyncio
import datetime

from src.dispatches import NO_DATE, dispatch_times, next_dispatch, parse_time, summarise
from src.octopus import AuthError, OctopusClient

UTC = datetime.timezone.utc
BST = datetime.timezone(datetime.timedelta(hours=1))
NOW = datetime.datetime(2026, 10, 15, 12, 0, tzinfo=UTC)

DISPATCHES = [
    {"start": "2026-10-15T10:00:00Z", "end": "2026-10-15T11:00:00Z", "type": "SMART", "energyAddedKwh": 2.0},  # over
    {"start": "2026-10-15T13:00:00+00:00", "end": "2026-10-15T13:30:00+00:00", "type": "SMART",
     "energyAddedKwh": -3.5},
    {"start": "2026-10-15T14:00:00Z", "end": "2026-10-15T14:30:00Z", "type": "SMART", "energyAddedKwh": 1.5},
]


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_times_from_the_api_are_read():
    assert parse_time("2026-10-15T13:00:00Z") == datetime.datetime(2026, 10, 15, 13, tzinfo=UTC)
    assert parse_time("2026-10-15T14:00:00+01:00").utcoffset() == datetime.timedelta(hours=1)
    assert parse_time("") is None and parse_time(None) is None and parse_time("soon") is None


def test_next_charge_and_discharge_like_the_templates():
    # charge: energyAddedKwh below 0; discharge: above 0; only ones that haven't ended
    assert next_dispatch(DISPATCHES, "charge", NOW)["energyAddedKwh"] == -3.5
    assert next_dispatch(DISPATCHES, "discharge", NOW)["start"] == "2026-10-15T14:00:00Z"
    assert next_dispatch(DISPATCHES, "discharge", NOW.replace(hour=15)) is None
    assert next_dispatch([], "charge", NOW) is None and next_dispatch(None, "charge", NOW) is None


def test_dispatch_dates_and_times_in_local_time():
    d = {"start": "2026-10-15T14:00:00Z", "end": "2026-10-15T14:30:00Z"}
    assert dispatch_times(d, BST, {}) == {"start_date": "2026-10-15", "end_date": "2026-10-15", "date": "2026-10-15",
                                          "start_time": "15:00:00", "end_time": "15:30:00"}
    # Runs past midnight: the end date is the next day, at the real end time
    late = dispatch_times({"start": "2026-10-15T22:30:00Z", "end": "2026-10-15T23:30:00Z"}, BST, {})
    assert (late["start_date"], late["start_time"]) == ("2026-10-15", "23:30:00")
    assert (late["end_date"], late["end_time"]) == ("2026-10-16", "00:30:00")
    # None planned: 1999-01-01, the last start time kept, the end time = the start time
    none = dispatch_times(None, BST, {"start_time": "15:00:00"})
    assert none == {"start_date": NO_DATE, "end_date": NO_DATE, "date": NO_DATE,
                    "start_time": "15:00:00", "end_time": "15:00:00"}
    assert dispatch_times(None, BST, {})["start_time"] is None


def test_summary_for_the_sensors():
    s = summarise(DISPATCHES, NOW, BST, {"discharge_start_time": "09:00:00"})
    assert s["count"] == 3 and s["dispatches"] == DISPATCHES
    assert (s["charge_start"], s["charge_end"]) == ("2026-10-15T13:00:00+00:00", "2026-10-15T13:30:00+00:00")
    assert (s["discharge_start"], s["discharge_kwh"]) == ("2026-10-15T14:00:00Z", 1.5)
    assert (s["discharge_date"], s["discharge_start_time"], s["discharge_end_time"]) == ("2026-10-15", "15:00:00", "15:30:00")
    # The charge gets the same date and times
    assert (s["charge_start_date"], s["charge_end_date"], s["charge_start_time"], s["charge_end_time"],
            s["charge_kwh"]) == ("2026-10-15", "2026-10-15", "14:00:00", "14:30:00", -3.5)
    empty = summarise([], NOW, BST, {"discharge_start_time": "09:00:00", "charge_start_time": "01:00:00"})
    assert empty["count"] == 0 and empty["charge_start"] is None
    assert (empty["discharge_date"], empty["discharge_start_time"], empty["discharge_end_time"]) == (NO_DATE, "09:00:00", "09:00:00")
    assert (empty["charge_date"], empty["charge_start_time"], empty["charge_end_time"]) == (NO_DATE, "01:00:00", "01:00:00")


class FakeOctopus(OctopusClient):
    """Answers like the API: a token for the right key, dispatches for a good token."""

    def __init__(self, api_key, replies=None):
        super().__init__(api_key)
        self.calls, self.replies, self.tokens = [], list(replies or []), 0

    async def _post(self, query, variables=None, token=None):
        self.calls.append((query.split("(")[0].split()[-1], token))
        if "obtainKrakenToken" in query:
            if variables["apiKey"] != "sk_live_good":
                return {"errors": [{"message": "Invalid API key."}], "data": {"obtainKrakenToken": None}}
            self.tokens += 1
            return {"data": {"obtainKrakenToken": {"token": f"tok{self.tokens}"}}}
        if self.replies:
            return self.replies.pop(0)
        if "viewer" in query:
            return {"data": {"viewer": {"accounts": [{"number": "A-1"}]}}}
        if "devices" in query:
            return {"data": {"devices": [{"id": "dev-1", "name": "Battery", "deviceType": "BATTERIES"}]}}
        return {"data": {"flexPlannedDispatches": DISPATCHES}}


def test_the_client_gets_a_token_and_the_dispatches():
    c = FakeOctopus("sk_live_good")
    assert _run(c.planned_dispatches("dev-1")) == DISPATCHES
    assert _run(c.planned_dispatches("dev-1")) == DISPATCHES
    assert c.tokens == 1  # the token is reused until it's old
    assert c.calls[1][1] == "tok1"  # sent as the Authorization header


def test_an_expired_token_is_renewed_once():
    c = FakeOctopus("sk_live_good", replies=[{"errors": [{"message": "Signature of the JWT has expired."}]}])
    assert _run(c.planned_dispatches("dev-1")) == DISPATCHES and c.tokens == 2


def test_a_bad_api_key_is_reported():
    try:
        _run(FakeOctopus("sk_live_bad").planned_dispatches("dev-1"))
        raise AssertionError("should have failed")
    except AuthError as err:
        assert "Invalid API key" in str(err)
    try:
        _run(FakeOctopus("").planned_dispatches("dev-1"))
        raise AssertionError("should have failed")
    except AuthError as err:
        assert "No API key" in str(err)


def test_the_device_is_found_from_the_account():
    from src.reader import pick_device, read_once
    from src.shared_state import SharedState

    c = FakeOctopus("sk_live_good")
    assert _run(c.find_devices()) == [{"id": "dev-1", "name": "Battery", "deviceType": "BATTERIES", "account": "A-1"}]
    assert pick_device([{"id": "a"}]) == "a" and pick_device([{"id": "a"}, {"id": "b"}]) is None
    state, kept = SharedState(), {}
    _run(read_once(state, c, kept, None))  # nothing picked, one device: that one
    assert state.device_id == "dev-1" and state.summary["count"] == 3 and state.last_update
    assert state.devices[0]["id"] == "dev-1"  # listed for the page's drop-down
    assert {k: kept[k] for k in ("charge_start_time", "discharge_start_time")} == {
        "charge_start_time": state.summary["charge_start_time"],
        "discharge_start_time": state.summary["discharge_start_time"]}
    assert "completed" in kept and "tracking" in kept and state.completed == kept["completed"]


def test_the_device_picked_on_the_page_is_followed():
    from src.reader import read_once
    from src.shared_state import SharedState

    class TwoDevices(FakeOctopus):
        async def _post(self, query, variables=None, token=None):
            if "devices(" in query:
                self.calls.append(("devices", token))
                return {"data": {"devices": [{"id": "meter"}, {"id": "dev-1", "name": "Battery"}]}}
            if "flexPlannedDispatches" in query:
                self.calls.append(("dispatches", variables["deviceId"]))
            return await super()._post(query, variables, token)

    c, state = TwoDevices("sk_live_good"), SharedState()
    try:
        _run(read_once(state, c, {}, None))  # two devices and none picked: the page asks
        raise AssertionError("should have asked for a device")
    except ValueError as err:
        assert "Pick your device on the Settings tab" in str(err) and len(state.devices) == 2
    _run(read_once(state, c, {}, "dev-1"))
    assert state.device_id == "dev-1" and ("dispatches", "dev-1") in c.calls
    found = sum(1 for name, _ in c.calls if name == "devices")
    assert found == 1
    _run(read_once(state, c, {}, "dev-1"))  # the device list isn't read again each time
    assert sum(1 for name, _ in c.calls if name == "devices") == found


def test_device_and_interval_are_page_settings(tmp_path):
    from src.app_settings import AppSettings
    from src.config import Config

    s = AppSettings(str(tmp_path))
    assert (s.device_id, s.poll_seconds) == ("", 60)
    s.update({"device_id": " dev-1 ", "poll_seconds": "300"})
    assert (s.device_id, s.poll_seconds) == ("dev-1", 300)
    assert AppSettings(str(tmp_path)).poll_seconds == 300  # saved
    for bad in ({"poll_seconds": 5}, {"poll_seconds": "x"}, {"device_id": "a b"}, {"device_id": 3}):
        try:
            s.update(bad)
            raise AssertionError(f"should have refused {bad}")
        except ValueError:
            pass

    # The options from before 0.3.0 are copied over once, and never again
    fresh = AppSettings(str(tmp_path / "x")) if (tmp_path / "x").mkdir() is None else None
    fresh.adopt_options(Config(api_key="k", device_id="dev-9", poll_seconds=120))
    assert (fresh.device_id, fresh.poll_seconds) == ("dev-9", 120)
    fresh.update({"poll_seconds": 600})
    again = AppSettings(str(tmp_path / "x"))
    again.adopt_options(Config(api_key="k", device_id="other", poll_seconds=30))
    assert (again.device_id, again.poll_seconds) == ("dev-9", 600)  # the page's choice stays


# --- completed sessions ---------------------------------------------------------------


def _d(start, end, kwh=5.0):
    return {"start": start, "end": end, "energyAddedKwh": kwh, "type": "SMART"}


def test_a_session_still_listed_at_its_end_is_completed():
    from src.dispatches import track_completed
    at = lambda hh, mm=0: datetime.datetime(2026, 10, 15, hh, mm, tzinfo=datetime.timezone.utc)
    kept = {}
    plan = [_d("2026-10-15T17:00:00Z", "2026-10-15T18:00:00Z"), _d("2026-10-15T20:00:00Z", "2026-10-15T21:00:00Z", -3)]
    assert track_completed(kept, plan, at(16), 180) == []  # not started: not followed
    assert track_completed(kept, plan, at(17, 30), 180) == []
    assert track_completed(kept, plan, at(17, 59), 180) == []  # still listed just before its end
    done = track_completed(kept, plan[1:], at(18, 1), 180)  # gone from the list once it ended
    assert [(c["start"], c["kind"]) for c in done] == [("2026-10-15T17:00:00Z", "discharge")]
    # the charge, taken off the plan half-way: it didn't happen
    track_completed(kept, plan[1:], at(20, 10), 180)
    assert track_completed(kept, [], at(21, 1), 180) == []
    assert [c["start"] for c in kept["completed"]] == ["2026-10-15T17:00:00Z"] and kept["tracking"] == {}


def test_a_session_whose_end_moves_later_is_one_session():
    from src.dispatches import track_completed
    at = lambda hh, mm=0: datetime.datetime(2026, 10, 15, hh, mm, tzinfo=datetime.timezone.utc)
    kept = {}
    track_completed(kept, [_d("2026-10-15T17:00:00Z", "2026-10-15T17:30:00Z")], at(17, 10), 180)
    track_completed(kept, [_d("2026-10-15T17:00:00Z", "2026-10-15T18:30:00Z", 9)], at(18, 29), 180)
    done = track_completed(kept, [], at(18, 31), 180)
    assert len(done) == 1 and done[0]["end"] == "2026-10-15T18:30:00Z" and done[0]["energyAddedKwh"] == 9
    # old ones are forgotten
    track_completed(kept, [], at(18, 31) + datetime.timedelta(days=31), 180)
    assert kept["completed"] == []


def test_idle_dispatches_arent_sessions():
    from src.dispatches import track_completed
    at = lambda hh, mm=0: datetime.datetime(2026, 10, 15, hh, mm, tzinfo=datetime.timezone.utc)
    kept = {}
    track_completed(kept, [_d("2026-10-15T15:00:00Z", "2026-10-15T16:00:00Z", 0.0)], at(15, 59), 180)
    assert track_completed(kept, [], at(16, 1), 180) == [] and kept["completed"] == []


# --- now, plan changes, the calendar -------------------------------------------------

def _at(hh, mm=0, day=15):
    return datetime.datetime(2026, 10, day, hh, mm, tzinfo=datetime.timezone.utc)


def test_what_its_doing_now():
    from src.dispatches import now_values
    plan = [_d("2026-10-15T15:00:00+00:00", "2026-10-15T16:00:00+00:00", 0.0),
            _d("2026-10-15T22:30:00+00:00", "2026-10-15T23:00:00+00:00", "-0.5995")]
    assert now_values(plan, _at(15, 20))["now"] == "idle"
    v = now_values(plan, _at(22, 40))
    assert v["now"] == "charging" and v["now_minutes_left"] == 20 and v["now_kwh"] == -0.5995
    assert now_values(plan, _at(19))["now"] == "none"


def test_changes_to_the_plan_are_logged():
    from src.dispatches import track_changes
    kept = {}
    a = _d("2026-10-15T18:00:00Z", "2026-10-15T19:00:00Z", 4.4)
    b = _d("2026-10-15T22:30:00Z", "2026-10-15T23:00:00Z", -0.6)
    assert track_changes(kept, [a, b], _at(12)) == []  # the first read isn't a change
    a2 = dict(a, end="2026-10-15T19:30:00Z")
    c = _d("2026-10-16T00:30:00Z", "2026-10-16T01:30:00Z", 4.4)
    new = track_changes(kept, [a2, c], _at(13))
    assert [(x["change"], x["dispatch"]["start"]) for x in new] == [
        ("changed", "2026-10-15T18:00:00Z"), ("added", "2026-10-16T00:30:00Z"), ("removed", "2026-10-15T22:30:00Z")]
    assert new[0]["was"]["end"] == "2026-10-15T19:00:00Z" and kept["changes"][0]["at"] == "2026-10-15T13:00:00Z"
    # one that's ended dropping off isn't a change
    assert track_changes(kept, [c], _at(19, 31)) == []


def test_the_calendar_follows_the_plan():
    from src.calendar_sync import MARK, plan, summary
    a = _d("2026-10-15T18:00:00+00:00", "2026-10-15T19:00:00+00:00", 4.4)
    b = _d("2026-10-15T22:30:00+00:00", "2026-10-15T23:00:00+00:00", -0.6)
    idle = _d("2026-10-15T15:00:00+00:00", "2026-10-15T16:00:00+00:00", 0.0)
    assert summary(a) == "Discharge 4.40 kWh" and summary(b) == "Charge 0.60 kWh"
    ev = lambda s, e, t, uid, desc=MARK: {"start": {"dateTime": s}, "end": {"dateTime": e}, "summary": t, "uid": uid, "description": desc}
    events = [ev("2026-10-15T19:00:00+01:00", "2026-10-15T20:00:00+01:00", "Discharge 4.40 kWh", "1"),  # = a, in BST
              ev("2026-10-15T20:00:00+01:00", "2026-10-15T21:00:00+01:00", "Discharge 2.00 kWh", "2"),  # off the plan
              ev("2026-10-15T16:00:00+01:00", "2026-10-15T17:00:00+01:00", "Discharge 1.00 kWh", "3"),  # started: kept
              ev("2026-10-15T21:00:00+01:00", "2026-10-15T22:00:00+01:00", "Dinner", "4", "mine")]  # not ours
    delete, add = plan(events, [a, b, idle], _at(15, 30))
    assert [e["uid"] for e in delete] == ["2"] and add == [b]


def test_the_2nd_and_3rd_discharges():
    from src.dispatches import summarise
    from src.ha_entities import SENSORS
    plan = [_d("2026-10-15T18:00:00+00:00", "2026-10-15T19:00:00+00:00", 4.4),
            _d("2026-10-15T22:30:00+00:00", "2026-10-15T23:00:00+00:00", -0.6),
            _d("2026-10-15T23:30:00+00:00", "2026-10-16T00:30:00+00:00", 2.0)]
    s = summarise(plan, _at(12), datetime.timezone.utc, {})
    assert s["discharge_start_time"] == "18:00:00"
    assert (s["discharge_2_date"], s["discharge_2_start_time"], s["discharge_2_end_time"], s["discharge_2_end_date"]) == (
        "2026-10-15", "23:30:00", "00:30:00", "2026-10-16")
    assert (s["discharge_3_date"], s["discharge_3_start_time"], s["discharge_3_end_time"]) == ("1999-01-01", "00:00:00", "00:00:00")
    assert SENSORS["discharge_2_date"][0] == "sensor.next_discharge_dispatch_2_date"
    assert SENSORS["discharge_3_end_time"][0] == "sensor.next_discharge_dispatch_3_end_time"
