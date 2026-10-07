"""The web page's charts and daily energy, read from Home Assistant's history.

The add-on posts its Power, Current, Energy, Status and Current limit sensors
to HA (src/ha_entities.py), and HA's recorder keeps them. Rather than keep
its own copy, the add-on asks HA when the page wants them:

- the 30 min to 24 h chart: HA's recorded states, sampled every 10 seconds
  (the last hour comes from memory, so the page's 10-second refresh doesn't
  query HA)
- the 14-day chart and older sessions' power curves: HA's 5-minute
  statistics (hourly beyond HA's recorder retention, 10 days by default)
- energy per day: HA's daily statistics of the Energy sensor (what the
  Energy dashboard shows)

The SoC comes from your SoC sensor's history if one is picked on the Settings
tab. If HA can't be reached the charts show the last hour (from memory) and
the daily bars fall back to the kept sessions.
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Callable, Optional

from src.gui_data import PowerHistory, daily_from_sessions
from src.ha_entities import LIMIT_SENSOR, SENSORS, STATUS_SENSOR

logger = logging.getLogger(__name__)

POWER = SENSORS["power_kw"][0]
CURRENT = SENSORS["current_a"][0]
ENERGY = SENSORS["energy_kwh"][0]

FINE_HOURS = 24
FINE_STEP_S = 10
LONG_DAYS = 14
MAX_KWH_PER_DAY = 200  # more than a home charger can deliver: a meter jump, not energy

# Which state a 5-minute point shows when it saw several (most telling first)
_STATE_RANK = ("Charging", "SuspendedEV", "SuspendedEVSE", "Finishing", "Waiting for supplier", "Scheduled",
               "Preparing")
_GONE = ("unavailable", "unknown", "none", "")


# --- parsing HA's replies -----------------------------------------------------


def _ts(value) -> Optional[float]:
    """HA times: seconds, milliseconds or ISO text -> unix seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value / 1000.0 if value > 1e11 else float(value)
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_history(result: Optional[dict], entity_id: str) -> list[tuple[float, Optional[str], dict]]:
    """history/history_during_period -> [(time, state or None, attributes)].

    Handles the compact form ({"s", "a", "lu"}) and the full one."""
    out = []
    attrs: dict = {}
    for row in (result or {}).get(entity_id) or []:
        if "s" in row:
            state, t, new_attrs = row.get("s"), _ts(row.get("lu")), row.get("a")
        else:
            state, t, new_attrs = row.get("state"), _ts(row.get("last_updated")), row.get("attributes")
        if t is None:
            continue
        if new_attrs is not None:
            attrs = new_attrs
        out.append((t, None if str(state).lower() in _GONE else state, attrs))
    out.sort(key=lambda r: r[0])
    return out


def parse_statistics(result: Optional[dict], statistic_id: str) -> list[dict]:
    """recorder/statistics_during_period -> rows with "start" in unix seconds."""
    rows = []
    for row in (result or {}).get(statistic_id) or []:
        start = _ts(row.get("start"))
        if start is not None:
            rows.append({**row, "start": start})
    rows.sort(key=lambda r: r["start"])
    return rows


def _num(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class _Step:
    """A recorded entity as a step function: the value at any time."""

    def __init__(self, rows: list[tuple[float, Optional[str], dict]]) -> None:
        self.rows, self.i = rows, -1

    def at(self, t: float) -> tuple[Optional[str], dict]:
        """For increasing t only."""
        while self.i + 1 < len(self.rows) and self.rows[self.i + 1][0] <= t:
            self.i += 1
        return (self.rows[self.i][1], self.rows[self.i][2]) if self.i >= 0 else (None, {})

    def states_between(self, t0: float, t1: float) -> list[str]:
        """The state at t0 and every state set before t1 (call at() for t0 first)."""
        states = [self.rows[self.i][1]] if self.i >= 0 and self.rows[self.i][1] else []
        j = self.i + 1
        while j < len(self.rows) and self.rows[j][0] < t1:
            if self.rows[j][1]:
                states.append(self.rows[j][1])
            j += 1
        return states


def _most_telling(states: list[str]) -> Optional[str]:
    for rank in _STATE_RANK:
        if rank in states:
            return rank
    return states[-1] if states else None


# --- building the chart's points ------------------------------------------------


def fine_samples(rows: dict, start: float, end: float, step: float = FINE_STEP_S) -> list[dict]:
    """Recorded states -> chart samples every `step` seconds in [start, end).

    rows: entity -> parse_history() rows, keys "power", "current", "soc",
    "status", "limit". Times the add-on was stopped (no power reading) are
    left out, so the chart breaks the line there."""
    series = {k: _Step(rows.get(k) or []) for k in ("power", "current", "soc", "status", "limit")}
    out = []
    t = start - start % step + step
    while t < end:
        power = _num(series["power"].at(t)[0])
        status = series["status"].at(t)[0]
        current = _num(series["current"].at(t)[0])
        soc = _num(series["soc"].at(t)[0])
        limit, limit_attrs = series["limit"].at(t)
        if power is not None:
            out.append({
                "t": t, "power_kw": power, "current_a": current, "soc": soc,
                "max_amps": limit_attrs.get("max_amps"), "effective_amps": _num(limit),
                "provider_limit_amps": limit_attrs.get("provider_limit_amps"),
                "state": status or "Unknown",
            })
        t += step
    return out


def long_samples(stats: dict, rows: dict) -> list[dict]:
    """Statistics -> one chart point per statistics period (5 min or an hour).

    stats: "power" / "current" / "limit" -> parse_statistics() rows (mean,
    max). rows: "status", "soc", "limit" -> parse_history() rows for the
    state, the SoC and the limit attributes. Each point is at the middle of
    its period, with its length in "d"."""
    current = {r["start"]: r for r in stats.get("current") or []}
    limit_mean = {r["start"]: r for r in stats.get("limit") or []}
    status, soc, limit = (_Step(rows.get(k) or []) for k in ("status", "soc", "limit"))
    power_rows = stats.get("power") or []
    out = []
    for n, row in enumerate(power_rows):
        start = row["start"]
        nxt = power_rows[n + 1]["start"] if n + 1 < len(power_rows) else None
        length = _ts(row.get("end")) and _ts(row.get("end")) - start
        if not length:
            length = 3600.0 if nxt is not None and nxt - start >= 3600 else 300.0
        if row.get("mean") is None:
            continue
        mid = start + length / 2
        status.at(start)
        state = _most_telling(status.states_between(start, start + length))
        soc_value = _num(soc.at(mid)[0])
        limit_attrs = limit.at(mid)[1]
        out.append({
            "t": mid, "d": length,
            "power_kw": round(float(row["mean"]), 3),
            "power_max_kw": None if row.get("max") is None else round(float(row["max"]), 3),
            "current_a": (current.get(start) or {}).get("mean"),
            "soc": soc_value,
            "max_amps": limit_attrs.get("max_amps"),
            "effective_amps": (limit_mean.get(start) or {}).get("mean"),
            "provider_limit_amps": limit_attrs.get("provider_limit_amps"),
            "state": state or "Unknown",
        })
    return out


def charging_per_day(rows: list[tuple[float, Optional[str], dict]], days: list[tuple[str, float, float]],
                     now: float) -> dict[str, float]:
    """Seconds spent Charging per day, from the Status sensor's history.

    days: (date, start, end) in unix seconds. Only days the history fully
    covers are returned (the first row is the state at the start of the
    query, so a day starting before it is unknown)."""
    if not rows:
        return {}
    covered_from = rows[0][0]
    out = {d: 0.0 for d, start, _ in days if start >= covered_from}
    for n, (t, state, _) in enumerate(rows):
        if state != "Charging":
            continue
        t_end = rows[n + 1][0] if n + 1 < len(rows) else now
        for d, start, end in days:
            if d in out:
                out[d] += max(0.0, min(t_end, end) - max(t, start))
    return out


# --- the source the API uses ----------------------------------------------------


class ChartHistory:
    """Chart samples and daily energy for the web page."""

    def __init__(self, ha_link, soc_entity: Callable[[], Optional[str]],
                 recent: Optional[PowerHistory] = None, clock: Callable[[], float] = time.time,
                 today: Callable[[], datetime.date] = lambda: datetime.datetime.now().astimezone().date()) -> None:
        self.link = ha_link
        self.soc_entity = soc_entity
        self.recent = recent or PowerHistory(clock=clock)  # the last hour, in memory
        self._clock = clock
        self._today = today
        self.error: Optional[str] = None  # why HA's history couldn't be read, for the page

    @property
    def _ha(self) -> bool:
        return self.link is not None and self.link.connected

    async def _history(self, ids: list[str], start: float, end: float, attributes: bool) -> dict:
        iso = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()  # noqa: E731
        return await self.link.query({
            "type": "history/history_during_period",
            "start_time": iso(start), "end_time": iso(end),
            "entity_ids": ids,
            "minimal_response": not attributes, "no_attributes": not attributes,
            "significant_changes_only": False,
        }, timeout=60) or {}

    async def _statistics(self, ids: list[str], start: float, end: float, period: str, types: list[str]) -> dict:
        iso = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()  # noqa: E731
        return await self.link.query({
            "type": "recorder/statistics_during_period",
            "start_time": iso(start), "end_time": iso(end),
            "statistic_ids": ids, "period": period, "types": types,
        }, timeout=60) or {}

    async def _rows(self, start: float, end: float) -> dict:
        """Status, SoC and limit (with attributes) as recorded by HA."""
        soc = self.soc_entity()
        plain = await self._history([STATUS_SENSOR] + ([soc] if soc else []), start, end, attributes=False)
        with_attrs = await self._history([LIMIT_SENSOR], start, end, attributes=True)
        return {
            "status": parse_history(plain, STATUS_SENSOR),
            "soc": parse_history(plain, soc) if soc else [],
            "limit": parse_history(with_attrs, LIMIT_SENSOR),
        }

    async def samples(self, since: float = 0.0) -> list[dict]:
        """10-second samples newer than `since` (up to 24 hours back)."""
        now = self._clock()
        recent = self.recent.since(since)
        first = self.recent.since(0)[:1]
        recent_start = first[0]["t"] if first else now
        start = max(since, now - FINE_HOURS * 3600)
        if start >= recent_start - FINE_STEP_S or not self._ha:
            return recent
        try:
            plain = await self._history([POWER, CURRENT], start, recent_start, attributes=False)
            rows = await self._rows(start, recent_start)
            rows["power"] = parse_history(plain, POWER)
            rows["current"] = parse_history(plain, CURRENT)
            older = fine_samples(rows, start, recent_start)
            self.error = None
        except Exception as err:
            self.error = f"Home Assistant history not available: {err}"
            logger.debug("%s", self.error)
            return recent
        return older + recent

    async def long_samples(self, since: float = 0.0) -> list[dict]:
        """5-minute (or hourly, when older) points newer than `since`, up to 14 days back."""
        now = self._clock()
        start = max(since, now - LONG_DAYS * 86400)
        if not self._ha:
            return []
        try:
            ids = [POWER, CURRENT, LIMIT_SENSOR]
            five = await self._statistics(ids, start, now, "5minute", ["mean", "max"])
            first5 = min((r["start"] for r in parse_statistics(five, POWER)), default=now)
            hourly = await self._statistics(ids, start, first5, "hour", ["mean", "max"]) if first5 - start > 3600 else {}
            stats = {
                key: [r for r in parse_statistics(hourly, sid) if r["start"] + 3600 <= first5] + parse_statistics(five, sid)
                for key, sid in (("power", POWER), ("current", CURRENT), ("limit", LIMIT_SENSOR))
            }
            rows = await self._rows(start - 3600, now)
            self.error = None
        except Exception as err:
            self.error = f"Home Assistant statistics not available: {err}"
            logger.debug("%s", self.error)
            return []
        return [p for p in long_samples(stats, rows) if p["t"] > since]

    async def daily(self, days: int, sessions: list) -> list[dict]:
        """kWh and time spent charging per day for the last `days` days.

        kWh: HA's daily statistics of the Energy sensor, or the kept sessions
        where those are missing or lower (e.g. today until HA's next hourly
        statistics). Charging time: from the Status sensor's history (2.3.0
        on), else estimated from the sessions' lengths."""
        metered: dict[str, float] = {}
        charging: dict[str, float] = {}
        if self._ha:
            today = self._today()
            first = today - datetime.timedelta(days=days - 1)
            start = datetime.datetime.combine(first, datetime.time()).astimezone().timestamp()
            bounds = []
            for i in range(days):
                day = first + datetime.timedelta(days=i)
                d0 = datetime.datetime.combine(day, datetime.time()).astimezone().timestamp()
                d1 = datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time()).astimezone().timestamp()
                bounds.append((day.isoformat(), d0, d1))
            try:
                status = await self._history([STATUS_SENSOR], start, self._clock(), attributes=False)
                charging = charging_per_day(parse_history(status, STATUS_SENSOR), bounds, self._clock())
            except Exception as err:
                logger.debug("Status history not available: %s", err)
            try:
                result = await self._statistics([ENERGY], start, self._clock(), "day", ["change"])
                for row in parse_statistics(result, ENERGY):
                    change = _num(row.get("change"))
                    if change is not None and 0 <= change <= MAX_KWH_PER_DAY:
                        day = datetime.datetime.fromtimestamp(row["start"]).astimezone().date().isoformat()
                        metered[day] = change
                self.error = None
            except Exception as err:
                self.error = f"Home Assistant statistics not available: {err}"
                logger.debug("%s", self.error)
        return daily_from_sessions(days, sessions, self._today(), metered, charging)
