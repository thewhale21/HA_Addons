"""Feeds the Stellantis Vehicles integration's readings into the statistics
(src/evstats.py), live and, once, from Home Assistant's history, and keeps
the page's headline figures and the add-on's sensors up to date."""
from __future__ import annotations

import datetime
import logging
import time
from typing import Optional

from src.evstats import EvStats, forecast_temp, next_departure, number, parse_trip, to_c, to_km

logger = logging.getLogger(__name__)

HISTORY_DAYS = 30  # read once at the start (HA keeps 10 days by default)
NUMERIC = ("soc", "range", "temperature", "residual", "capacity", "soh_capacity", "soh_resistance", "odometer", "plugged")


def _value(key: str, state, unit: Optional[str]) -> Optional[float]:
    """A reading in the add-on's units (km, °C, %, kWh), or None if there isn't one."""
    if state is None or str(state).lower() in ("unknown", "unavailable", "none", ""):
        return None
    v = number(state)
    if v is None:
        return None
    if key in ("range", "odometer"):
        return to_km(v, unit)
    if key == "temperature":
        return to_c(v, unit)
    if key in ("residual", "capacity") and (unit or "").lower() == "wh":
        return v / 1000
    return v


class Feed:
    """Applies readings, in time order, to an EvStats: the latest of each is kept in `cur`."""

    def __init__(self, stats: EvStats) -> None:
        self.stats = stats
        self.cur: dict[str, Optional[float]] = {}

    def apply(self, key: str, ts: float, state, attrs: Optional[dict], unit: Optional[str],
              source: str = "live") -> Optional[dict]:
        """One reading. Returns a trip if it was a new one."""
        s, cur = self.stats, self.cur
        if key == "last_trip":
            if str(state).lower() in ("unknown", "unavailable", "none", ""):
                return None
            return s.trip(ts, parse_trip(state, attrs or {}, unit or "km"), source)
        if key == "plugged":
            on = str(state).lower()
            s.plugged(ts, True if on == "on" else False if on == "off" else None)
            return None
        if key == "weather":
            return None
        cur[key] = _value(key, state, unit)
        if key == "temperature":
            s.temperature(ts, cur[key])
        if key == "soc":
            s.soc(ts, cur[key])
        if key in ("soc", "range"):
            s.range_reading(ts, cur.get("soc"), cur.get("range"), cur.get("temperature"))
        if key in ("soc", "residual"):
            s.residual(ts, cur.get("residual"), cur.get("soc"))
        if key in ("soh_capacity", "soh_resistance"):
            s.soh(ts, cur.get("soh_capacity"), cur.get("soh_resistance"))
        return None


def history_events(history: dict, entities: dict) -> list[tuple]:
    """history/history_during_period's {entity_id: [states]} as (ts, key, state, attributes), oldest first."""
    out = []
    for key, entity_id in entities.items():
        for item in (history or {}).get(entity_id) or []:
            ts = item.get("lu") or item.get("lc")
            if ts is None and item.get("last_updated"):
                try:
                    ts = datetime.datetime.fromisoformat(str(item["last_updated"]).replace("Z", "+00:00")).timestamp()
                except ValueError:
                    ts = None
            if ts is not None:
                out.append((float(ts), key, item.get("s", item.get("state")), item.get("a", item.get("attributes"))))
    out.sort(key=lambda e: (e[0], e[1] != "last_trip"))  # a trip after the readings at the same moment
    return out


class Runner:
    def __init__(self, link, stats: EvStats, settings, state) -> None:
        self.link, self.stats, self.settings, self.state = link, stats, settings, state
        self.feed = Feed(stats)
        self._saved_at = 0.0
        self.forecast: Optional[dict] = None  # the next commute's {"at", "temp_c", "source"}
        self._forecast_at = 0.0

    def unit(self, key: str) -> Optional[str]:
        st = self.link.states.get(self.link.settings.get(key) or "") or {}
        return (st.get("attributes") or {}).get("unit_of_measurement")

    async def entity_changed(self, entity_id: str, st: Optional[dict]) -> None:
        """A watched entity changed (src/ha_link.py)."""
        for key in self.link.key_for(entity_id):
            if st is None:
                continue
            attrs = st.get("attributes") or {}
            trip = self.feed.apply(key, float(st.get("ts") or time.time()), st.get("state"), attrs,
                                   attrs.get("unit_of_measurement"))
            if trip:
                logger.info("Trip: %.1f mi, %s kWh, %s °C", trip["km"] / 1.609344, trip.get("kwh"), trip.get("temp_c"))
        self.refresh()

    def current(self) -> dict:
        c = self.feed.cur
        return {"soc": c.get("soc"), "range_km": c.get("range"), "temp_c": c.get("temperature"),
                "odometer_km": c.get("odometer"), "residual_kwh": c.get("residual"),
                "capacity_kwh": c.get("capacity"), "forecast": self.forecast}

    def summary(self, now: Optional[float] = None) -> dict:
        return self.stats.summary(time.time() if now is None else now, self.settings.data,
                                  capacity_sensor=self.feed.cur.get("capacity"), current=self.current())

    def refresh(self, now: Optional[float] = None) -> None:
        """The headline figures for the page and the sensors; saves now and then."""
        now = time.time() if now is None else now
        sm = self.summary(now)
        brief = {k: sm[k] for k in ("now", "efficiency", "usable_kwh", "usable_from", "commute")}
        brief["drain"] = {k: sm["drain"][k] for k in ("pct_per_day", "mi_per_day", "spells", "days")}
        brief["health"] = {k: sm["health"][k] for k in ("soh_capacity", "soh_resistance")}
        self.state.car = self.current()
        if brief != self.state.brief or self.state.trips != sm["trip_count"]:
            self.state.stats_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.state.brief, self.state.trips = brief, sm["trip_count"]
        if not self.link.settings.get("last_trip"):
            self.state.status, self.state.reason = "Waiting", "Pick the car's Last trip sensor on the Settings tab"
        elif not self.link.connected:
            self.state.status, self.state.reason = "Offline", "Not connected to Home Assistant"
        else:
            self.state.status = "Recording"
            self.state.reason = f"{sm['trip_count']} trip{'' if sm['trip_count'] == 1 else 's'} recorded"
        if self.stats.dirty and now - self._saved_at >= 60:
            self.stats.save()
            self._saved_at = now

    async def refresh_forecast(self, now: Optional[datetime.datetime] = None, every_s: float = 1800) -> None:
        """The temperature forecast for the next commute (weather.get_forecasts), every half hour."""
        s = self.settings.data
        entity = self.link.settings.get("weather")
        if not s.get("commute_mi"):
            self.forecast = None
            return
        if time.time() - self._forecast_at < every_s and self.forecast is not None:
            return
        now = now or datetime.datetime.now().astimezone()
        at = next_departure(now, s.get("commute_time", "07:30"), s.get("commute_days") or [])
        if at is None:
            return
        temp, source = None, None
        st = self.link.states.get(entity or "") or {}
        unit = (st.get("attributes") or {}).get("temperature_unit")
        if entity:
            for kind in ("hourly", "daily"):
                try:
                    res = await self.link.query({
                        "type": "call_service", "domain": "weather", "service": "get_forecasts",
                        "service_data": {"type": kind}, "target": {"entity_id": entity}, "return_response": True})
                except Exception as err:
                    logger.debug("No %s forecast from %s: %s", kind, entity, err)
                    continue
                forecast = (((res or {}).get("response") or {}).get(entity) or {}).get("forecast") or []
                temp = forecast_temp(forecast, at, kind == "hourly")
                if temp is not None:
                    temp, source = to_c(temp, unit), f"{entity} ({kind} forecast)"
                    break
        if temp is None:  # no forecast: the temperature now
            temp, source = self.feed.cur.get("temperature"), "the temperature now (no forecast)"
        self.forecast = {"at": at.isoformat(timespec="minutes"), "temp_c": None if temp is None else round(temp, 1),
                         "source": source}
        self._forecast_at = time.time()
        self.refresh()

    async def backfill(self) -> None:
        """Once: the last HISTORY_DAYS of the sensors from Home Assistant's history."""
        if self.stats.backfilled:
            return
        entities = {k: v for k, v in self.link.settings.items() if v}
        if not entities.get("last_trip"):
            return
        start = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=HISTORY_DAYS)).isoformat()
        numeric = {k: v for k, v in entities.items() if k in NUMERIC}
        history = {}
        if numeric:
            history.update(await self.link.query({
                "type": "history/history_during_period", "start_time": start, "entity_ids": list(numeric.values()),
                "minimal_response": True, "no_attributes": True, "significant_changes_only": False}, timeout=120) or {})
        history.update(await self.link.query({  # the trips need their attributes
            "type": "history/history_during_period", "start_time": start, "entity_ids": [entities["last_trip"]],
            "minimal_response": False, "no_attributes": False, "significant_changes_only": False}, timeout=120) or {})
        old = EvStats()
        feed = Feed(old)
        for ts, key, state, attrs in history_events(history, entities):
            unit = (attrs or {}).get("unit_of_measurement") or self.unit(key)
            feed.apply(key, ts, state, attrs, unit, source="history")
        found = self.stats.merge(old)
        self.stats.backfilled = True
        self.stats.save()
        self.state.backfill = (f"{found['trips']} trips, {found['ranges']} range readings and "
                               f"{found['health']} battery health readings from the last {HISTORY_DAYS} days")
        logger.info("History: %s", self.state.backfill)
        self.refresh()
