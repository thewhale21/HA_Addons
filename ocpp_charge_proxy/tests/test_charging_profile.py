"""Tests for ChargingProfileScheduler."""

import time
from unittest.mock import patch

from src.charging_profile import ChargingProfileScheduler


def _make_profile(
    kind="Relative",
    rate_unit="A",
    periods=None,
    stack_level=0,
    purpose="TxProfile",
    start_schedule=None,
    profile_id=None,
):
    """Build a charging profile dict (camelCase, as received from CSMS). Each
    purpose and stack level gets its own id unless one is given (a profile with
    the same id replaces the one kept)."""
    if periods is None:
        periods = [{"startPeriod": 0, "limit": 32.0}]
    if profile_id is None:
        profile_id = {"TxProfile": 0, "TxDefaultProfile": 100, "ChargePointMaxProfile": 200}.get(purpose, 300) + stack_level
    profile = {
        "chargingProfileId": profile_id,
        "stackLevel": stack_level,
        "chargingProfilePurpose": purpose,
        "chargingProfileKind": kind,
        "chargingSchedule": {
            "chargingRateUnit": rate_unit,
            "chargingSchedulePeriod": periods,
        },
    }
    if start_schedule:
        profile["chargingSchedule"]["startSchedule"] = start_schedule
    return profile


class TestBasicProfile:
    def test_no_profile_returns_none(self):
        sched = ChargingProfileScheduler()
        assert sched.get_current_limit_kw() is None

    def test_has_profile_false_when_empty(self):
        sched = ChargingProfileScheduler()
        assert sched.has_profile is False

    def test_has_profile_true_after_set(self):
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile())
        assert sched.has_profile is True

    def test_single_period_relative_amps(self):
        """Typical profile: Relative, 32A, single period."""
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile(kind="Relative", rate_unit="A", periods=[
            {"startPeriod": 0, "limit": 32.0}
        ]))
        limit = sched.get_current_limit_kw()
        assert limit is not None
        # 32A * 230V = 7360W = 7.36 kW
        assert abs(limit - 7.36) < 0.01

    def test_single_period_watts(self):
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile(kind="Relative", rate_unit="W", periods=[
            {"startPeriod": 0, "limit": 7400.0}
        ]))
        limit = sched.get_current_limit_kw()
        assert limit is not None
        assert abs(limit - 7.4) < 0.01

    def test_zero_limit_returns_zero(self):
        """A profile with limit=0 means pause charging."""
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile(kind="Relative", rate_unit="A", periods=[
            {"startPeriod": 0, "limit": 0.0}
        ]))
        limit = sched.get_current_limit_kw()
        assert limit == 0.0


class TestMultiPeriod:
    def test_multi_period_selects_correct_one(self):
        """With multiple periods, the one whose startPeriod <= elapsed is active."""
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile(kind="Relative", rate_unit="A", periods=[
            {"startPeriod": 0, "limit": 32.0},
            {"startPeriod": 3600, "limit": 0.0},   # pause after 1 hour
            {"startPeriod": 7200, "limit": 16.0},   # resume at 16A after 2 hours
        ]))

        # Just set, elapsed ~0s -> first period (32A)
        limit = sched.get_current_limit_kw()
        assert limit is not None
        assert abs(limit - 7.36) < 0.01

    def test_second_period_after_elapsed(self):
        """After enough time, the second period becomes active."""
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile(kind="Relative", rate_unit="A", periods=[
            {"startPeriod": 0, "limit": 32.0},
            {"startPeriod": 10, "limit": 0.0},
        ]))

        # Simulate 15 seconds passing
        sched._profiles[0]["_set_at"] -= 15
        limit = sched.get_current_limit_kw()
        assert limit == 0.0


class TestSnakeCaseKeys:
    def test_snake_case_profile(self):
        """The ocpp library may deliver keys in snake_case."""
        profile = {
            "charging_profile_id": 1,
            "stack_level": 0,
            "charging_profile_purpose": "TxProfile",
            "charging_profile_kind": "Relative",
            "charging_schedule": {
                "charging_rate_unit": "A",
                "charging_schedule_period": [
                    {"start_period": 0, "limit": 16.0}
                ],
            },
        }
        sched = ChargingProfileScheduler()
        sched.set_profile(profile)
        limit = sched.get_current_limit_kw()
        assert limit is not None
        # 16A * 230V = 3680W = 3.68 kW
        assert abs(limit - 3.68) < 0.01


class TestClearProfile:
    def test_clear_all(self):
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile(stack_level=0))
        sched.set_profile(_make_profile(stack_level=1))
        sched.clear_profile()
        assert sched.has_profile is False

    def test_clear_by_stack_level(self):
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile(stack_level=0))
        sched.set_profile(_make_profile(stack_level=1))
        sched.clear_profile(stack_level=0)
        assert sched.has_profile is True
        assert [sched.stack(q) for q in sched._profiles] == [1]

    def test_clear_by_purpose(self):
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile(purpose="TxProfile", stack_level=0))
        sched.set_profile(_make_profile(purpose="ChargePointMaxProfile", stack_level=1))
        sched.clear_profile(purpose="TxProfile")
        assert len(sched._profiles) == 1


class TestStackLevelPriority:
    def test_higher_stack_level_wins(self):
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile(
            stack_level=0, rate_unit="A",
            periods=[{"startPeriod": 0, "limit": 32.0}]
        ))
        sched.set_profile(_make_profile(
            stack_level=1, rate_unit="A",
            periods=[{"startPeriod": 0, "limit": 16.0}]
        ))
        limit = sched.get_current_limit_kw()
        # Stack level 1 (16A) should win over stack level 0 (32A)
        assert abs(limit - 3.68) < 0.01


# --- OCPP 1.6 § 3.13: purposes, recurring, validity, the composite schedule ---

def _iso(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestPurposes:
    def test_tx_profile_overrides_the_default(self):
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile(purpose="TxDefaultProfile", periods=[{"startPeriod": 0, "limit": 0.0}]))
        assert sched.get_current_limit_kw() == 0.0  # (the default: paused)
        sched.set_profile(_make_profile(purpose="TxProfile", periods=[{"startPeriod": 0, "limit": 16.0}]))
        assert abs(sched.get_current_limit_kw() - 3.68) < 0.01

    def test_the_cap_always_applies(self):
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile(purpose="TxProfile", periods=[{"startPeriod": 0, "limit": 32.0}]))
        sched.set_profile(_make_profile(purpose="ChargePointMaxProfile", periods=[{"startPeriod": 0, "limit": 10.0}]))
        assert abs(sched.get_current_limit_kw() - 2.3) < 0.01

    def test_cap_alone(self):
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile(purpose="ChargePointMaxProfile", periods=[{"startPeriod": 0, "limit": 10.0}]))
        assert abs(sched.get_current_limit_kw() - 2.3) < 0.01

    def test_session_end_keeps_the_default_and_cap(self):
        sched = ChargingProfileScheduler()
        for purpose in ("TxProfile", "TxDefaultProfile", "ChargePointMaxProfile"):
            sched.set_profile(_make_profile(purpose=purpose))
        sched.transaction_ended()
        assert sorted(sched.purpose(q) for q in sched._profiles) == ["ChargePointMaxProfile", "TxDefaultProfile"]
        assert [sched.purpose(q) for q in sched.to_store()] == ["TxDefaultProfile", "ChargePointMaxProfile"]

    def test_same_id_replaces(self):
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile(purpose="TxDefaultProfile", stack_level=0, profile_id=7))
        sched.set_profile(_make_profile(purpose="TxDefaultProfile", stack_level=2, profile_id=7))
        assert sched.count() == 1 and sched.stack(sched._profiles[0]) == 2

    def test_saved_and_loaded(self):
        changes = []
        sched = ChargingProfileScheduler(on_change=lambda: changes.append(1))
        sched.set_profile(_make_profile(purpose="TxDefaultProfile", periods=[{"startPeriod": 0, "limit": 8.0}]))
        sched.set_profile(_make_profile(purpose="TxProfile"))  # (not saved: it ends with its session)
        assert len(changes) == 1
        other = ChargingProfileScheduler()
        other.load(sched.to_store())
        assert abs(other.get_current_limit_kw() - 1.84) < 0.01

    def test_lower_stack_used_when_the_higher_has_ended(self):
        sched = ChargingProfileScheduler()
        now = time.time()
        sched.set_profile(_make_profile(purpose="TxDefaultProfile", stack_level=0, kind="Absolute",
                                        start_schedule=_iso(now - 60), periods=[{"startPeriod": 0, "limit": 16.0}]))
        p = _make_profile(purpose="TxDefaultProfile", stack_level=1, kind="Absolute",
                          start_schedule=_iso(now - 60), periods=[{"startPeriod": 0, "limit": 6.0}])
        p["chargingSchedule"]["duration"] = 30  # (over 30 s ago)
        sched.set_profile(p)
        assert abs(sched.get_current_limit_kw() - 3.68) < 0.01


class TestTiming:
    def test_valid_from_and_to(self):
        sched = ChargingProfileScheduler()
        p = _make_profile(purpose="TxDefaultProfile", periods=[{"startPeriod": 0, "limit": 0.0}])
        p["validFrom"] = _iso(time.time() + 3600)
        sched.set_profile(p)
        assert sched.get_current_limit_kw() is None  # (not yet valid)
        p["validFrom"] = _iso(time.time() - 7200)
        p["validTo"] = _iso(time.time() - 3600)
        sched.set_profile(p)
        assert sched.get_current_limit_kw() is None  # (no longer valid)

    def test_daily_recurring(self):
        sched = ChargingProfileScheduler()
        now = time.time()
        # Started 2 days and 1 hour ago: pause for the first 2 hours of each day
        p = _make_profile(purpose="TxDefaultProfile", kind="Recurring", start_schedule=_iso(now - 2 * 86400 - 3600),
                          periods=[{"startPeriod": 0, "limit": 0.0}, {"startPeriod": 7200, "limit": 16.0}])
        p["recurrencyKind"] = "Daily"
        sched.set_profile(p)
        assert sched.get_current_limit_kw() == 0.0
        assert abs(sched.limit_w_at(now + 2 * 3600) - 3680) < 1

    def test_relative_runs_from_the_session_start(self):
        sched = ChargingProfileScheduler()
        sched.set_profile(_make_profile(purpose="TxDefaultProfile", kind="Relative",
                                        periods=[{"startPeriod": 0, "limit": 32.0}, {"startPeriod": 600, "limit": 6.0}]))
        sched.transaction_started(time.time() - 900)
        assert abs(sched.get_current_limit_kw() - 1.38) < 0.01


class TestComposite:
    def test_changes_listed_from_now(self):
        sched = ChargingProfileScheduler()
        now = int(time.time())  # (whole seconds, as times are sent)
        sched.set_profile(_make_profile(purpose="TxDefaultProfile", kind="Absolute", start_schedule=_iso(now - 10),
                                        periods=[{"startPeriod": 0, "limit": 16.0}, {"startPeriod": 610, "limit": 0.0}]))
        sched.set_profile(_make_profile(purpose="ChargePointMaxProfile", kind="Absolute", start_schedule=_iso(now - 10),
                                        periods=[{"startPeriod": 0, "limit": 32.0}, {"startPeriod": 310, "limit": 10.0}]))
        steps = sched.composite(now, 3600)
        assert [(o, round(w)) for o, w in steps] == [(0, 3680), (300, 2300), (600, 0)]

    def test_nothing_set(self):
        assert ChargingProfileScheduler().composite(time.time(), 600) == [(0, None)]
