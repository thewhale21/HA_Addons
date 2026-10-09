"""The car's statistics, from the Stellantis Vehicles integration's sensors.

What's recorded (saved in /data/evstats.json):

- Trips: each new "Last trip" (the integration fetches it when the car
  stops) with its distance and energy, the outside temperature over the
  trip (the car's Temperature sensor, or one you pick) and the SoC before
  and after it.
- Range readings: the car's own range estimate with the SoC and the
  temperature at the time, so its estimate for a full battery can be
  compared with what you really get.
- Battery: the integration's SoH figures (capacity and resistance) when
  they change, and the usable energy in the battery (Battery residual ÷ SoC)
  as a measured capacity.

Worked out from them (summary()):

- Efficiency (mi/kWh): miles ÷ kWh over trips of at least
  `min_trip_mi`, overall and in 5 °C temperature bands.
- Real range at 100%: efficiency × the usable capacity, per band. Also
  from the SoC: miles per 1% used × 100 (trips using at least 5%).
- The car's estimate at 100%: its range ÷ SoC (readings at 30% or more),
  the median per band.

Everything is kept in km, kWh and °C; the page shows miles. Pure (no I/O
except the save file), so it can be tested on its own.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import statistics
from typing import Optional

logger = logging.getLogger(__name__)

KM_PER_MI = 1.609344
BAND_C = 5  # temperature bands this wide
MAX_TRIPS = 3000
MAX_RANGE_READINGS = 5000
MAX_HEALTH = 2000
BUFFER_S = 3 * 86400  # recent temperature and SoC readings kept for matching to trips
RANGE_MIN_SOC = 30  # the car's estimate ÷ SoC is only used at or above this SoC
SOC_TRIP_MIN_PCT = 5  # trips using at least this much SoC give a miles-per-1% figure
USABLE_MIN_SOC = 20  # Battery residual ÷ SoC only at or above this SoC
DEFAULTS = {"min_trip_mi": 2.0, "usable_kwh": 0.0}  # 0: measured / the car's capacity sensor


def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(iso: str) -> float:
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _r(v: Optional[float], n: int = 2) -> Optional[float]:
    return None if v is None else round(v, n)


# --- reading the integration's values ----------------------------------------------


def number(value) -> Optional[float]:
    """A number from a state or an attribute like "12.3 kWh" (None if there isn't one)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.match(r"\s*(-?\d+(?:[.,]\d+)?)", str(value))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def unit_of(value) -> str:
    """The unit after a number in an attribute like "12.3 kWh/100km"."""
    m = re.match(r"\s*-?\d+(?:[.,]\d+)?\s*(.*)$", str(value or ""))
    return (m.group(1) if m else "").strip()


def to_km(value: Optional[float], unit: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    u = (unit or "km").strip().lower()
    if u in ("mi", "mile", "miles"):
        return value * KM_PER_MI
    if u == "m":
        return value / 1000
    if u == "ft":
        return value * 0.0003048
    return value


def to_c(value: Optional[float], unit: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    return (value - 32) / 1.8 if "f" in (unit or "").lower() else value


def duration_s(value) -> Optional[float]:
    """"01:23:45" (the integration's trip duration) in seconds."""
    m = re.match(r"\s*(\d+):(\d{1,2}):(\d{1,2})", str(value or ""))
    if not m:
        return None
    h, mi, s = (int(x) for x in m.groups())
    return h * 3600 + mi * 60 + s


def parse_trip(state, attrs: dict, distance_unit: Optional[str] = "km") -> Optional[dict]:
    """The Last trip sensor's state (distance) and attributes as a trip, or None."""
    km = to_km(number(state), distance_unit)
    if km is None or km <= 0:
        return None
    attrs = attrs or {}
    kwh = number(attrs.get("electric_consumption"))
    per100 = number(attrs.get("electric_avg_consumption"))
    if per100 is not None and "mi" in unit_of(attrs.get("electric_avg_consumption")).lower():
        per100 = per100 / KM_PER_MI  # (kWh/100mi)
    if kwh is None and per100:
        kwh = per100 * km / 100
    start_km = number(attrs.get("start_mileage"))
    start_km = to_km(start_km, unit_of(attrs.get("start_mileage")) or distance_unit)
    speed = number(attrs.get("avg_speed"))
    if speed is not None and "mph" in unit_of(attrs.get("avg_speed")).lower():
        speed *= KM_PER_MI
    return {"km": km, "kwh": kwh, "duration_s": duration_s(attrs.get("duration")),
            "odo_start": start_km, "avg_kmh": speed}


# --- the recorder ---------------------------------------------------------------------


class EvStats:
    def __init__(self, data_dir: Optional[str] = None) -> None:
        self._path = os.path.join(data_dir, "evstats.json") if data_dir else None
        self.trips: list[dict] = []
        self.ranges: list[list] = []  # [ts, soc, range_km, temp_c]
        self.health: list[dict] = []  # {"at", "soh_capacity", "soh_resistance", "usable_kwh"}
        self.temps: list[list] = []  # [ts, °C], recent
        self.socs: list[list] = []  # [ts, %], recent
        self.usable: list[list] = []  # [ts, kWh]: Battery residual ÷ SoC
        self.backfilled = False
        self.dirty = False
        self._load()

    # --- saved -------------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path:
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            self.trips = list(data.get("trips") or [])
            self.ranges = list(data.get("ranges") or [])
            self.health = list(data.get("health") or [])
            self.temps = list(data.get("temps") or [])
            self.socs = list(data.get("socs") or [])
            self.usable = list(data.get("usable") or [])
            self.backfilled = bool(data.get("backfilled"))
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("Statistics %s are unreadable: starting afresh", self._path)

    def save(self) -> None:
        self.dirty = False
        if not self._path:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"trips": self.trips, "ranges": self.ranges, "health": self.health, "temps": self.temps,
                           "socs": self.socs, "usable": self.usable, "backfilled": self.backfilled}, f)
            os.replace(tmp, self._path)
        except Exception:
            logger.warning("Could not save the statistics", exc_info=True)

    # --- readings ------------------------------------------------------------------------

    def _prune(self, now: float) -> None:
        cutoff = now - BUFFER_S
        self.temps = [x for x in self.temps if x[0] >= cutoff]
        self.socs = [x for x in self.socs if x[0] >= cutoff]

    def temperature(self, ts: float, temp_c: Optional[float]) -> None:
        if temp_c is None or not -40 <= temp_c <= 60:
            return
        if self.temps and self.temps[-1][1] == temp_c and ts - self.temps[-1][0] < 1800:
            return
        self.temps.append([ts, round(temp_c, 1)])
        self.temps.sort(key=lambda x: x[0])
        self._prune(max(ts, self.temps[-1][0]))
        self.dirty = True

    def soc(self, ts: float, soc: Optional[float]) -> None:
        if soc is None or not 0 < soc <= 100:
            return
        if self.socs and self.socs[-1][1] == soc:
            return
        self.socs.append([ts, soc])
        self.socs.sort(key=lambda x: x[0])
        self._prune(max(ts, self.socs[-1][0]))
        self._fill_soc_end()
        self.dirty = True

    def temp_at(self, ts: float, start: Optional[float] = None) -> Optional[float]:
        """The temperature over start..ts (the mean of the readings then), else the last one
        before ts (within 6 hours)."""
        if start is not None:
            during = [t for at, t in self.temps if start <= at <= ts]
            if during:
                return round(statistics.fmean(during), 1)
        before = [x for x in self.temps if x[0] <= ts and ts - x[0] <= 6 * 3600]
        return before[-1][1] if before else None

    def soc_at(self, ts: float, after: bool = False, within_s: float = 12 * 3600) -> Optional[float]:
        if after:
            later = [x for x in self.socs if ts <= x[0] <= ts + within_s]
            return later[0][1] if later else None
        before = [x for x in self.socs if x[0] <= ts and ts - x[0] <= within_s]
        return before[-1][1] if before else None

    def range_reading(self, ts: float, soc: Optional[float], range_km: Optional[float],
                      temp_c: Optional[float]) -> None:
        """The car's own range estimate at this SoC."""
        if soc is None or range_km is None or not 0 < soc <= 100 or range_km < 0:
            return
        last = self.ranges[-1] if self.ranges else None
        if last and last[1] == soc and abs(last[2] - range_km) < 0.5:
            return
        self.ranges.append([round(ts), soc, round(range_km, 1), temp_c])
        if last and ts < last[0]:
            self.ranges.sort(key=lambda x: x[0])
        del self.ranges[:-MAX_RANGE_READINGS]
        self.dirty = True

    def residual(self, ts: float, residual_kwh: Optional[float], soc: Optional[float]) -> None:
        """Battery residual (kWh in the battery now) ÷ SoC: the usable capacity, measured."""
        if residual_kwh is None or soc is None or soc < USABLE_MIN_SOC or residual_kwh <= 0:
            return
        full = residual_kwh / soc * 100
        if not 5 <= full <= 250:
            return
        if self.usable and abs(self.usable[-1][1] - full) < 0.05 and ts - self.usable[-1][0] < 86400:
            return
        self.usable.append([round(ts), round(full, 2)])
        del self.usable[:-MAX_HEALTH]
        self.dirty = True

    def soh(self, ts: float, capacity_pct: Optional[float], resistance_pct: Optional[float]) -> None:
        if capacity_pct is None and resistance_pct is None:
            return
        last = self.health[-1] if self.health else {}
        if last.get("soh_capacity") == capacity_pct and last.get("soh_resistance") == resistance_pct:
            return
        self.health.append({"at": _iso(ts), "soh_capacity": capacity_pct, "soh_resistance": resistance_pct})
        del self.health[:-MAX_HEALTH]
        self.dirty = True

    def trip(self, ts: float, trip: Optional[dict], source: str = "live") -> Optional[dict]:
        """A new Last trip (ts: when it was seen, about when the trip ended). Returns the
        record, or None if it's not new."""
        if not trip:
            return None
        key = (_r(trip.get("odo_start"), 1), _r(trip["km"], 2), _r(trip.get("kwh"), 3), trip.get("duration_s"))
        if any(self._key(t) == key for t in self.trips[-50:]):
            return None  # the same trip again (e.g. sent again when the link reconnects)
        end = ts
        start = end - trip["duration_s"] if trip.get("duration_s") else None
        soc_start = self.soc_at(start if start is not None else end - 60)
        rec = {
            "end": _iso(end), "start": _iso(start), "km": key[1], "kwh": key[2],
            "duration_s": trip.get("duration_s"), "avg_kmh": _r(trip.get("avg_kmh"), 1),
            "odo_start": key[0], "temp_c": self.temp_at(end, start),
            "soc_start": soc_start, "soc_end": self._soc_after(end, start), "source": source,
        }
        self.trips.append(rec)
        self.trips.sort(key=lambda t: t["end"])
        del self.trips[:-MAX_TRIPS]
        self.dirty = True
        return rec

    @staticmethod
    def _key(t: dict) -> tuple:
        return (t.get("odo_start"), t.get("km"), t.get("kwh"), t.get("duration_s"))

    def _soc_after(self, end: float, start: Optional[float]) -> Optional[float]:
        """The SoC the car reported as the trip ended (it often comes with the trip, just
        before or after it): the first reading from shortly before the end to an hour after."""
        frm = max(start if start is not None else end - 300, end - 300)
        later = [x for x in self.socs if frm <= x[0] <= end + 3600]
        return later[0][1] if later else None

    def _fill_soc_end(self) -> None:
        """A SoC reading that arrived after a trip was recorded: its SoC at the end."""
        for t in self.trips[-5:]:
            if t.get("soc_end") is None:
                soc = self._soc_after(_ts(t["end"]), _ts(t["start"]) if t.get("start") else None)
                if soc is not None:
                    t["soc_end"] = soc

    def merge(self, other: "EvStats") -> dict:
        """Add what `other` recorded (e.g. from Home Assistant's history) that isn't here yet.
        Returns how many of each were added."""
        keys = {self._key(t) for t in self.trips}
        trips = [t for t in other.trips if self._key(t) not in keys]
        self.trips = sorted(self.trips + trips, key=lambda t: t["end"])[-MAX_TRIPS:]
        seen = {(r[0], r[1]) for r in self.ranges}
        ranges = [r for r in other.ranges if (r[0], r[1]) not in seen]
        self.ranges = sorted(self.ranges + ranges, key=lambda r: r[0])[-MAX_RANGE_READINGS:]
        ats = {h["at"] for h in self.health}
        health = [h for h in other.health if h["at"] not in ats]
        merged = []
        for h in sorted(self.health + health, key=lambda h: h["at"]):
            if not merged or (merged[-1]["soh_capacity"], merged[-1]["soh_resistance"]) != (
                    h["soh_capacity"], h["soh_resistance"]):
                merged.append(h)  # only changes
        self.health = merged[-MAX_HEALTH:]
        uts = {u[0] for u in self.usable}
        self.usable = sorted(self.usable + [u for u in other.usable if u[0] not in uts], key=lambda u: u[0])[-MAX_HEALTH:]
        self.dirty = True
        return {"trips": len(trips), "ranges": len(ranges), "health": len(health)}

    # --- worked out -------------------------------------------------------------------------

    def usable_kwh(self, capacity_sensor: Optional[float] = None, override: float = 0.0,
                   now: Optional[float] = None) -> tuple[Optional[float], str]:
        """The usable capacity and where it's from."""
        if override:
            return override, "set on the Settings tab"
        recent = [kwh for at, kwh in self.usable if now is None or at >= now - 90 * 86400][-30:]
        if len(recent) >= 3:
            return statistics.median(recent), "measured (Battery residual ÷ SoC)"
        if capacity_sensor:
            return capacity_sensor, "the car's Battery capacity sensor"
        if recent:
            return statistics.median(recent), "measured (Battery residual ÷ SoC)"
        return None, "not known yet"

    @staticmethod
    def band(temp_c: Optional[float]) -> Optional[int]:
        """The lower edge of the temperature band (e.g. 5 for 5 to 10 °C)."""
        if temp_c is None:
            return None
        return int((temp_c // BAND_C) * BAND_C)

    def summary(self, now: float, settings: Optional[dict] = None, capacity_sensor: Optional[float] = None,
                current: Optional[dict] = None) -> dict:
        s = {**DEFAULTS, **(settings or {})}
        current = current or {}
        min_km = float(s["min_trip_mi"]) * KM_PER_MI
        usable, usable_from = self.usable_kwh(capacity_sensor, float(s["usable_kwh"] or 0), now)
        good = [t for t in self.trips if t["km"] >= min_km and t.get("kwh") and 0.03 <= t["kwh"] / t["km"] <= 0.6]

        def eff(trips) -> dict:
            km = sum(t["km"] for t in trips)
            kwh = sum(t["kwh"] for t in trips)
            mi = km / KM_PER_MI
            return {"trips": len(trips), "mi": _r(mi, 1), "kwh": _r(kwh, 2),
                    "mi_per_kwh": _r(mi / kwh, 2) if kwh else None, "raw": mi / kwh if kwh else None}

        since30 = _iso(now - 30 * 86400)
        overall, last30 = eff(good), eff([t for t in good if t["end"] >= since30])

        bands: dict[int, dict] = {}
        for t in good:
            b = self.band(t.get("temp_c"))
            if b is not None:
                bands.setdefault(b, {"trips": []})["trips"].append(t)
        for t in self.trips:  # miles per 1% of SoC
            b = self.band(t.get("temp_c"))
            if b is None or t.get("soc_start") is None or t.get("soc_end") is None:
                continue
            used = t["soc_start"] - t["soc_end"]
            if used >= SOC_TRIP_MIN_PCT:
                row = bands.setdefault(b, {"trips": []})
                row["soc_km"] = row.get("soc_km", 0.0) + t["km"]
                row["soc_pct"] = row.get("soc_pct", 0.0) + used
        for at, soc, range_km, temp in self.ranges:  # the car's estimate at 100%
            b = self.band(temp)
            if b is None or soc < RANGE_MIN_SOC:
                continue
            bands.setdefault(b, {"trips": []}).setdefault("car_full_km", []).append(range_km / soc * 100)
        rows = []
        for b in sorted(bands):
            row = bands[b]
            e = eff(row["trips"])
            car = row.get("car_full_km") or []
            rows.append({
                "from_c": b, "to_c": b + BAND_C, **e,
                "real_full_mi": _r(e["raw"] * usable, 0) if e["raw"] and usable else None,
                "soc_full_mi": _r(row["soc_km"] / row["soc_pct"] * 100 / KM_PER_MI, 0) if row.get("soc_pct") else None,
                "car_full_mi": _r(statistics.median(car) / KM_PER_MI, 0) if car else None,
                "car_readings": len(car),
            })

        # Now: the band for the current temperature (or the nearest with trips)
        temp_now = current.get("temp_c")
        soc_now = current.get("soc")
        with_eff = [r for r in rows if r["mi_per_kwh"]]
        here = None
        if temp_now is not None and with_eff:
            here = min(with_eff, key=lambda r: (abs(r["from_c"] + BAND_C / 2 - temp_now), -r["trips"]))
        mpk_now = here["raw"] if here else last30["raw"] or overall["raw"]
        full_now = mpk_now * usable if mpk_now and usable else None
        car_range_mi = current.get("range_km") / KM_PER_MI if current.get("range_km") is not None else None
        car_full_now = (car_range_mi / soc_now * 100) if car_range_mi is not None and soc_now and soc_now >= 10 else None

        for d in [overall, last30, *rows]:
            d.pop("raw", None)
        latest_health = self.health[-1] if self.health else {}
        usable_series = self._weekly(self.usable)
        return {
            "usable_kwh": _r(usable, 1), "usable_from": usable_from,
            "efficiency": {"overall": overall, "last30": last30},
            "bands": rows, "band_c": BAND_C, "min_trip_mi": float(s["min_trip_mi"]),
            "now": {
                "temp_c": temp_now, "soc": soc_now, "band": here["from_c"] if here else None,
                "mi_per_kwh": _r(mpk_now, 2), "real_full_mi": _r(full_now, 0),
                "real_left_mi": _r(full_now * soc_now / 100, 0) if full_now and soc_now is not None else None,
                "car_range_mi": _r(car_range_mi, 0), "car_full_mi": _r(car_full_now, 0),
                "odometer_mi": _r(current["odometer_km"] / KM_PER_MI, 0) if current.get("odometer_km") is not None else None,
            },
            "health": {"soh_capacity": latest_health.get("soh_capacity"),
                       "soh_resistance": latest_health.get("soh_resistance"),
                       "history": self.health[-500:], "usable": usable_series},
            "trips": self.trips[-300:][::-1], "trip_count": len(self.trips),
            "range_readings": len(self.ranges), "since": self.trips[0]["end"] if self.trips else None,
        }

    @staticmethod
    def _weekly(series: list) -> list:
        """[ts, value] as the median of each week: {"week", "kwh", "n"}."""
        weeks: dict[str, list] = {}
        for at, v in series:
            d = datetime.datetime.fromtimestamp(at, datetime.timezone.utc).date()
            monday = (d - datetime.timedelta(days=d.weekday())).isoformat()
            weeks.setdefault(monday, []).append(v)
        return [{"week": w, "kwh": _r(statistics.median(v), 2), "n": len(v)} for w, v in sorted(weeks.items())]
