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


PURPOSES = ("ChargePointMaxProfile", "TxDefaultProfile", "TxProfile")
_PERIOD_S = {"Daily": 86400, "Weekly": 7 * 86400}


def _str(v):
    return None if v is None else str(getattr(v, "value", v))


def _ts(iso) -> Optional[float]:
    """An ISO time as a UTC timestamp (None if missing or unreadable)."""
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.timestamp()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ChargingProfileScheduler:
    """OCPP 1.6 Smart Charging, as a charger works it out (OCPP 1.6 § 3.13):

    - each profile is kept by its id, or its purpose and stack level (a new one
      with either the same replaces it)
    - of each purpose, the highest stack level that has a limit now applies
    - the session's own profile (TxProfile) overrides the standing default
      (TxDefaultProfile); the charger's overall cap (ChargePointMaxProfile)
      always applies: the lower of the two is the limit
    - Absolute (from startSchedule), Relative (from the session's start) and
      Recurring (Daily / Weekly from startSchedule) schedules; validFrom /
      validTo; a schedule's duration; amps or watts
    - TxProfile ends with its session; the others stay (and are kept across
      restarts by the caller: to_store / load)

    Handles both camelCase (raw JSON) and snake_case (ocpp library) keys.
    """

    def __init__(self, rated_power_w: float = 7400.0, volts: float = 230.0, on_change=None):
        self._rated_power_w = rated_power_w
        self.volts = volts  # amps <-> watts (single phase, as before: 230 V)
        self._profiles: list[dict] = []  # normalised, with "_set_at" (UTC) and "_connector"
        self._tx_start: Optional[float] = None  # the session's start (UTC), for Relative
        self.on_change = on_change  # called when the standing profiles change (to save them)

    # --- what's kept ---

    @staticmethod
    def purpose(p: dict) -> Optional[str]:
        return _str(_get(p, "charging_profile_purpose", "chargingProfilePurpose"))

    @staticmethod
    def stack(p: dict) -> int:
        return int(_get(p, "stack_level", "stackLevel") or 0)

    @staticmethod
    def pid(p: dict):
        return _get(p, "charging_profile_id", "chargingProfileId")

    def set_profile(self, profile: dict, connector_id: int = 1) -> None:
        """Store a charging profile."""
        p = normalise_profile(profile)
        p["_set_at"] = float(int(time.time()))  # (whole seconds, as times are sent)
        p["_connector"] = connector_id
        purpose, level, pid = self.purpose(p), self.stack(p), self.pid(p)
        kind = _str(_get(p, "charging_profile_kind", "chargingProfileKind"))
        schedule = _get(p, "charging_schedule", "chargingSchedule") or {}
        periods = _get(schedule, "charging_schedule_period", "chargingSchedulePeriod") or []
        start = _get(schedule, "start_schedule", "startSchedule")
        rate_unit = _str(_get(schedule, "charging_rate_unit", "chargingRateUnit")) or "W"

        logger.info("Charging profile set: id=%s purpose=%s kind=%s", pid, purpose, kind)
        logger.info("  Schedule: unit=%s start=%s periods=%d", rate_unit, start, len(periods))
        for per in periods:
            limit = _get(per, "limit") or 0
            start_period = _get(per, "start_period", "startPeriod") or 0
            if rate_unit == "A":
                limit_display = f"{limit}A (~{limit * self.volts / 1000:.1f}kW)"
            else:
                limit_display = f"{limit}W ({limit / 1000:.1f}kW)"
            logger.info("    offset=%ds limit=%s", start_period, limit_display)

        self._profiles = [
            q for q in self._profiles
            if not ((pid is not None and self.pid(q) == pid) or (self.purpose(q) == purpose and self.stack(q) == level))
        ]
        self._profiles.append(p)
        self._changed(purpose)

    def clear_profile(
        self,
        profile_id: Optional[int] = None,
        connector_id: Optional[int] = None,
        purpose: Optional[str] = None,
        stack_level: Optional[int] = None,
    ) -> int:
        """Clear the profiles matching (ClearChargingProfile): by id; else all of
        connector, purpose and stack level that are given; nothing given: all.
        Returns how many were cleared."""
        purpose = _str(purpose)
        before = list(self._profiles)
        if profile_id is not None:
            self._profiles = [q for q in self._profiles if self.pid(q) != profile_id]
        elif connector_id is None and purpose is None and stack_level is None:
            self._profiles = []
        else:
            def matches(q):
                return ((connector_id is None or connector_id == 0 or q.get("_connector") in (connector_id, 0))
                        and (purpose is None or self.purpose(q) == purpose)
                        and (stack_level is None or self.stack(q) == stack_level))
            self._profiles = [q for q in self._profiles if not matches(q)]
        cleared = len(before) - len(self._profiles)
        logger.info("Charging profiles cleared (remaining: %d)", len(self._profiles))
        if any(self.purpose(q) != "TxProfile" for q in before if q not in self._profiles):
            self._changed("standing")
        return cleared

    def transaction_started(self, start_ts: Optional[float] = None) -> None:
        """A session started (or continued after a restart): Relative schedules run from then."""
        self._tx_start = time.time() if start_ts is None else start_ts

    def transaction_ended(self) -> None:
        """The session ended: its TxProfile goes with it; the others stay."""
        self._tx_start = None
        if any(self.purpose(q) == "TxProfile" for q in self._profiles):
            self.clear_profile(purpose="TxProfile")

    def _changed(self, purpose) -> None:
        if purpose != "TxProfile" and self.on_change:
            try:
                self.on_change()
            except Exception:
                logger.warning("Couldn't save the charging profiles", exc_info=True)

    def to_store(self) -> list[dict]:
        """The standing profiles (not the session's), to keep across restarts."""
        return [q for q in self._profiles if self.purpose(q) != "TxProfile"]

    def load(self, profiles) -> None:
        for q in profiles or []:
            if isinstance(q, dict) and self.purpose(q) in PURPOSES and self.purpose(q) != "TxProfile":
                q = normalise_profile(q)
                q.setdefault("_set_at", time.time())
                q.setdefault("_connector", 0)
                self._profiles.append(q)

    def count(self) -> int:
        return len(self._profiles)

    def has_purpose(self, purpose: str) -> bool:
        return any(self.purpose(q) == purpose for q in self._profiles)

    def replaces(self, profile: dict) -> bool:
        """Would this profile replace one already kept (same id, or purpose and stack level)?"""
        pid, purpose, level = self.pid(profile), self.purpose(profile), self.stack(profile)
        return any((pid is not None and self.pid(q) == pid) or (self.purpose(q) == purpose and self.stack(q) == level)
                   for q in self._profiles)

    # --- the limit ---

    def limit_w_at(self, t: float) -> Optional[float]:
        """The limit (W) at UTC time t: the lower of the session's (its TxProfile,
        else the standing TxDefaultProfile) and the overall cap; None if none applies."""
        def best(purpose):
            for q in sorted((q for q in self._profiles if self.purpose(q) == purpose), key=self.stack, reverse=True):
                v = self._eval(q, t)
                if v is not None:
                    return v
            return None
        tx = best("TxProfile")
        if tx is None:
            tx = best("TxDefaultProfile")
        cap = best("ChargePointMaxProfile")
        vals = [v for v in (tx, cap) if v is not None]
        return min(vals) if vals else None

    def get_current_limit_kw(self) -> Optional[float]:
        """The limit now, in kW: None if no profile applies (charge at rated
        power), 0.0 if it says to pause."""
        w = self.limit_w_at(time.time())
        return None if w is None else float(w) / 1000.0

    def _start(self, q: dict, schedule: dict) -> Optional[float]:
        kind = _str(_get(q, "charging_profile_kind", "chargingProfileKind")) or "Absolute"
        if kind == "Relative":
            return self._tx_start if self._tx_start is not None else q.get("_set_at")
        return _ts(_get(schedule, "start_schedule", "startSchedule")) or q.get("_set_at")

    def _eval(self, q: dict, t: float) -> Optional[float]:
        """One profile at UTC time t: watts, or None if it has no limit then."""
        vf = _ts(_get(q, "valid_from", "validFrom"))
        vt = _ts(_get(q, "valid_to", "validTo"))
        if (vf is not None and t < vf) or (vt is not None and t >= vt):
            return None
        schedule = _get(q, "charging_schedule", "chargingSchedule") or {}
        periods = _get(schedule, "charging_schedule_period", "chargingSchedulePeriod") or []
        if not periods:
            return None
        start = self._start(q, schedule)
        if start is None:
            return None
        kind = _str(_get(q, "charging_profile_kind", "chargingProfileKind")) or "Absolute"
        if kind == "Recurring":
            every = _PERIOD_S.get(_str(_get(q, "recurrency_kind", "recurrencyKind")) or "Daily", 86400)
            elapsed = (t - start) % every
        else:
            elapsed = t - start
        if elapsed < 0:
            return None
        duration = _get(schedule, "duration")
        if duration and elapsed >= float(duration):
            return None
        active = None
        for per in sorted(periods, key=lambda p: _get(p, "start_period", "startPeriod") or 0):
            if (_get(per, "start_period", "startPeriod") or 0) <= elapsed:
                active = per
            else:
                break
        if active is None:
            return None
        limit = float(_get(active, "limit") or 0)
        if (_str(_get(schedule, "charging_rate_unit", "chargingRateUnit")) or "W") == "A":
            limit *= self.volts
        return limit

    def composite(self, t0: float, duration: int) -> list[tuple[int, Optional[float]]]:
        """The limit (W) from t0 for duration seconds, as (offset s, watts or None)
        each time it changes (GetCompositeSchedule)."""
        t1 = t0 + duration
        points = {t0}
        for q in self._profiles:
            schedule = _get(q, "charging_schedule", "chargingSchedule") or {}
            start = self._start(q, schedule)
            if start is None:
                continue
            kind = _str(_get(q, "charging_profile_kind", "chargingProfileKind")) or "Absolute"
            bases = [start]
            if kind == "Recurring":
                every = _PERIOD_S.get(_str(_get(q, "recurrency_kind", "recurrencyKind")) or "Daily", 86400)
                k = int((t0 - start) // every) - 1
                bases = [start + (k + n) * every for n in range(int(duration // every) + 3)]
            dur = _get(schedule, "duration")
            for b in bases:
                for per in _get(schedule, "charging_schedule_period", "chargingSchedulePeriod") or []:
                    points.add(b + (_get(per, "start_period", "startPeriod") or 0))
                if dur:
                    points.add(b + float(dur))
            for edge in (_ts(_get(q, "valid_from", "validFrom")), _ts(_get(q, "valid_to", "validTo"))):
                if edge is not None:
                    points.add(edge)
        out: list[tuple[int, Optional[float]]] = []
        for t in sorted(p for p in points if t0 <= p < t1):
            v = self.limit_w_at(t)
            if not out or out[-1][1] != v:
                out.append((int(round(t - t0)), v))
        return out

    def profiles_info(self) -> list[dict]:
        """The profiles for the web GUI: the cap, then the session's, then the default; highest stack first."""
        order = {"ChargePointMaxProfile": 0, "TxProfile": 1, "TxDefaultProfile": 2}
        out = []
        for q in sorted(self._profiles, key=lambda q: (order.get(self.purpose(q), 3), -self.stack(q))):
            schedule = _get(q, "charging_schedule", "chargingSchedule") or {}
            periods = _get(schedule, "charging_schedule_period", "chargingSchedulePeriod") or []
            kind = _str(_get(q, "charging_profile_kind", "chargingProfileKind")) or "Absolute"
            start = self._start(q, schedule)
            out.append({
                "stack_level": self.stack(q),
                "profile_id": self.pid(q),
                "purpose": self.purpose(q),
                "kind": kind,
                "recurrency": _str(_get(q, "recurrency_kind", "recurrencyKind")),
                "valid_from": _get(q, "valid_from", "validFrom"),
                "valid_to": _get(q, "valid_to", "validTo"),
                "unit": _str(_get(schedule, "charging_rate_unit", "chargingRateUnit")) or "W",
                "start": _iso(start) if start is not None else None,
                "duration_s": _get(schedule, "duration"),
                "min_rate": _get(schedule, "min_charging_rate", "minChargingRate"),
                "applies_now": self._eval(q, time.time()) is not None,
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
