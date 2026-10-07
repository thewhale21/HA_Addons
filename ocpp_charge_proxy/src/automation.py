"""Plug-in schedule and automatic re-plug.

- Schedule: switch Plugged In on or off at set times, on chosen days, as
  many times a day as you like. Times are local (the add-on's TZ, which Home
  Assistant sets to your configured time zone). A time missed while the
  add-on was stopped isn't caught up.
- Re-plug: if the car is plugged in but the supplier hasn't started a
  session after `after_min` minutes, unplug, wait REPLUG_WAIT_S seconds and
  plug back in, up to `attempts` times. The count resets when a session
  starts or when the car is unplugged by anything else. If your supplier's
  smart charging plan is available (src/smart_charging.py), a slot planned
  for later counts as an answer: no re-plug while one is planned, only when
  nothing has been scheduled `after_min` minutes after plugging in. A slot
  running now doesn't: the supplier should be charging. But it may only
  start a session at the next half hour (Octopus does, e.g. after the
  add-on restarted mid-slot), so the wait is counted from then: with no
  session `after_min` minutes after the next :00 or :30, it re-plugs.

- One-off times: an entry with a `date` runs once, on that day, and is
  removed after it has run. Skips: any upcoming slot (a plug-in and its
  unplug, weekly or one-off) can be skipped once; skipped times don't
  run, and the skips are forgotten a day after.
- Auto plug-in charge: when auto plug-in (low SoC) switches Plugged In on
  and its "set my supplier's ready time" option is on, plan_auto_plug adds
  a one-off slot to the schedule: plug in now, unplug at the first ready
  time your supplier accepts at least the chosen hours away. If that puts
  more than Octopus's 6 hours in 24 (only checked with Force schedule on
  supplier on, as for the schedule), the next scheduled slot starts that
  much later (its first hours move to now). If it then meets or overlaps
  the next scheduled slot, the two become one slot. The ready time is set
  for the end of the slot. Its entries carry "source": "auto_plug" and run
  even with the schedule off.
- At start-up: if the schedule is on and the add-on starts inside a
  plugged-in stretch (the last schedule time before now was a plug-in) with
  Plugged In off, it plugs in, as if it had been running at that time.
- Graceful unplug: with the ready time on (Force schedule on supplier), a
  scheduled unplug during a session waits up to `unplug_wait_s` (default
  GRACEFUL_UNPLUG_S, set on the page; 0 = don't wait) for the supplier to
  stop the session itself (RemoteStop), then unplugs.
- Plan check: with the ready time on, while the schedule has the car
  plugged in, the supplier's planned slots up to the ready time are checked
  against the schedule (src/plan_check.py); a mismatch is shown on the page.
- Ready time: optionally, when the schedule plugs in, set your supplier's
  smart charging ready-by time to the schedule's next unplug
  (src/ready_time.py). Only at a scheduled plug-in.

Settings are saved in /data/automation.json and set on the web page's
Automations tab. Until they're saved, re-plug uses the defaults.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import math
import os
import time
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from src.plan_check import SETTLE_S, check_plan
from src.ready_time import ALL_DAY_TIMES, check_unplug_times

logger = logging.getLogger(__name__)

REPLUG_WAIT_S = 30
HALF_HOUR_S = 1800
STARTUP_READY_S = 180  # keep trying to set the ready time this long after start-up
GRACEFUL_UNPLUG_S = 60  # with Force schedule on supplier: wait this long for it to stop a session (default)
MAX_UNPLUG_WAIT_S = 600
PENDING_TICK_S = 2  # check this often while waiting
TICK_S = 15
CATCH_UP_S = 300  # a scheduled time is still run if noticed within this
ACTIONS = ("plug", "unplug")
AUTO_SOURCE = "auto_plug"  # entries added by an auto plug-in charge
CHARGE_NOW_SOURCE = "charge_now"  # ... or by the Charge now button
CAR_PLUGGED_SOURCE = "car_plugged"  # ... or by the car plugged in sensor
AUTO_SOURCES = (AUTO_SOURCE, CHARGE_NOW_SOURCE, CAR_PLUGGED_SOURCE)
SOURCE_NAMES = {AUTO_SOURCE: "Auto plug-in charge", CHARGE_NOW_SOURCE: "Charge now",
                CAR_PLUGGED_SOURCE: "Car plugged in charge"}
ONE_OFF_KEEP = datetime.timedelta(days=14)  # one-off times (and skips) are kept this long after they ran


@dataclass(frozen=True)
class ReplugOptions:
    """Re-plug defaults (the web page's settings are saved over them)."""

    enabled: bool = True
    after_min: int = 10
    attempts: int = 3
    off_s: int = REPLUG_WAIT_S  # left unplugged this long before plugging back in

    def as_dict(self) -> dict:
        return {"enabled": self.enabled, "after_min": self.after_min, "attempts": self.attempts, "off_s": self.off_s}


def _iso_local(dt: Optional[datetime.datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") if dt else None


def _iso_from_epoch(t: Optional[float]) -> Optional[str]:
    if t is None:
        return None
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_hhmm(value) -> tuple[int, int]:
    try:
        hh, mm = str(value).strip().split(":")
        h, m = int(hh), int(mm)
    except (ValueError, AttributeError):
        raise ValueError(f"Time must be HH:MM, got {value!r}") from None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Time must be HH:MM, got {value!r}")
    return h, m


def _parse_iso(value) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.astimezone()


def _parse_date(value) -> datetime.date:
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(f"Date must be YYYY-MM-DD, got {value!r}") from None


def validate_block(raw: dict) -> dict:
    """A no-charging time: {id, start "HH:MM", end "HH:MM", days [0=Mon..6=Sun]};
    overnight when end <= start (it starts on the days given)."""
    if not isinstance(raw, dict):
        raise ValueError("Each no-charging time must be an object")
    h1, m1 = _parse_hhmm(raw.get("start"))
    h2, m2 = _parse_hhmm(raw.get("end"))
    if (h1, m1) == (h2, m2):
        raise ValueError("A no-charging time must start and end at different times")
    days = raw.get("days", list(range(7)))
    if not isinstance(days, list) or not days or any(
        not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in days
    ):
        raise ValueError("Days must be a non-empty list of 0 (Mon) to 6 (Sun)")
    return {"id": str(raw.get("id") or uuid.uuid4().hex[:8]), "start": f"{h1:02d}:{m1:02d}",
            "end": f"{h2:02d}:{m2:02d}", "days": sorted(set(days))}


def minus(windows: list, cuts: list) -> list:
    """`windows` [(a, b)] with the `cuts` [(a, b)] taken out."""
    out = list(windows)
    for ca, cb in cuts:
        nxt = []
        for a, b in out:
            if cb <= a or ca >= b:
                nxt.append((a, b))
                continue
            if a < ca:
                nxt.append((a, ca))
            if cb < b:
                nxt.append((cb, b))
        out = nxt
    return out


def validate_entry(raw: dict) -> dict:
    """A schedule entry: {id, time "HH:MM", days [0=Mon..6=Sun], action, enabled},
    or a one-off: the same with "date": "YYYY-MM-DD" (days is then that day)."""
    if not isinstance(raw, dict):
        raise ValueError("Each entry must be an object")
    h, m = _parse_hhmm(raw.get("time"))
    action = raw.get("action")
    if action not in ACTIONS:
        raise ValueError(f"Action must be one of {ACTIONS}, got {action!r}")
    if raw.get("date"):
        date = _parse_date(raw["date"])
        out = {
            "id": str(raw.get("id") or uuid.uuid4().hex[:8]),
            "time": f"{h:02d}:{m:02d}",
            "days": [date.weekday()],
            "date": date.isoformat(),
            "action": action,
            "enabled": bool(raw.get("enabled", True)),
        }
        if raw.get("source") in AUTO_SOURCES:
            out["source"] = raw["source"]
        trims = raw.get("trims")
        if isinstance(trims, dict):  # what this charge changed in the schedule (put back if it's deleted)
            out["trims"] = {
                "skips": [{"entry_id": str(k["entry_id"]), "date": str(k["date"])} for k in trims.get("skips") or []
                          if isinstance(k, dict) and k.get("entry_id") and k.get("date")],
                "added": [str(i) for i in trims.get("added") or [] if isinstance(i, (str, int))],
            }
        return out
    days = raw.get("days", list(range(7)))
    if not isinstance(days, list) or not days or any(
        not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in days
    ):
        raise ValueError("Days must be a non-empty list of 0 (Mon) to 6 (Sun)")
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex[:8]),
        "time": f"{h:02d}:{m:02d}",
        "days": sorted(set(days)),
        "action": action,
        "enabled": bool(raw.get("enabled", True)),
    }


def plugged_windows(events, open_until=None):
    """(time, is_plug) events in time order -> the stretches plugged in, as
    (start, end). A stretch still open at the last event is left out, or
    with `open_until`, ends then (a plug-in that's never unplugged)."""
    windows = []
    state, since = None, None
    for t, plug in events:
        if plug and state is not True:
            state, since = True, t
        elif not plug:
            if state is True:
                windows.append((since, t))
            state = False
    if open_until is not None and state is True and since < open_until:
        windows.append((since, open_until))
    return windows


def _hours(minutes: int) -> str:
    """360 -> "6", 330 -> "5.5"."""
    return f"{minutes / 60:g}"


def _rolling_hours(reset: Optional[str]) -> Optional[int]:
    """limit_reset "48h": no more than the limit in any 48 hours (rolling)."""
    if reset and reset.endswith("h") and reset[:-1].isdigit():
        return int(reset[:-1])
    return None


def limit_length(reset: Optional[str]) -> datetime.timedelta:
    """How long the daily limit is counted over: N hours for "Nh", else 24."""
    return datetime.timedelta(hours=_rolling_hours(reset) or 24)


def _fixed(reset: Optional[str]) -> Optional[str]:
    """The reset time ("HH:MM") if the limit resets at a set time every day."""
    return reset if reset and _rolling_hours(reset) is None else None


def limit_period_text(reset: Optional[str]) -> str:
    """"a day" / "in any 48 hours", for messages."""
    hours = _rolling_hours(reset)
    return f"in any {hours} hours" if hours and hours != 24 else "a day"


def window_minutes(windows, start, end=datetime.timedelta(days=1)) -> int:
    """Plugged-in minutes (real ones: the night the clocks go back has an
    extra hour) from `start` to `end` (or for `end`, a timedelta: 24 hours)."""
    if isinstance(end, datetime.timedelta):
        end = start + end
    return int(round(sum(max(0.0, (min(y, end) - max(x, start)).total_seconds()) for x, y in windows) / 60))


def _system_localize(naive: datetime.datetime) -> datetime.datetime:
    return naive.astimezone()


def period_start(t: datetime.datetime, reset: str, localize=_system_localize) -> datetime.datetime:
    """The start of the limit day `t` is in, for a limit that resets every day
    at `reset` ("HH:MM", e.g. Octopus: 12:00), by the clock."""
    h, m = _parse_hhmm(reset)
    wall = t.replace(tzinfo=None)  # local clock time
    start = wall.replace(hour=h, minute=m, second=0, microsecond=0)
    if start > wall:
        start -= datetime.timedelta(days=1)
    start = localize(start)
    if start > t:  # the clocks changed in between
        start = localize(start.replace(tzinfo=None) - datetime.timedelta(days=1))
    return start


def limit_end(start: datetime.datetime, reset: Optional[str], localize=_system_localize) -> datetime.datetime:
    """When the limit day (or rolling period) from `start` ends: the reset
    time the next day by the clock (23 or 25 hours when the clocks change),
    or 24 (N) hours on."""
    if _fixed(reset):
        return localize(start.replace(tzinfo=None) + datetime.timedelta(days=1))
    return start + limit_length(reset)


def limit_starts(windows, after, until, reset: Optional[str] = None, localize=_system_localize) -> list:
    """Where the 24 hours a daily limit is checked over start. reset None
    (rolling): any 24 hours, i.e. from each stretch's start between `after`
    and `until`; "Nh": the same over N hours (looking back N hours from a
    day after `after`, i.e. from now).
    reset "HH:MM": the limit resets then every day, so each limit day a
    stretch is in, from after `after` (i.e. not over yet when `after` is a
    day ago) to `until`."""
    if not _fixed(reset):
        if reset:
            after += datetime.timedelta(days=1) - limit_length(reset)
        # a stretch already going at `after` (e.g. one that's never unplugged) counts from then
        return sorted({max(a, after) for a, b in windows if b > after and a <= until})
    out = set()
    for a, b in windows:
        for t in (a, b - datetime.timedelta(microseconds=1)):
            s = period_start(t, reset, localize)
            if after < s <= until:
                out.add(s)
    return sorted(out)


def longest_day(windows, after, until, reset: Optional[str] = None, localize=_system_localize):
    """The most plugged-in minutes in any 24 hours a daily limit is checked
    over (see limit_starts): (minutes, start), or None."""
    worst = None
    for a in limit_starts(windows, after, until, reset, localize):
        total = window_minutes(windows, a, limit_end(a, reset, localize))
        if worst is None or total > worst[0]:
            worst = (total, a)
    return worst


def limit_day_text(start: datetime.datetime, reset: Optional[str]) -> str:
    """"the 24 hours from Sat 18:00" / "the day from Sat 12:00 (the limit resets at 12:00)"."""
    if not _fixed(reset):
        return f"the {_rolling_hours(reset) or 24} hours from {start.strftime('%a %H:%M')}"
    return f"the day from {start.strftime('%a %H:%M')} (the limit resets at {reset})"


def _local_now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def timezone_name() -> str:
    return os.environ.get("TZ") or _local_now().tzname() or "UTC"


class Automation:
    def __init__(
        self,
        data_dir: Optional[str],
        options: ReplugOptions = ReplugOptions(),
        now: Callable[[], datetime.datetime] = _local_now,
        clock: Callable[[], float] = time.time,
        localize: Callable[[datetime.datetime], datetime.datetime] = lambda naive: naive.astimezone(),
    ) -> None:
        self._localize = localize  # naive local time -> aware (local DST rules)
        self._path = os.path.join(data_dir, "automation.json") if data_dir else None
        self._now = now
        self._clock = clock
        self.schedule_enabled = False
        self.entries: list[dict] = []
        self.skips: list[dict] = []  # [{"entry_id", "date"}]: times skipped once
        self.ready_time = False  # set the supplier's ready time at scheduled plug-ins
        self.ready_status: Optional[dict] = None  # the last time it was set (or why not)
        self.auto_plug_last: Optional[dict] = None  # the last auto plug-in charge planned
        self.unplug_wait_s = GRACEFUL_UNPLUG_S
        self.blocks: list[dict] = []  # no-charging times: nothing is scheduled in them
        self.override_guards = False  # Diagnostics › Debug: no daily limit (Octopus: 6 hours)
        # When the daily limit resets: None = any 24 hours (rolling), "Nh" =
        # any N hours, "HH:MM" = every day then (Octopus: 12:00). From the
        # Settings tab, not saved here.
        self.limit_reset: Optional[str] = None
        self.plan_check: Optional[dict] = None  # the supplier's plan vs the schedule, while plugged in
        self._plan_problems: tuple = ()
        self.replug = options.as_dict()
        # Runtime (not saved)
        self.attempts_used = 0
        self.waiting_since: Optional[float] = None  # plugged in, no session, since
        self.replugging = False
        self.gave_up = False
        self.scheduled = False  # waiting, but your supplier has a slot planned
        self.slot_now = False  # waiting, though your supplier's slot is running
        self.last_replug: Optional[float] = None
        self.last_run: Optional[dict] = None  # last schedule entry run
        self.unplug_at: Optional[float] = None  # a scheduled unplug waiting for the supplier, until
        self._last_check: Optional[datetime.datetime] = None
        self._load()

    # --- persistence ---------------------------------------------------------

    def _load(self) -> None:
        if not self._path:
            return
        data = None
        for path in (self._path, self._path + ".bak"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                break
            except FileNotFoundError:
                continue
            except Exception:
                logger.warning("Automation settings %s are unreadable", path)
        if not isinstance(data, dict):
            return
        schedule = data.get("schedule") or {}
        self.schedule_enabled = bool(schedule.get("enabled", False))
        self.ready_time = bool(schedule.get("ready_time", False))
        self.override_guards = bool(schedule.get("override_guards", False))
        blocks = []
        for raw in schedule.get("blocks") or []:
            try:
                blocks.append(validate_block(raw))
            except ValueError:
                logger.warning("Ignoring invalid no-charging time %r", raw)
        self.blocks = blocks
        try:
            self.unplug_wait_s = self._valid_wait(schedule.get("unplug_wait_s", GRACEFUL_UNPLUG_S))
        except ValueError:
            pass
        entries = []
        for raw in schedule.get("entries") or []:
            try:
                entries.append(validate_entry(raw))
            except ValueError:
                logger.warning("Ignoring invalid schedule entry %r", raw)
        self.entries = entries
        self.skips = [k for k in schedule.get("skips") or []
                      if isinstance(k, dict) and k.get("entry_id") and k.get("date")]
        # Saved re-plug settings (set on the web page) win over the defaults
        replug = data.get("replug")
        if isinstance(replug, dict):
            try:
                self.replug = self._valid_replug({**self.replug, **replug})
            except ValueError:
                pass

    def _save(self) -> None:
        if not self._path:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "schedule": {"enabled": self.schedule_enabled, "entries": self.entries,
                                 "ready_time": self.ready_time, "skips": self.skips,
                                 "unplug_wait_s": self.unplug_wait_s,
                                 "override_guards": self.override_guards, "blocks": self.blocks},
                    "replug": self.replug,
                }, f, indent=1)
                f.flush()
                os.fsync(f.fileno())
            if os.path.exists(self._path):
                os.replace(self._path, self._path + ".bak")
            os.replace(tmp, self._path)
        except Exception:
            logger.warning("Could not save automation settings", exc_info=True)

    # --- settings ------------------------------------------------------------

    def set_schedule(self, enabled: Optional[bool] = None, entries: Optional[list] = None,
                     ready_time: Optional[bool] = None, ready_times: Optional[list] = None,
                     provider: str = "your supplier", daily_cap_min: Optional[int] = None,
                     unplug_wait_s=None, override_guards: Optional[bool] = None,
                     blocks: Optional[list] = None) -> None:
        """override_guards: with it on, daily_cap_min isn't applied (turning it
        back off checks the schedule, as turning on the ready time does).
        ready_times: the times your supplier accepts as a ready time (None:
        unknown). While the schedule sets it, unplug times must be among them,
        and with daily_cap_min (Octopus: 360) it can't plug in for longer than
        that in any 24 hours. Checked when times are saved or the ready time
        is turned on, so the schedule can always be switched off."""
        wait = None if unplug_wait_s is None else self._valid_wait(unplug_wait_s)
        new_entries = self.entries
        if entries is not None:
            if not isinstance(entries, list):
                raise ValueError("Entries must be a list")
            if len(entries) > 50:
                raise ValueError("At most 50 schedule entries")
            new_entries = [validate_entry(e) for e in entries]
        new_skips = list(self.skips)
        if entries is not None:
            # A charge (auto plug-in, Charge now...) that's deleted puts back the
            # slot it trimmed or joined: its replacement plug-in goes, the skips go
            kept = {e["id"] for e in new_entries}
            for gone in (e for e in self.entries if e.get("trims") and e["id"] not in kept):
                added = set(gone["trims"].get("added") or [])
                new_entries = [e for e in new_entries if e["id"] not in added]
                new_skips = [k for k in new_skips if k not in (gone["trims"].get("skips") or [])]
                logger.info("Schedule: a charge was deleted, putting back what it changed")
        guards_off = self.override_guards if override_guards is None else bool(override_guards)
        if guards_off:
            daily_cap_min = None
        if daily_cap_min and (self.ready_time if ready_time is None else bool(ready_time)):
            # A slot across the limit's reset time (Octopus: 12:00) that's longer
            # than the limit is split there: two charges, each with its own ready time
            splits = self._reset_splits(new_entries, new_skips, daily_cap_min)
            if splits:
                new_entries = new_entries + splits
                logger.info("Schedule: split %s at %s, where %s's daily limit resets",
                            "a slot" if len(splits) == 2 else "slots", ", ".join(sorted({e["time"] for e in splits})),
                            provider)
        checking = (entries is not None or bool(ready_time)
                    or (override_guards is not None and not override_guards and self.override_guards))
        if checking and (self.ready_time if ready_time is None else bool(ready_time)):
            if ready_times:
                check_unplug_times([e for e in new_entries if not self._past_one_off(e)], ready_times, provider)
            if daily_cap_min:
                # Any 24 hours from the previous day on. Only saving times: one
                # that's already over (e.g. after a Charge now) can still be
                # changed, as long as it doesn't get worse.
                only_times = entries is not None and not ready_time and override_guards is None
                if not only_times or self._makes_worse(daily_cap_min, (self.entries, self.skips), (new_entries, new_skips)):
                    self.check_daily_cap(new_entries, daily_cap_min, provider, new_skips)
        new_blocks = self.blocks
        if blocks is not None:
            if not isinstance(blocks, list) or len(blocks) > 20:
                raise ValueError("No-charging times must be a list (at most 20)")
            new_blocks = [validate_block(b) for b in blocks]
        if entries is not None or blocks is not None:
            self.check_blocks(new_entries, new_blocks, new_skips)
        self.blocks = new_blocks
        self.entries = new_entries
        ids = {e["id"] for e in self.entries}
        self.skips = [k for k in new_skips if k["entry_id"] in ids]
        self._prune()
        if enabled is not None:
            self.schedule_enabled = bool(enabled)
        if ready_time is not None:
            self.ready_time = bool(ready_time)
        if wait is not None:
            self.unplug_wait_s = wait
        if override_guards is not None and bool(override_guards) != self.override_guards:
            self.override_guards = bool(override_guards)
            logger.info("Scheduling guards %s", "overridden: no daily limit"
                        if self.override_guards else "back on")
        self._save()
        logger.info(
            "Schedule %s, %d entr%s", "on" if self.schedule_enabled else "off",
            len(self.entries), "y" if len(self.entries) == 1 else "ies",
        )

    @staticmethod
    def _valid_wait(value) -> int:
        try:
            wait = int(value)
        except (TypeError, ValueError):
            raise ValueError("The unplug wait must be a whole number of seconds") from None
        if not 0 <= wait <= MAX_UNPLUG_WAIT_S:
            raise ValueError(f"The unplug wait must be 0 to {MAX_UNPLUG_WAIT_S} seconds")
        return wait

    @staticmethod
    def _valid_replug(values: dict) -> dict:
        try:
            after = int(values["after_min"])
            attempts = int(values["attempts"])
            off = int(values.get("off_s", REPLUG_WAIT_S))
        except (KeyError, TypeError, ValueError):
            raise ValueError("after_min, attempts and off_s must be whole numbers") from None
        if not 1 <= after <= 240:
            raise ValueError("after_min must be 1 to 240 minutes")
        if not 0 <= attempts <= 20:
            raise ValueError("attempts must be 0 to 20")
        if not 5 <= off <= 300:
            raise ValueError("off_s must be 5 to 300 seconds")
        return {"enabled": bool(values.get("enabled", True)), "after_min": after, "attempts": attempts, "off_s": off}

    def set_replug(self, **changes) -> None:
        allowed = {k: v for k, v in changes.items() if k in ("enabled", "after_min", "attempts", "off_s") and v is not None}
        self.replug = self._valid_replug({**self.replug, **allowed})
        if not self.replug["enabled"]:
            self.waiting_since = None
        self.gave_up = self.gave_up and self.attempts_used >= self.replug["attempts"]
        self._save()
        logger.info(
            "Auto re-plug %s (after %d min, up to %d tries)",
            "on" if self.replug["enabled"] else "off",
            self.replug["after_min"], self.replug["attempts"],
        )

    # --- schedule ------------------------------------------------------------

    def _occurrences(self, entry: dict, start: datetime.date, days: int):
        h, m = _parse_hhmm(entry["time"])
        once = entry.get("date")
        for i in range(days):
            day = start + datetime.timedelta(days=i)
            if (day.isoformat() == once) if once else (day.weekday() in entry["days"]):
                yield self._localize(datetime.datetime(day.year, day.month, day.day, h, m))

    def timeline(self, start: datetime.date, days: int, entries: Optional[list] = None,
                 skips: Optional[list] = None) -> list:
        """Every enabled time from `start` for `days` days: (when, entry, skipped), in order."""
        skips = self.skips if skips is None else skips
        out = []
        for entry in self._active_entries() if entries is None else entries:
            if not entry["enabled"]:
                continue
            for occ in self._occurrences(entry, start, days):
                out.append((occ, entry, {"entry_id": entry["id"], "date": occ.date().isoformat()} in skips))
        # an unplug at the same minute as a plug comes before it: back-to-back
        # slots (06:00-12:00 and 12:00-18:00) unplug and plug straight back in,
        # so the supplier sees two charges, each with its own ready time
        out.sort(key=lambda x: (x[0], x[1]["action"] == "plug"))
        return out

    def _active_entries(self) -> list:
        """The entries that run: all of them with the schedule on, else only
        those an auto plug-in charge added."""
        if self.schedule_enabled:
            return self.entries
        return [e for e in self.entries if e.get("source") in AUTO_SOURCES]

    def _horizon_days(self, entries: Optional[list] = None) -> int:
        """Days on from today the schedule is looked at: 8, or to the last one-off."""
        today = self._now().date()
        last = max((_parse_date(e["date"]) for e in (self._active_entries() if entries is None else entries)
                    if e.get("date")), default=today)
        return max(8, (last - today).days + 2)

    def windows(self, entries: Optional[list] = None, now: Optional[datetime.datetime] = None,
                skips: Optional[list] = None, open_ended: bool = False) -> list:
        """The stretches the schedule has the car plugged in, a week back to 8
        days on (or to the last one-off). open_ended: a plug-in with no unplug
        after it counts as plugged in to the end (for the daily limit)."""
        now = now or self._now()
        days = self._horizon_days(entries)
        tl = self.timeline(now.date() - datetime.timedelta(days=7), 8 + days, entries, skips)
        end = self._localize(datetime.datetime.combine(now.date() + datetime.timedelta(days=days), datetime.time()))
        return plugged_windows([(t, e["action"] == "plug") for t, e, skipped in tl if not skipped],
                               end if open_ended else None)

    def block_windows(self, start: datetime.date, days: int, blocks: Optional[list] = None) -> list:
        """The no-charging times from `start` for `days` days: [(a, b)]."""
        out = []
        for b in self.blocks if blocks is None else blocks:
            h1, m1 = _parse_hhmm(b["start"])
            h2, m2 = _parse_hhmm(b["end"])
            for i in range(-1, days):
                d = start + datetime.timedelta(days=i)
                if d.weekday() not in b["days"]:
                    continue
                a = self._localize(datetime.datetime(d.year, d.month, d.day, h1, m1))
                e = d + datetime.timedelta(days=1) if (h2, m2) <= (h1, m1) else d
                out.append((a, self._localize(datetime.datetime(e.year, e.month, e.day, h2, m2))))
        return sorted(out)

    def check_blocks(self, entries: list, blocks: list, skips: Optional[list] = None) -> None:
        """Nothing scheduled may plug in during a no-charging time (over the
        coming week; auto plug-in and Charge now are planned around them)."""
        now = self._now()
        cuts = self.block_windows(now.date(), self._horizon_days(entries) + 1, blocks)
        for a, b in self.windows(entries, now, skips):
            if b <= now:
                continue
            hit = next(((ca, cb) for ca, cb in cuts if ca < b and cb > a), None)
            if hit:
                raise ValueError(
                    f"The {a.strftime('%a %H:%M')}–{b.strftime('%H:%M')} slot overlaps the no-charging time "
                    f"{hit[0].strftime('%H:%M')}–{hit[1].strftime('%H:%M')}: change one of them")

    def blocked(self, when: Optional[datetime.datetime] = None):
        """The no-charging time `when` (now) is in: (start, end), or None."""
        when = when or self._now()
        return next(((a, b) for a, b in self.block_windows(when.date(), 1) if a <= when < b), None)

    def _longest_day(self, entries: list, skips: Optional[list] = None):
        now = self._now()
        return longest_day(self.windows(entries, now, skips, open_ended=True), now - datetime.timedelta(days=1),
                           now + datetime.timedelta(days=self._horizon_days(entries) - 1), self.limit_reset,
                           self._localize)

    def _reset_splits(self, entries: list, skips: list, cap_min: int, one_off: bool = False,
                      until: Optional[datetime.datetime] = None) -> list:
        """Entries that split each coming slot longer than `cap_min` where the
        daily limit resets (it unplugs and plugs straight back in there: see
        due()), so the supplier sees a charge either side. Weekly for weekly
        slots, one-offs otherwise (or with `one_off`). Only with a reset time."""
        fixed, loc = _fixed(self.limit_reset), self._localize
        if not fixed or not cap_min:
            return []
        now = self._now()
        weekly: dict = {}
        out = []
        for s in self._stretches(now.date() - datetime.timedelta(days=1), self._horizon_days(entries) + 1,
                                 entries, skips):
            if s["end"] <= now or (until is not None and s["start"] > until):
                continue
            if (s["end"] - s["start"]).total_seconds() / 60 <= cap_min:
                continue
            r = limit_end(period_start(s["start"], fixed, loc), fixed, loc)
            while r < s["end"]:
                if r > now:
                    src = s["plug"].get("source")
                    if not one_off and not s["plug"].get("date") and not s["unplug"].get("date"):
                        weekly.setdefault(r.strftime("%H:%M"), set()).add(r.weekday())
                    else:
                        for action in ("unplug", "plug"):
                            out.append(validate_entry({"time": r.strftime("%H:%M"), "date": r.date().isoformat(),
                                                       "action": action, **({"source": src} if src else {})}))
                r = limit_end(r, fixed, loc)
        for t, days in sorted(weekly.items()):
            for action in ("unplug", "plug"):
                out.append(validate_entry({"time": t, "days": sorted(days), "action": action}))
        return out

    def _makes_worse(self, cap_min: int, old: tuple, new: tuple) -> bool:
        """(entries, skips) before and after a change: does any 24 hours (or
        limit day) go over the cap, or further over it than it already was?"""
        now, reset = self._now(), self.limit_reset
        before = self.windows(old[0], now, old[1], open_ended=True)
        after = self.windows(new[0], now, new[1], open_ended=True)
        for a in limit_starts(after, now - datetime.timedelta(days=1),
                              now + datetime.timedelta(days=self._horizon_days(new[0]) - 1), reset, self._localize):
            end = limit_end(a, reset, self._localize)
            if window_minutes(after, a, end) > max(cap_min, window_minutes(before, a, end)):
                return True
        return False

    def check_daily_cap(self, entries: list, cap_min: int, provider: str, skips: Optional[list] = None) -> None:
        """Octopus schedules at most 6 hours of smart charging a day: refuse a
        schedule that plugs in for longer in any 24 hours (or limit day, with a
        reset time) over the coming week."""
        worst = self._longest_day(entries, skips)
        if worst and worst[0] > cap_min:
            total, start = worst
            raise ValueError(
                f"{provider[:1].upper() + provider[1:]} schedules at most {_hours(cap_min)} hours of smart charging "
                f"{limit_period_text(self.limit_reset)}, but the schedule "
                f"plugs in for {total // 60}h {total % 60:02d}m in {limit_day_text(start, self.limit_reset)}: shorten it"
            )

    def _prune(self) -> bool:
        """Forget one-off times that have run and skips more than a day old."""
        now = self._now()
        keep = []
        for e in self.entries:
            if e.get("date"):
                h, m = _parse_hhmm(e["time"])
                d = _parse_date(e["date"])
                when = self._localize(datetime.datetime(d.year, d.month, d.day, h, m))
                if when < now - ONE_OFF_KEEP:  # kept a day, so its stretch stays known
                    continue
            keep.append(e)
        # (a skip is kept for a day after, e.g. last night's plug-in until it's over)
        skips = [k for k in self.skips if k["date"] >= (now.date() - ONE_OFF_KEEP).isoformat()]
        changed = len(keep) != len(self.entries) or len(skips) != len(self.skips)
        self.entries, self.skips = keep, skips
        return changed

    def _past_one_off(self, entry: dict) -> bool:
        """A one-off time that has already run (kept for the Sessions tab)."""
        if not entry.get("date"):
            return False
        h, m = _parse_hhmm(entry["time"])
        d = _parse_date(entry["date"])
        return self._localize(datetime.datetime(d.year, d.month, d.day, h, m)) < self._now()

    def one_off_runs(self) -> list:
        """The plugged-in stretches of the last 14 days that a one-off time
        started or ended, newest first: [{"start", "end", "source"}] ("auto_plug"
        if an auto plug-in charge added it, else "one_off")."""
        now = self._now()
        days = ONE_OFF_KEEP.days + 1
        out = []
        for s in self._stretches(now.date() - datetime.timedelta(days=days - 1), days, self._active_entries(), self.skips):
            ones = [e for e in (s["plug"], s["unplug"]) if e.get("date")]
            if ones and s["start"] <= now:
                source = next((e["source"] for e in ones if e.get("source") in AUTO_SOURCES), "one_off")
                out.append({"start": _iso_local(s["start"]), "end": _iso_local(s["end"]), "source": source})
        return out[::-1]

    def _stretches(self, start: datetime.date, days: int, entries: list, skips: list) -> list:
        """Plugged-in stretches with the entries that make them:
        [{"start", "plug", "end", "unplug"}] (a stretch still open at the end is left out)."""
        out, state, cur = [], None, None
        for t, e, skipped in self.timeline(start, days, entries, skips):
            if skipped:
                continue
            if e["action"] == "plug" and state is not True:
                state, cur = True, {"start": t, "plug": e}
            elif e["action"] == "unplug":
                if state is True:
                    cur.update(end=t, unplug=e)
                    out.append(cur)
                state = False
        return out

    def first_ready_at(self, target: datetime.datetime, ready_times: Optional[list] = None):
        """The first ready time your supplier accepts at or after `target`."""
        best = None
        for d in range(3):
            day = target.date() + datetime.timedelta(days=d)
            for t in ready_times or ALL_DAY_TIMES:
                h, m = _parse_hhmm(t)
                dt = self._localize(datetime.datetime(day.year, day.month, day.day, h, m))
                if dt >= target and (best is None or dt < best):
                    best = dt
        return best

    def last_ready_by(self, limit: datetime.datetime, ready_times: Optional[list] = None):
        """The last ready time your supplier accepts at or before `limit` (that day or the one before)."""
        best = None
        for d in (0, -1):
            day = limit.date() + datetime.timedelta(days=d)
            for t in ready_times or ALL_DAY_TIMES:
                h, m = _parse_hhmm(t)
                dt = self._localize(datetime.datetime(day.year, day.month, day.day, h, m))
                if dt <= limit and (best is None or dt > best):
                    best = dt
        return best

    def plan_auto_plug(self, minutes: int, ready_times: Optional[list] = None,
                       cap_min: Optional[int] = None, provider: str = "your supplier",
                       source: str = AUTO_SOURCE, dry_run: bool = False) -> dict:
        """An auto plug-in (or Charge now) just plugged in: add a charge of
        `minutes` to the schedule as a one-off (see the module docstring).

        With cap_min (Octopus: 360), the charge is at most that long, and if
        it takes any 24 hours (the previous 24 included) over the cap, the
        scheduled slots after it lose their first half hours, as a one-off,
        the next first: just enough to get back under it (a slot that's all
        taken off is skipped, and the next one is trimmed too, as long as it's
        in a day the charge takes over). dry_run: work it out without changing
        anything (Charge now asks first). Returns what was (or would be) done,
        with "over": the most minutes in any 24 hours before and after the
        slots are trimmed."""
        loc = self._localize
        now = self._now().replace(second=0, microsecond=0)
        end = self.first_ready_at(now + datetime.timedelta(minutes=minutes), ready_times)
        if end is None:
            raise ValueError("No ready time your supplier accepts in the next 2 days")
        # Plugged in from now to then, but not in a no-charging time (off peak:
        # the car may well charge then anyway): it unplugs at its start and plugs
        # back in at its end, and still ends at the same time
        cuts = self.block_windows(now.date() - datetime.timedelta(days=1), 4)
        segments = minus([(now, end)], cuts)
        blocked_notes = [f"not plugged in {ca.strftime('%H:%M')}–{cb.strftime('%H:%M')} (no-charging time)"
                         for ca, cb in cuts if ca < end and cb > now]
        shortened = None
        reset = self.limit_reset
        fixed, span_len = _fixed(reset), limit_length(reset)
        if cap_min:
            # e.g. Octopus schedules at most 6 hours a day: the earliest that many
            # are scheduled, then it stops. With a reset time (Octopus: 12:00),
            # that many in each limit day: a charge across it can be longer.
            pieces = []
            for x, y in segments:
                while fixed:
                    nxt = limit_end(period_start(x, fixed, loc), fixed, loc)
                    if nxt >= y:
                        break
                    pieces.append((x, nxt))
                    x = nxt
                pieces.append((x, y))
            keep, used, stopped = [], {}, False
            for x, y in pieces:
                key = period_start(x, fixed, loc) if fixed else None
                left = cap_min - used.get(key, 0)
                length = (y - x).total_seconds() / 60
                if length <= left:
                    keep.append((x, y))
                    used[key] = used.get(key, 0) + length
                    continue
                if left > 0:
                    cut = x + datetime.timedelta(minutes=left)
                    earlier = self.last_ready_by(cut, ready_times)  # a ready time, if one fits
                    keep.append((x, earlier if earlier is not None and earlier > x else cut))
                stopped = True
                break
            if stopped:
                merged = []
                for x, y in keep:
                    if merged and merged[-1][1] == x:
                        merged[-1] = (merged[-1][0], y)
                    else:
                        merged.append((x, y))
                segments = merged
                kept = int(round(sum((y - x).total_seconds() for x, y in segments) / 60))
                shortened = (f"shortened to {_hours(cap_min)} hours, {provider}'s daily limit" if not fixed
                             else f"shortened to {_hours(kept)} hours, {provider}'s daily limit of "
                                  f"{_hours(cap_min)} hours (resets at {fixed})")
        if not segments:
            plan = {"at": _iso_local(now), "minutes": 0, "ready_for": None, "end": None, "combined": False,
                    "moved": None, "notes": blocked_notes or ["nothing to schedule"], "source": source,
                    "cap_min": cap_min, "over": None, "plug_now": False, "segments": [], "nothing": True}
            if not dry_run:
                self.auto_plug_last = plan
                logger.info("%s: nothing scheduled (%s)", SOURCE_NAMES.get(source, "Charge"), "; ".join(plan["notes"]))
            return plan
        end = segments[-1][1]
        minutes = int(round(sum((y - x).total_seconds() for x, y in segments) / 60))
        plug_now = segments[0][0] <= now

        def one_off(t, action, src=source):
            return validate_entry({"time": t.strftime("%H:%M"), "date": t.date().isoformat(),
                                   "action": action, "source": src})

        active = self._active_entries()
        seg_entries = []  # plug / unplug for each part but the last's unplug
        for i, (x, y) in enumerate(segments):
            seg_entries.append(one_off(x, "plug"))
            if i < len(segments) - 1:
                seg_entries.append(one_off(y, "unplug"))
        unplug = one_off(end, "unplug")
        start_day = now.date() - datetime.timedelta(days=1)
        # The scheduled slots still to come (the first may meet the charge),
        # up to 3 days on: the ones that can be trimmed
        later = [s for s in self._stretches(start_day, 5, active, self.skips)
                 if s["end"] > now and s["start"] < end + datetime.timedelta(days=3)]
        nxt0 = later[0] if later else None
        if later and later[0]["start"] <= now:
            later = later[1:]  # one going now isn't trimmed
        can_trim = bool(later)

        def build(cuts: dict):
            """The entries and skips for the charge, with the first `cuts[i]`
            minutes of later slot i taken off (all of it: skipped)."""
            added, skips, nxt, notes = list(seg_entries), list(self.skips), nxt0, []
            for i, s in enumerate(later):
                cut = cuts.get(i)
                if not cut:
                    continue
                new_start = s["start"] + datetime.timedelta(minutes=cut)
                skips.append({"entry_id": s["plug"]["id"], "date": s["start"].date().isoformat()})
                if new_start < s["end"]:
                    plug_later = one_off(new_start, "plug", s["plug"].get("source"))  # still that slot's own kind
                    added.append(plug_later)
                    trimmed = dict(s, start=new_start, plug=plug_later)
                    notes.append(f"the {s['end'].strftime('%H:%M')} slot now starts at {new_start.strftime('%H:%M')}")
                else:
                    skips.append({"entry_id": s["unplug"]["id"], "date": s["end"].date().isoformat()})
                    notes.append(f"the {s['start'].strftime('%H:%M')}–{s['end'].strftime('%H:%M')} slot is skipped"
                                 + (f" ({s['start'].strftime('%a')})" if s["start"].date() != now.date() else ""))
                    trimmed = None
                if s is nxt0:
                    nxt = trimmed
            note = "; ".join(notes) or None
            combined = nxt is not None and end >= nxt["start"]
            if combined:
                # One slot: plugged in from now to the scheduled unplug
                if nxt["start"] > now:
                    if nxt["plug"] in added:
                        added.remove(nxt["plug"])
                    else:
                        skips.append({"entry_id": nxt["plug"]["id"], "date": nxt["start"].date().isoformat()})
                slot_end = nxt["end"]
            else:
                added.append(unplug)
                slot_end = end
            # A scheduled unplug during the charge (e.g. an "unplug at 07:00
            # every day") would end it early: skipped this once
            parts = segments[:-1] + [(segments[-1][0], nxt["start"] if combined else end)]
            for t, e, skipped in self.timeline(now.date() - datetime.timedelta(days=1), 4, active, skips):
                if not skipped and e["action"] == "unplug" and any(x < t < y for x, y in parts):
                    skips.append({"entry_id": e["id"], "date": t.date().isoformat()})
            return added, skips, combined, slot_end, note

        span = (now - datetime.timedelta(days=1), (later[-1]["end"] if later else end) + span_len)
        base = self.windows(active, now, self.skips)  # the schedule without this charge

        def totals_for(cuts: dict) -> tuple:
            """(most minutes in any 24 hours; most minutes the charge puts any
            24 hours over the cap, beyond what the schedule already had; the
            same for the 24 hours that meet each later slot, which trimming it
            can fix: {i: minutes})."""
            added, skips, *_ = build(cuts)
            wins = self.windows(active + added, now, skips)
            worst = excess = 0
            near = {}
            for a in limit_starts(wins + base, span[0], span[1], reset, loc):
                stop = limit_end(a, reset, loc)
                with_it = window_minutes(wins, a, stop)
                worst = max(worst, with_it)
                ex = with_it - max(cap_min, window_minutes(base, a, stop))
                excess = max(excess, ex)
                for i, s in enumerate(later):
                    if a < s["end"] and stop > s["start"]:
                        near[i] = max(near.get(i, 0), ex)
            return worst, excess, near

        cuts, before, after, added_over, left_over = {}, None, None, 0, 0
        if cap_min:
            before, added_over, near = totals_for(cuts)
            after, left_over = before, added_over
            # Each later slot in turn, the next first: its first half hours
            # come off, just enough (or all of it, then the one after)
            for i, s in enumerate(later):
                if near.get(i, 0) <= 0:
                    continue
                length = (s["end"] - s["start"]).total_seconds() / 60
                best = None
                for c in range(30, int(math.ceil(length / 30)) * 30 + 1, 30):
                    total, ex, n = totals_for({**cuts, i: c})
                    if n.get(i, 0) < near[i] and (best is None or n.get(i, 0) < best[3].get(i, 0)):
                        best = (c, total, ex, n)
                    if n.get(i, 0) <= 0:
                        break
                if best:
                    cuts[i] = best[0]
                    after, left_over, near = best[1], best[2], best[3]
        added, skips, combined, slot_end, moved = build(cuts)
        # Longer than the limit across its reset time (e.g. 08:00-18:00 with
        # Octopus's 12:00): split there, a fresh charge with its own ready time
        splits = self._reset_splits(active + added, skips, cap_min, one_off=True, until=slot_end) if cap_min else []
        added += splits
        changed = {"skips": [k for k in skips if k not in self.skips],
                   "added": [e["id"] for e in added if e["id"] not in {x["id"] for x in seg_entries + [unplug]}]}
        if changed["skips"] or changed["added"]:
            added[0] = dict(added[0], trims=changed)  # put back if this charge is deleted
        notes = ([shortened] if shortened else []) + blocked_notes
        if moved:
            notes.append(moved)
        if combined:
            notes.append(f"joined with the scheduled slot until {slot_end.strftime('%H:%M')}")
        if splits:
            notes.append("a fresh charge from " + ", ".join(sorted({e["time"] for e in splits}))
                         + f" ({provider}'s daily limit resets then)")
        plan = {
            "at": _iso_local(now), "minutes": minutes, "ready_for": _iso_local(end),
            "end": _iso_local(slot_end), "combined": combined, "moved": moved, "notes": notes,
            "source": source, "cap_min": cap_min,
            # before / after: the most minutes in any 24 hours; added / left: how
            # far this charge takes it over the cap (beyond the schedule's own),
            # before and after the next slot is trimmed
            "over": {"before": before, "after": after, "added": added_over, "left": left_over} if cap_min else None,
            # plugged in straight away (False: it starts after a no-charging time)
            "plug_now": plug_now,
            "segments": [{"start": _iso_local(x), "end": _iso_local(y)} for x, y in segments],
        }
        if dry_run:
            return plan
        self.entries = self.entries + added
        self.skips = [dict(k) for i, k in enumerate(skips) if k not in skips[:i]]
        self._save()
        self.auto_plug_last = plan
        logger.info("%s: plugged in until %s%s", SOURCE_NAMES.get(source, "Charge"),
                    slot_end.strftime("%a %H:%M"),
                    f" ({'; '.join(notes)})" if notes else "")
        if cap_min and left_over > 0:
            logger.warning("%s: the schedule plugs in for %dh %02dm in %s, over %s's %s hours",
                           SOURCE_NAMES.get(source, "Charge"), after // 60, after % 60,
                           f"a day (from {fixed})" if fixed else f"{int(span_len.total_seconds() // 3600)} hours",
                           provider, _hours(cap_min))
        return plan

    def set_skip(self, entry_id: str, date: str, skip: bool = True) -> None:
        """Skip (or un-skip) one upcoming time: entry `entry_id` on `date`."""
        self.set_skips([{"entry_id": entry_id, "date": date}], skip)

    def set_skips(self, times: list, skip: bool = True, daily_cap_min: Optional[int] = None,
                  provider: str = "your supplier") -> None:
        """Skip (or un-skip) several times at once, e.g. a slot's plug-in and
        unplug: [{"entry_id", "date"}, ...]. All or nothing. With daily_cap_min
        (Octopus, while the schedule sets its ready time), a change that takes a
        day over it is refused, as when saving the schedule."""
        if not isinstance(times, list) or not times:
            raise ValueError("Say which times to skip")
        keys = []
        for t in times:
            entry_id, date = str((t or {}).get("entry_id") or ""), (t or {}).get("date")
            entry = next((e for e in self.entries if e["id"] == entry_id), None)
            if entry is None:
                raise ValueError("No such schedule time (save the schedule first)")
            day = _parse_date(date)
            if not any(True for _ in self._occurrences(entry, day, 1)):
                raise ValueError(f"That time doesn't run on {date}")
            keys.append(({"entry_id": entry_id, "date": day.isoformat()}, entry))
        if daily_cap_min and self.ready_time and not self.override_guards:
            new = list(self.skips)
            for key, _ in keys:
                new = [k for k in new if k != key] + ([key] if skip else [])
            if self._makes_worse(daily_cap_min, (self.entries, self.skips), (self.entries, new)):
                self.check_daily_cap(self.entries, daily_cap_min, provider, new)  # raises, with the details
        if not skip:
            new = list(self.skips)
            for key, _ in keys:
                new = [k for k in new if k != key]
            self.check_blocks(self.entries, self.blocks, new)  # e.g. a no-charging time added while it was skipped
        for key, entry in keys:
            self.skips = [k for k in self.skips if k != key] + ([key] if skip else [])
            logger.info("Schedule: %s the %s at %s on %s", "skipping" if skip else "no longer skipping",
                        "plug-in" if entry["action"] == "plug" else "unplug", entry["time"], key["date"])
        self._prune()
        self._save()

    def upcoming(self, days: int = 7) -> list:
        """The next times over `days` days, for the page."""
        now = self._now()
        out = []
        for occ, entry, skipped in self.timeline(now.date(), days + 1):
            if now < occ <= now + datetime.timedelta(days=days):
                out.append({"time": _iso_local(occ), "date": occ.date().isoformat(), "entry_id": entry["id"],
                            "action": entry["action"], "skipped": skipped, "one_off": bool(entry.get("date"))})
        return out[:30]

    def due(self) -> list[dict]:
        """Entries whose time has come since the last check (empty on the first)."""
        now = self._now()
        prev, self._last_check = self._last_check, now
        if prev is None or now <= prev:
            return []  # (with the schedule off, only auto plug-in times run: see timeline)
        start = prev.date() - datetime.timedelta(days=1)
        span = (now.date() - start).days + 1
        due = []
        timeline = self.timeline(start, span)
        plugs_at = {occ for occ, e, skipped in timeline if e["action"] == "plug" and not skipped}
        for occ, entry, skipped in timeline:
            if prev < occ <= now and (now - occ).total_seconds() <= CATCH_UP_S:
                if skipped:
                    logger.info("Schedule: %s at %s skipped",
                                "plug-in" if entry["action"] == "plug" else "unplug", entry["time"])
                elif entry["action"] == "unplug" and occ in plugs_at:
                    # One slot ends as the next starts: unplug straight away (no
                    # waiting for the supplier) and plug back in for the next, so
                    # it's two charges, each with its own ready time (e.g. Octopus:
                    # 6 hours before a 12:00 reset and 6 after)
                    due.append(dict(entry, back_to_back=True))
                else:
                    due.append(entry)
        if prev.date() != now.date() and self._prune():  # tidy up once a day
            self._save()
        return due

    def last_event(self, at: datetime.datetime) -> Optional[tuple[datetime.datetime, dict]]:
        """The schedule's most recent enabled time at or before `at` (within a week)."""
        best = None
        for occ, entry, skipped in self.timeline(at.date() - datetime.timedelta(days=7), 9):
            if occ <= at and not skipped:
                best = (occ, entry)  # in order, so the last one wins
        return best

    def in_plug_window(self, at: Optional[datetime.datetime] = None) -> Optional[datetime.datetime]:
        """When the plugged-in stretch we're in started, if the schedule (on)
        has the car plugged in at `at` (default now); else None."""
        if not self.schedule_enabled:
            return None
        last = self.last_event(at or self._now())
        return last[0] if last and last[1]["action"] == "plug" else None

    def next_unplug(self, after: datetime.datetime) -> Optional[datetime.datetime]:
        """The schedule's next unplug after `after` (within a week). Back-to-back
        slots each have their own: they unplug and plug back in where they meet."""
        for occ, entry, skipped in self.timeline(after.date(), 8):
            if occ > after and entry["action"] == "unplug" and not skipped:
                return occ
        return None

    def next_action(self) -> Optional[dict]:
        if not self.schedule_enabled:
            return None
        now = self._now()
        for occ, entry, skipped in self.timeline(now.date(), 8):
            if occ > now and not skipped:
                return {"time": _iso_local(occ), "action": entry["action"], "entry_id": entry["id"]}
        return None

    # --- the supplier's plan vs the schedule ------------------------------------

    def update_plan_check(self, plan: Optional[dict], plugged_in: bool) -> Optional[dict]:
        """plan: {"found", "provider", "slots", "supplier_ready"} from HaLink.supplier_plan.
        Checked only with Force schedule on supplier, while the schedule has the
        car plugged in, up to the ready time set for this stretch."""
        result = None
        since = self.in_plug_window() if self.ready_time and plugged_in else None
        end = self.next_unplug(self._now()) if since is not None else None
        if end is not None and plan and plan.get("found"):
            r = self.ready_status or {}
            ready_at = _parse_iso(r.get("ready_at"))
            set_at = _parse_iso(r.get("at"))
            # The ready time set for this stretch (at its plug-in)
            this_stretch = (not r.get("error") and set_at is not None and set_at >= since - datetime.timedelta(minutes=1))
            until = ready_at if this_stretch and ready_at is not None and since < ready_at <= end else end
            settle_from = max(since, set_at) if this_stretch else since
            check_at = settle_from + datetime.timedelta(seconds=SETTLE_S)
            if self._now() < check_at:
                result = {"status": "waiting", "start": _iso_local(since), "end": _iso_local(end),
                          "until": _iso_local(until), "check_at": _iso_local(check_at), "problems": []}
            else:
                result = check_plan(plan.get("slots") or [], since, end, until,
                                    ready_set=r.get("ready") if this_stretch else None,
                                    supplier_ready=plan.get("supplier_ready"),
                                    provider=plan.get("provider") or "Your supplier")
            result["provider"] = plan.get("provider")
        problems = tuple(result["problems"]) if result else ()
        if problems != self._plan_problems:
            for text in problems:
                if text not in self._plan_problems:
                    logger.warning("Supplier plan doesn't match the schedule: %s", text)
            if not problems and result and result["status"] != "waiting":
                logger.info("Supplier plan matches the schedule again")
            self._plan_problems = problems
        self.plan_check = result
        return result

    # --- re-plug -------------------------------------------------------------

    def replug_due(self, plugged_in: bool, in_session: bool, connected: bool,
                   scheduled: Optional[bool] = None, slot_now: Optional[bool] = None) -> bool:
        """Call regularly; True when it's time to re-plug.

        scheduled: your supplier has a charge slot planned (None: unknown, so
        only a session counts). slot_now: one is running now, so the wait
        counts from the next half hour (when the supplier may start)."""
        now = self._clock()
        self.scheduled = bool(scheduled) and plugged_in and not in_session
        self.slot_now = bool(slot_now) and plugged_in and not in_session
        if self.replugging:
            return False
        if in_session or not plugged_in or scheduled:
            # A session started or was scheduled, or the car was unplugged:
            # start afresh (if a planned slot is dropped, the wait starts then)
            self.attempts_used = 0
            self.gave_up = False
            self.waiting_since = None
            return False
        if not connected or not self.replug["enabled"]:
            self.waiting_since = None  # the wait restarts once back online / on
            return False
        if self.waiting_since is None:
            self.waiting_since = now
            return False
        if now < self._replug_at():
            return False
        if self.attempts_used >= self.replug["attempts"]:
            if not self.gave_up:
                self.gave_up = True
                logger.warning(
                    "Still no session %d min after plugging in, after %d re-plug(s): giving up "
                    "until the car is next unplugged or a session starts",
                    self.replug["after_min"], self.attempts_used,
                )
            return False
        return True

    def _replug_at(self) -> float:
        """When the wait for a session runs out (waiting_since must be set)."""
        start = self.waiting_since
        if self.slot_now:  # the supplier may only start at the next half hour
            start = -(-start // HALF_HOUR_S) * HALF_HOUR_S
        return start + self.replug["after_min"] * 60

    async def run_replug(self, unplug: Callable[..., Awaitable[None]], plug: Callable[..., Awaitable[None]],
                         wait_s: Optional[float] = None) -> None:
        self.attempts_used += 1
        logger.warning(
            "No session from the supplier %d min after plugging in: re-plugging (try %d of %d)",
            self.replug["after_min"], self.attempts_used, self.replug["attempts"],
        )
        self.replugging = True
        try:
            await unplug(source="auto re-plug")
            await asyncio.sleep(self.replug.get("off_s", REPLUG_WAIT_S) if wait_s is None else wait_s)
            await plug(source="auto re-plug")
        finally:
            self.replugging = False
            self.last_replug = self._clock()
            self.waiting_since = self._clock()

    # --- status --------------------------------------------------------------

    def replug_status(self) -> dict:
        r = self.replug
        if not r["enabled"]:
            status = "off"
        elif self.replugging:
            status = "replugging"
        elif self.gave_up:
            status = "gave_up"
        elif self.scheduled:
            status = "scheduled"
        elif self.waiting_since is not None:
            status = "waiting"
        else:
            status = "idle"
        next_at = None
        if status == "waiting" and self.attempts_used < r["attempts"]:
            next_at = self._replug_at()
        return {
            **r,
            "status": status,
            "attempts_used": self.attempts_used,
            "waiting_since": _iso_from_epoch(self.waiting_since),
            "next_replug_at": _iso_from_epoch(next_at),
            "last_replug": _iso_from_epoch(self.last_replug),
        }

    def snapshot(self) -> dict:
        return {
            "timezone": timezone_name(),
            "now": _iso_local(self._now()),
            "schedule": {
                "enabled": self.schedule_enabled,
                "entries": self.entries,
                "next": self.next_action(),
                "last_run": self.last_run,
                "ready_time": self.ready_time,
                "ready_status": self.ready_status,
                "auto_plug_last": self.auto_plug_last,
                "one_off_runs": self.one_off_runs(),
                "unplug_wait_s": self.unplug_wait_s,
                "override_guards": self.override_guards,
                "blocks": self.blocks,
                "plan_check": self.plan_check,
                "skips": self.skips,
                "upcoming": self.upcoming(),
            },
            "replug": self.replug_status(),
        }

    def publish(self, shared_state) -> None:
        shared_state.schedule_enabled = self.schedule_enabled
        shared_state.schedule_next = self.next_action()
        shared_state.replug = self.replug_status()
        shared_state.unplug_pending = _iso_from_epoch(self.unplug_at)
        shared_state.plan_check = self.plan_check


async def apply_ready_time(automation: "Automation",
                           set_ready_time: Callable[[datetime.datetime], Awaitable[dict]],
                           log_errors: bool = True) -> dict:
    """At a scheduled plug-in: ready time = the schedule's next unplug."""
    now = automation._now()
    unplug = automation.next_unplug(now)
    if unplug is None:
        result = {"error": "There's no unplug in the schedule after this plug-in"}
    else:
        try:
            result = await set_ready_time(unplug)
        except Exception as err:
            result = {"unplug": unplug.isoformat(timespec="minutes"), "error": str(err)}
    if result.get("error") and log_errors:
        logger.warning("Ready time not set: %s", result["error"])
    automation.ready_status = {**result, "at": _iso_from_epoch(automation._clock())}
    return result


async def auto_plug_charge(automation: "Automation", hours: float,
                           set_ready_time: Optional[Callable[[datetime.datetime], Awaitable[dict]]] = None,
                           ready_times: Optional[list] = None, cap_min: Optional[int] = None,
                           provider: str = "your supplier", source: str = AUTO_SOURCE,
                           dry_run: bool = False) -> dict:
    """Auto plug-in (or Charge now) just plugged in: plan the charge and set
    the ready time. dry_run: only work out what would be done."""
    plan = automation.plan_auto_plug(int(round(hours * 60)), ready_times, cap_min, provider, source, dry_run)
    if dry_run:
        return plan
    if set_ready_time is not None:
        await apply_ready_time(automation, set_ready_time)
    return plan


async def automation_loop(
    automation: Automation,
    shared_state,
    plug: Callable[[], Awaitable[None]],
    unplug: Callable[[], Awaitable[None]],
    tick_s: float = TICK_S,
    scheduled: Optional[Callable[[], Optional[bool]]] = None,
    slot_now: Optional[Callable[[], Optional[bool]]] = None,
    set_ready_time: Optional[Callable[[datetime.datetime], Awaitable[dict]]] = None,
    supplier_plan: Optional[Callable[[], Optional[dict]]] = None,
) -> None:
    """Run the schedule and re-plug for the life of the add-on.

    scheduled: whether your supplier has a charge slot planned for later,
    slot_now: whether one is running now (None if its integration isn't
    there); both also shown as the add-on's status.
    supplier_plan: the supplier's slots and ready time, for the plan check."""
    started = automation._clock()
    ready_pending = False  # a start-up plug-in's ready time, until HA is there to take it
    first = True
    while True:
        try:
            shared_state.scheduled = scheduled() if scheduled is not None else None
            shared_state.slot_now = slot_now() if slot_now is not None else None
            if first:
                first = False
                since = automation.in_plug_window()
                if since is not None and not shared_state.plugged_in:
                    logger.info("Started inside a scheduled plug-in (since %s): plugging in", since.strftime("%a %H:%M"))
                    automation.last_run = {"entry_id": None, "action": "plug",
                                           "timestamp": _iso_from_epoch(automation._clock()), "startup": True}
                    await plug(source="schedule")
                    ready_pending = automation.ready_time and set_ready_time is not None
            if ready_pending:
                # HA (or the supplier's sensor) may not be there yet just after start-up
                last_try = automation._clock() - started >= STARTUP_READY_S
                result = await apply_ready_time(automation, set_ready_time, log_errors=last_try)
                ready_pending = bool(result.get("error")) and not last_try
            for entry in automation.due():
                automation.last_run = {
                    "entry_id": entry["id"], "action": entry["action"],
                    "timestamp": _iso_from_epoch(automation._clock()),
                }
                if entry.get("back_to_back"):
                    # Where two slots meet: a fresh charge for the next one
                    automation.unplug_at = None
                    off = automation.replug.get("off_s", REPLUG_WAIT_S)
                    logger.info("Schedule: one slot ends and the next starts at %s: unplugging, "
                                "plugging back in after %d s", entry["time"], off)
                    await unplug(source="schedule")
                    await asyncio.sleep(off)
                elif entry["action"] == "plug":
                    automation.unplug_at = None  # a waiting unplug is overtaken
                    logger.info("Schedule: plugging in at %s", entry["time"])
                    await plug(source="schedule")
                    if automation.ready_time and set_ready_time is not None:
                        await apply_ready_time(automation, set_ready_time)
                elif ((automation.ready_time or entry.get("source") in AUTO_SOURCES)
                      and automation.unplug_wait_s and shared_state.transaction_id is not None):
                    # Give the supplier a chance to end the session itself
                    automation.unplug_at = automation._clock() + automation.unplug_wait_s
                    logger.info("Schedule: unplug at %s, waiting up to %d s for the supplier to stop the session",
                                entry["time"], automation.unplug_wait_s)
                else:
                    logger.info("Schedule: unplugging at %s", entry["time"])
                    await unplug(source="schedule")
            if automation.unplug_at is not None:
                if not shared_state.plugged_in:
                    automation.unplug_at = None  # unplugged meanwhile
                elif shared_state.transaction_id is None:
                    logger.info("Schedule: the supplier stopped the session, unplugging")
                    automation.unplug_at = None
                    await unplug(source="schedule")
                elif automation._clock() >= automation.unplug_at:
                    logger.info("Schedule: the supplier didn't stop the session within %d s, unplugging",
                                automation.unplug_wait_s)
                    automation.unplug_at = None
                    await unplug(source="schedule")
            automation.update_plan_check(supplier_plan() if supplier_plan is not None else None,
                                         plugged_in=bool(shared_state.plugged_in))
            if automation.replug_due(
                # Plugged In and waiting (Preparing); not e.g. Unavailable
                plugged_in=bool(shared_state.plugged_in) and shared_state.state == "Preparing",
                in_session=shared_state.transaction_id is not None,
                connected=bool(shared_state.connected_to_server),
                # a slot running now with no session isn't an answer: re-plug
                scheduled=shared_state.scheduled and not shared_state.slot_now,
                slot_now=shared_state.slot_now,
            ):
                automation.publish(shared_state)
                await automation.run_replug(unplug, plug)
            automation.publish(shared_state)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Automation cycle failed", exc_info=True)
        await asyncio.sleep(min(tick_s, PENDING_TICK_S) if automation.unplug_at is not None else tick_s)
