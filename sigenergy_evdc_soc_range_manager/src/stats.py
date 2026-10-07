"""Battery statistics for the car: its usable capacity over time (to
guess at degradation) and what charging and discharging it through the
inverter loses in conversion.

Sessions: each time the charger runs in one direction (charging or
discharging) is a session. Its energy comes from the charger's total
charged / discharged counters.

Capacity: kWh in (or out) divided by the SoC it moved, x 100. The SoC is a
whole number, so it's measured between the moments the SoC ticks over (not
from the session's ends), and only over at least `capacity_min_span_pct`.
It's the energy at the charger, so it includes the car's own charging
losses: read the trend more than the number.

Losses: the inverter's DC side (solar in, home battery in or out, car in
or out) against its AC side, every few seconds. Whatever goes in and
doesn't come out is lost. The car is given its share of that loss by its
share of the DC flow at the time. A "clean" session (little solar or home
battery during it) gives a straight efficiency: AC in -> car, or car -> AC
out.

All pure, no I/O except saving to /data/stats.json; src/__main__.py feeds
it a Sample after each look at the charger, and replays Home Assistant's
history into it once, so there's something to see straight away.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import statistics
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

STATS_DEFAULTS = {
    "capacity_min_span_pct": 10.0,  # SoC a session must move to estimate the capacity from it
    "clean_share_pct": 10.0,  # solar + home battery under this % of the car's energy = a clean session
    "flip_inverter_power": False,  # the inverter's power reads negative when it feeds the house
}
MAX_SESSIONS = 1000
MAX_DAYS = 400
MAX_GAP_S = 120  # readings further apart than this aren't integrated across
SAVE_EVERY_S = 300
DAY_FIELDS = ("pv_kwh", "batt_in_kwh", "batt_out_kwh", "ac_in_kwh", "ac_out_kwh", "loss_kwh", "car_loss_kwh",
              "car_in_kwh", "car_out_kwh", "measured_h")


@dataclass
class Sample:
    now: float  # epoch seconds
    direction: Optional[str]  # "charge", "discharge", "other" (running, e.g. preparing) or None (stopped)
    soc: Optional[float] = None  # the car's SoC as the charger reports it (None/0 when it doesn't)
    e_in: Optional[float] = None  # the charger's total charged energy, kWh
    e_out: Optional[float] = None  # ...and total discharged
    car_kw: Optional[float] = None  # the charger's power (either sign: the direction says which way)
    pv_kw: Optional[float] = None  # solar
    batt_kw: Optional[float] = None  # home battery: positive charging
    ac_kw: Optional[float] = None  # inverter: positive = DC -> AC (feeding the house / grid)


def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _r(v: Optional[float], n: int = 3) -> Optional[float]:
    return None if v is None else round(v, n)


class StatsRecorder:
    def __init__(self, data_dir: Optional[str] = None) -> None:
        self._path = os.path.join(data_dir, "stats.json") if data_dir else None
        self.sessions: list[dict] = []
        self.days: dict[str, dict] = {}
        self.current: Optional[dict] = None
        self.last: Optional[Sample] = None
        self.started: Optional[float] = None  # first live sample (history is only used before this)
        self.backfilled = False
        self._saved_at = 0.0
        self._load()

    # --- saved between restarts -----------------------------------------------------

    def _load(self) -> None:
        if not self._path:
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            self.sessions = list(data.get("sessions") or [])
            self.days = dict(data.get("days") or {})
            self.started = data.get("started")
            self.backfilled = bool(data.get("backfilled"))
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("Statistics %s are unreadable: starting afresh", self._path)

    def save(self, now: Optional[float] = None) -> None:
        self._saved_at = now or self._saved_at
        if not self._path:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"sessions": self.sessions[-MAX_SESSIONS:], "days": self.days, "started": self.started,
                           "backfilled": self.backfilled}, f)
            os.replace(tmp, self._path)
        except Exception:
            logger.warning("Could not save the statistics", exc_info=True)

    # --- recording ----------------------------------------------------------------------

    def _dayrow(self, ts: float) -> dict:
        key = _day(ts)
        row = self.days.get(key)
        if row is None:
            row = self.days[key] = {k: 0.0 for k in DAY_FIELDS}
            if len(self.days) > MAX_DAYS:
                for old in sorted(self.days)[:-MAX_DAYS]:
                    del self.days[old]
        return row

    def feed(self, s: Sample, settings: Optional[dict] = None, live: bool = True) -> None:
        t = {**STATS_DEFAULTS, **(settings or {})}
        if live and self.started is None:
            self.started = s.now
        last = self.last
        if last is not None and s.now > last.now:
            self._counters(last, s)
            if s.now - last.now <= MAX_GAP_S:
                self._integrate(last, s.now - last.now, bool(t["flip_inverter_power"]))
        self._sessions(s, t)
        self.last = s
        if live and s.now - self._saved_at >= SAVE_EVERY_S:
            self.save(s.now)

    def _counters(self, a: Sample, b: Sample) -> None:
        """The car's energy each day, from the charger's counters."""
        for field, x, y in (("car_in_kwh", a.e_in, b.e_in), ("car_out_kwh", a.e_out, b.e_out)):
            if x is not None and y is not None and 0 < y - x < 100:  # a reset or a glitch isn't energy
                self._dayrow(b.now)[field] += y - x

    def _integrate(self, a: Sample, dt: float, flip: bool) -> None:
        """Loss over dt seconds from reading `a`: what went into the inverter's DC side
        and didn't come out of its AC side (or the other way)."""
        if a.pv_kw is None or a.batt_kw is None or a.ac_kw is None:
            return
        car = abs(a.car_kw or 0.0) if a.direction in ("charge", "discharge") else 0.0
        if a.direction in ("charge", "discharge") and a.car_kw is None:
            return
        pv, batt, ac = max(a.pv_kw, 0.0), a.batt_kw, (-a.ac_kw if flip else a.ac_kw)
        dc_net = pv - batt + (car if a.direction == "discharge" else -car)  # what the DC side hands the inverter
        loss_kw = dc_net - ac
        flow = pv + abs(batt) + car
        share = car / flow if flow > 0 else 0.0
        h = dt / 3600
        row = self._dayrow(a.now)
        row["pv_kwh"] += pv * h
        row["batt_in_kwh"] += max(batt, 0.0) * h
        row["batt_out_kwh"] += max(-batt, 0.0) * h
        row["ac_out_kwh"] += max(ac, 0.0) * h
        row["ac_in_kwh"] += max(-ac, 0.0) * h
        row["loss_kwh"] += loss_kw * h
        row["car_loss_kwh"] += loss_kw * share * h
        row["measured_h"] += h
        cur = self.current
        if cur is not None and car:
            cur["car_loss_kwh"] += loss_kw * share * h
            cur["loss_kwh"] += loss_kw * h
            cur["other_dc_kwh"] += (pv + abs(batt)) * h
            cur["ac_kwh"] += abs(ac) * h
            cur["car_kwh_power"] += car * h
            cur["measured_s"] += dt

    def _sessions(self, s: Sample, t: dict) -> None:
        d = s.direction
        if d is None or (d in ("charge", "discharge") and self.current and self.current["direction"] != d):
            if self.current:
                self._end(s, t)
        if d in ("charge", "discharge") and self.current is None:
            self.current = {
                "start": s.now, "direction": d, "e_start": None, "e_last": None,
                "soc_first": None, "soc_anchor": None, "e_anchor": None, "soc_end": None, "e_end": None,
                "soc_start": None, "soc_last": None,
                "car_loss_kwh": 0.0, "loss_kwh": 0.0, "other_dc_kwh": 0.0, "ac_kwh": 0.0, "car_kwh_power": 0.0,
                "measured_s": 0.0, "last": s.now,
            }
        cur = self.current
        if cur is None:
            return
        cur["last"] = s.now
        e = s.e_in if cur["direction"] == "charge" else s.e_out
        if e is not None:
            if cur["e_start"] is None:
                cur["e_start"] = e
            cur["e_last"] = e
        soc = s.soc if s.soc is not None and 0 < s.soc <= 100 else None
        if soc is None:
            return
        if cur["soc_start"] is None:
            cur["soc_start"] = soc
        cur["soc_last"] = soc
        if e is None:
            return
        # Measure between the SoC's tick-overs: whole steps, so no rounding at the ends
        if cur["soc_first"] is None:
            cur["soc_first"] = soc
        elif cur["soc_anchor"] is None:
            if soc != cur["soc_first"]:
                cur["soc_anchor"], cur["e_anchor"] = soc, e
        elif soc != (cur["soc_end"] if cur["soc_end"] is not None else cur["soc_anchor"]):
            cur["soc_end"], cur["e_end"] = soc, e

    def _end(self, s: Sample, t: dict) -> None:
        cur, self.current = self.current, None
        energy = None
        if cur["e_start"] is not None and cur["e_last"] is not None and cur["e_last"] >= cur["e_start"]:
            energy = cur["e_last"] - cur["e_start"]
        elif cur["car_kwh_power"]:
            energy = cur["car_kwh_power"]
        duration = cur["last"] - cur["start"]
        if (energy or 0) < 0.05 and duration < 120:
            return  # a blip
        capacity = span = None
        if cur["soc_anchor"] is not None and cur["soc_end"] is not None:
            span = abs(cur["soc_end"] - cur["soc_anchor"])
            moved = cur["e_end"] - cur["e_anchor"]
            if span >= float(t["capacity_min_span_pct"]) and moved > 0:
                capacity = moved / span * 100
        efficiency = None
        clean = (energy and cur["measured_s"] >= 0.8 * max(duration, 1)
                 and cur["other_dc_kwh"] <= float(t["clean_share_pct"]) / 100 * energy and cur["ac_kwh"] > 0)
        if clean:
            loss = cur["car_loss_kwh"]  # with little else going on, nearly all of it is the car's
            efficiency = energy / (energy + loss) if cur["direction"] == "charge" else (energy - loss) / energy
            if not 0.5 <= efficiency <= 1.0:
                efficiency = None  # something's off with the readings
        self.sessions.append({
            "start": _iso(cur["start"]), "end": _iso(cur["last"]), "direction": cur["direction"],
            "minutes": round(duration / 60, 1), "energy_kwh": _r(energy), "soc_start": cur["soc_start"],
            "soc_end": cur["soc_last"], "capacity_kwh": _r(capacity, 2), "capacity_span": span,
            "car_loss_kwh": _r(cur["car_loss_kwh"]) if cur["measured_s"] else None,
            "efficiency": _r(efficiency, 4), "clean": bool(clean), "source": "live",
        })
        if len(self.sessions) > MAX_SESSIONS:
            del self.sessions[:-MAX_SESSIONS]

    # --- history -------------------------------------------------------------------------

    def backfill(self, samples: list[Sample], settings: Optional[dict] = None) -> int:
        """Replay older readings (Home Assistant's history) from before live recording
        began: sessions and daily car energy only (no power history, so no losses).
        Returns how many sessions it found."""
        cutoff = self.started if self.started is not None else float("inf")
        old = StatsRecorder()
        for sample in sorted(samples, key=lambda x: x.now):
            if sample.now >= cutoff:
                break
            old.feed(sample, settings, live=False)
        if old.current is not None and old.last is not None:
            old._end(old.last, {**STATS_DEFAULTS, **(settings or {})})
        for sess in old.sessions:
            sess["source"] = "history"
        known = {x["start"] for x in self.sessions}
        found = [x for x in old.sessions if x["start"] not in known]
        self.sessions = sorted(self.sessions + found, key=lambda x: x["start"])[-MAX_SESSIONS:]
        for key, row in old.days.items():
            if key not in self.days:
                self.days[key] = row
            else:  # the day live recording began: add the energy from before it
                for field in ("car_in_kwh", "car_out_kwh"):
                    self.days[key][field] += row[field]
        self.backfilled = True
        self.save()
        return len(found)

    # --- for the page and the sensors ---------------------------------------------------------

    def summary(self, nominal_kwh: Optional[float] = None, now: Optional[float] = None) -> dict:
        import time

        now = time.time() if now is None else now
        ests = [{"at": x["end"], "kwh": x["capacity_kwh"], "direction": x["direction"], "span": x["capacity_span"]}
                for x in self.sessions if x.get("capacity_kwh")]
        recent = [e["kwh"] for e in ests[-10:]]
        capacity = statistics.median(recent) if recent else None
        trend = None
        if len(ests) >= 6:
            xs = [datetime.datetime.fromisoformat(e["at"].replace("Z", "+00:00")).timestamp() / 86400 for e in ests]
            if xs[-1] - xs[0] >= 60:  # two months at least
                mx, my = statistics.fmean(xs), statistics.fmean(e["kwh"] for e in ests)
                sxx = sum((x - mx) ** 2 for x in xs)
                slope = sum((x - mx) * (e["kwh"] - my) for x, e in zip(xs, ests)) / sxx if sxx else 0.0
                trend = {"kwh_per_year": round(slope * 365, 2), "days": round(xs[-1] - xs[0]),
                         "pct_per_year": round(slope * 365 / nominal_kwh * 100, 2) if nominal_kwh else None}

        def eff(direction):
            vals = [x["efficiency"] for x in self.sessions if x["direction"] == direction and x.get("efficiency")]
            return {"median": _r(statistics.median(vals), 4) if vals else None, "sessions": len(vals)}

        keys = sorted(self.days)
        since = _day(now - 29 * 86400)
        last30 = [k for k in keys if k >= since]
        totals = {f: round(sum(self.days[k][f] for k in last30), 2) for f in DAY_FIELDS}
        today = self.days.get(_day(now), {})
        return {
            "capacity_kwh": _r(capacity, 2), "nominal_kwh": nominal_kwh,
            "health_pct": round(capacity / nominal_kwh * 100, 1) if capacity and nominal_kwh else None,
            "estimates": ests[-200:], "trend": trend,
            "charge_efficiency": eff("charge"), "discharge_efficiency": eff("discharge"),
            "last30": totals, "today_car_loss_kwh": round(today.get("car_loss_kwh", 0.0), 3),
            "days": [{"day": k, **{f: round(self.days[k][f], 3) for f in DAY_FIELDS}} for k in last30],
            "sessions": self.sessions[-25:][::-1], "session_count": len(self.sessions),
            "since": keys[0] if keys else None, "recording_since": _iso(self.started),
            "in_session": None if self.current is None else {
                "direction": self.current["direction"], "start": _iso(self.current["start"]),
                "soc_start": self.current["soc_start"], "soc_now": self.current["soc_last"]},
        }
