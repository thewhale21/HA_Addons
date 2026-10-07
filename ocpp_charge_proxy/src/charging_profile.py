from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)


_FLOAT_KEYS = {"limit", "min_charging_rate", "minChargingRate"}
_INT_KEYS = {"start_period", "startPeriod", "stack_level", "stackLevel", "charging_profile_id",
             "chargingProfileId", "duration", "number_phases", "numberPhases", "transaction_id",
             "transactionId"}


def normalise_profile(obj, key=None):
    """A charging profile with plain numbers: the ocpp library gives Decimals
    (saved to disk as text), and a profile read back may have numbers as text."""
    if isinstance(obj, dict):
        return {k: normalise_profile(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalise_profile(v, key) for v in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, Decimal) or (isinstance(obj, str) and key in _FLOAT_KEYS | _INT_KEYS):
        try:
            f = float(obj)
        except ValueError:
            return obj
        return int(f) if key in _INT_KEYS and f.is_integer() else f
    return obj


def _get(d: dict, *keys):
    """Get a value trying multiple key formats (snake_case and camelCase)."""
    for key in keys:
        if key in d:
            return d[key]
    return None


class ChargingProfileScheduler:
    """Manages OCPP 1.6 charging profiles and determines current power limit.

    Handles both camelCase (raw JSON) and snake_case (ocpp library parsed)
    key formats, since the profile dict may arrive in either form depending
    on context.
    """

    def __init__(self, rated_power_w: float = 7400.0):
        self._rated_power_w = rated_power_w
        self._profiles: dict[int, dict] = {}  # stack_level -> profile
        self._profile_start_times: dict[int, float] = {}  # stack_level -> monotonic time

    def set_profile(self, profile: dict) -> None:
        """Store a charging profile."""
        profile = normalise_profile(profile)
        profile_id = _get(profile, "charging_profile_id", "chargingProfileId", 0)
        stack_level = _get(profile, "stack_level", "stackLevel") or 0
        purpose = _get(profile, "charging_profile_purpose", "chargingProfilePurpose")
        kind = _get(profile, "charging_profile_kind", "chargingProfileKind")

        schedule = _get(profile, "charging_schedule", "chargingSchedule") or {}
        periods = _get(schedule, "charging_schedule_period", "chargingSchedulePeriod") or []
        start = _get(schedule, "start_schedule", "startSchedule")
        rate_unit = _get(schedule, "charging_rate_unit", "chargingRateUnit") or "W"

        logger.info(
            "Charging profile set: id=%s purpose=%s kind=%s",
            profile_id, purpose, kind,
        )
        logger.info(
            "  Schedule: unit=%s start=%s periods=%d",
            rate_unit, start, len(periods),
        )
        for p in periods:
            limit = _get(p, "limit") or 0
            start_period = _get(p, "start_period", "startPeriod") or 0
            if rate_unit == "A":
                limit_display = f"{limit}A (~{limit * 230 / 1000:.1f}kW)"
            else:
                limit_display = f"{limit}W ({limit / 1000:.1f}kW)"
            logger.info("    offset=%ds limit=%s", start_period, limit_display)

        self._profiles[stack_level] = profile
        self._profile_start_times[stack_level] = time.monotonic()

    def clear_profile(
        self,
        profile_id: Optional[int] = None,
        connector_id: Optional[int] = None,
        purpose: Optional[str] = None,
        stack_level: Optional[int] = None,
    ) -> None:
        """Clear charging profiles matching the given criteria."""
        if profile_id is not None:
            self._profiles = {
                k: v for k, v in self._profiles.items()
                if _get(v, "charging_profile_id", "chargingProfileId") != profile_id
            }
        elif stack_level is not None:
            self._profiles.pop(stack_level, None)
            self._profile_start_times.pop(stack_level, None)
        elif purpose is not None:
            self._profiles = {
                k: v for k, v in self._profiles.items()
                if _get(v, "charging_profile_purpose", "chargingProfilePurpose") != purpose
            }
        else:
            self._profiles.clear()
            self._profile_start_times.clear()
        logger.info("Charging profiles cleared (remaining: %d)", len(self._profiles))

    def get_current_limit_kw(self) -> Optional[float]:
        """Evaluate all active profiles and return the current power limit in kW.

        Returns None if no profile is active (charge at rated power).
        Returns 0.0 if the profile says to pause.
        Returns a positive value for the allowed power.
        """
        if not self._profiles:
            return None

        now_mono = time.monotonic()
        now_utc = datetime.now(timezone.utc)

        # Evaluate highest stack level profile (highest priority)
        for stack_level in sorted(self._profiles.keys(), reverse=True):
            profile = self._profiles[stack_level]
            limit_w = self._evaluate_profile(profile, now_utc, now_mono, stack_level)
            if limit_w is not None:
                return float(limit_w) / 1000.0

        return None

    def _evaluate_profile(
        self, profile: dict, now_utc: datetime, now_mono: float, stack_level: int
    ) -> Optional[float]:
        """Evaluate a single profile at the given time. Returns watts or None."""
        schedule = _get(profile, "charging_schedule", "chargingSchedule") or {}
        periods = _get(schedule, "charging_schedule_period", "chargingSchedulePeriod") or []
        if not periods:
            return None

        rate_unit = _get(schedule, "charging_rate_unit", "chargingRateUnit") or "W"
        kind = _get(profile, "charging_profile_kind", "chargingProfileKind") or "Absolute"

        # Determine elapsed seconds since schedule start
        if kind == "Relative":
            # Relative to when the profile was set
            set_time = self._profile_start_times.get(stack_level)
            if set_time is None:
                return None
            elapsed_seconds = now_mono - set_time
        else:
            # Absolute — use startSchedule
            start_str = _get(schedule, "start_schedule", "startSchedule")
            if start_str:
                start_time = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                elapsed_seconds = (now_utc - start_time).total_seconds()
            else:
                return None

        if elapsed_seconds < 0:
            return None

        # Find the active period (last period whose startPeriod <= elapsed)
        sorted_periods = sorted(
            periods,
            key=lambda p: _get(p, "start_period", "startPeriod") or 0,
        )
        active_period = None
        for period in sorted_periods:
            if (_get(period, "start_period", "startPeriod") or 0) <= elapsed_seconds:
                active_period = period
            else:
                break

        if active_period is None:
            return None

        limit = float(_get(active_period, "limit") or 0)

        # Convert amps to watts if needed
        if rate_unit == "A":
            limit = limit * 230  # UK single phase

        return limit

    def profiles_info(self) -> list[dict]:
        """Active profiles for the web GUI, highest priority first."""
        out = []
        now_mono = time.monotonic()
        for level in sorted(self._profiles, reverse=True):
            profile = self._profiles[level]
            schedule = _get(profile, "charging_schedule", "chargingSchedule") or {}
            periods = _get(schedule, "charging_schedule_period", "chargingSchedulePeriod") or []
            kind = _get(profile, "charging_profile_kind", "chargingProfileKind") or "Absolute"
            start = _get(schedule, "start_schedule", "startSchedule")
            set_mono = self._profile_start_times.get(level)
            if kind == "Relative" and set_mono is not None:
                start = (datetime.now(timezone.utc).timestamp() - (now_mono - set_mono))
                start = datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            out.append({
                "stack_level": level,
                "profile_id": _get(profile, "charging_profile_id", "chargingProfileId"),
                "purpose": _get(profile, "charging_profile_purpose", "chargingProfilePurpose"),
                "kind": kind,
                "unit": _get(schedule, "charging_rate_unit", "chargingRateUnit") or "W",
                "start": start,
                "duration_s": _get(schedule, "duration"),
                "min_rate": _get(schedule, "min_charging_rate", "minChargingRate"),
                "periods": [
                    {
                        "start_period": _get(p, "start_period", "startPeriod") or 0,
                        "limit": _get(p, "limit"),
                        "phases": _get(p, "number_phases", "numberPhases"),
                    }
                    for p in periods
                ],
            })
        return out

    @property
    def has_profile(self) -> bool:
        return len(self._profiles) > 0

    @property
    def profile_summary(self) -> str:
        """Human-readable summary of active profiles."""
        if not self._profiles:
            return "No active profiles"
        lines = []
        for level, profile in sorted(self._profiles.items()):
            schedule = _get(profile, "charging_schedule", "chargingSchedule") or {}
            periods = _get(schedule, "charging_schedule_period", "chargingSchedulePeriod") or []
            kind = _get(profile, "charging_profile_kind", "chargingProfileKind")
            profile_id = _get(profile, "charging_profile_id", "chargingProfileId")
            lines.append(
                f"  Profile {profile_id}: "
                f"{len(periods)} periods, "
                f"kind={kind}"
            )
        return "\n".join(lines)
