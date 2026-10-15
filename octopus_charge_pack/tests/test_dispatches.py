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
    _run(read_once(state, c, kept))
    assert state.device_id == "dev-1" and state.summary["count"] == 3 and state.last_update
    assert kept == {"charge_start_time": state.summary["charge_start_time"],
                    "discharge_start_time": state.summary["discharge_start_time"]}
