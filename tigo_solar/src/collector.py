"""Reads Tigo: the latest readings every few minutes (poll), and the history from the day
the system started (backfill), into the store (src/store.py) and the shared state.

Each poll, for today (in the system's time zone):
- each panel's energy so far (aggenergy), and the day's total and reclaimed energy;
- the system's power by the minute, total, base and reclaimed (aggregate, minute);
- the days of this month and the months of this year (aggregate, day and month);
- each panel's power and reclaimed power at the latest reading (lastvalue), when there's a
  new one (Tigo only keeps the latest, so the add-on builds that history itself);
- now and then: the lifetime total, the plan (free or premium) and the system's layout.

The history, a day at a time, newest first, between polls: each panel's energy that day
and the system's power by the minute, and each month's days; a day is read once, and
yesterday once more after midnight (Tigo can still be catching up then).
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import time
from typing import Callable, Optional

from src import tigo_data

logger = logging.getLogger(__name__)

POLL_S = 300  # free plan: Tigo's data changes about every 15 minutes
POLL_PREMIUM_S = 60
CONFIG_EVERY_S = 6 * 3600
LIFETIME_EVERY_S = 1800
BACKFILL_GAP_S = 3.0  # between history requests: gentle on Tigo
BACKFILL_YEARS = 5  # looked back this far for the first month with production
ERROR_BACKOFF_S = (60, 120, 300, 600)


def _zone(name: Optional[str]):
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None


def _days(start: str, end: str) -> list[str]:
    """Every day from start to end, both included, "YYYY-MM-DD"."""
    a, b = datetime.date.fromisoformat(start), datetime.date.fromisoformat(end)
    return [(a + datetime.timedelta(days=n)).isoformat() for n in range((b - a).days + 1)]


def _month_end(month: str) -> str:
    """The last day of a month ("YYYY-MM")."""
    first = datetime.date.fromisoformat(month + "-01")
    return ((first + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)).isoformat()


class Collector:
    def __init__(self, client, store, state, layout=None,
                 now: Callable[[], datetime.datetime] = lambda: datetime.datetime.now(datetime.timezone.utc),
                 sleep=asyncio.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        self.client = client
        self.store = store
        self.state = state
        self.layout = layout
        self._now = now
        self._sleep = sleep
        self._clock = clock
        self.system: dict = {"panels": [], "strings": [], "inverters": []}
        self._config_at: Optional[float] = None
        self._lifetime_at: Optional[float] = None
        self._info_day: Optional[str] = None
        self._last_reading: Optional[str] = None
        self._day: Optional[str] = None  # the day the last poll was for
        self._live: dict = {}  # panel ID -> {"power", "reclaimed", "energy_today"}
        self._start: Optional[str] = None  # the first day with production
        self.wake = asyncio.Event()  # (set to poll now, e.g. the page asked)

    # --- time ------------------------------------------------------------------------

    def local_now(self) -> datetime.datetime:
        now = self._now()
        zone = _zone(self.state.timezone)
        return now.astimezone(zone) if zone else now.astimezone()

    def today(self) -> str:
        return self.local_now().date().isoformat()

    # --- the system ------------------------------------------------------------------

    async def refresh_config(self) -> None:
        self.system = tigo_data.parse_config(await self.client.config())
        self._config_at = self._clock()
        self.state.strings = self.system["strings"]
        self.state.inverters = self.system["inverters"]
        self.publish_panels()
        logger.info("Tigo system: %d panels in %d strings", len(self.system["panels"]), len(self.system["strings"]))

    def publish_panels(self) -> None:
        """The panels with their place on the roof and their latest readings, for the page and sensors."""
        panels = self.layout.apply(self.system["panels"]) if self.layout else [dict(p) for p in self.system["panels"]]
        for p in panels:
            p.update(self._live.get(p["id"]) or {"power": None, "reclaimed": None, "energy_today": None})
        self.state.panels = panels
        self.state.layout_moved = bool(self.layout and self.layout.moved)

    async def refresh_info(self, day: str) -> None:
        info = tigo_data.parse_systeminfo(await self.client.systeminfo(day), day)
        if info["premium"] is not None:
            self.state.premium = info["premium"]
        self.state.timezone = info["timezone"] or self.state.timezone
        self.state.sunrise, self.state.sunset = info["sunrise"], info["sunset"]
        self._info_day = day

    # --- now -------------------------------------------------------------------------

    async def poll(self) -> None:
        """Read today's data (and finish yesterday's when the day has changed)."""
        if self._config_at is None or self._clock() - self._config_at >= CONFIG_EVERY_S:
            await self.refresh_config()
        day = self.today()
        if self._info_day != day:
            await self.refresh_info(day)
            day = self.today()  # (the time zone may have just become known)
        if self._day is not None and self._day != day:
            # A new day: yesterday's last readings, and it's done
            await self.read_day(self._day)
            self._live = {p: {**v, "energy_today": None} for p, v in self._live.items()}
        self._day = day

        energy = tigo_data.parse_aggenergy(await self.client.aggenergy(day))
        self.store.put_panel_energy(day, energy["panels"])
        for pid, wh in energy["panels"].items():
            self._live.setdefault(pid, {})["energy_today"] = wh

        rows = tigo_data.echart_rows(await self.client.aggregate("minute", day, day, line=True))
        self.store.put_system_power(rows)
        if rows:
            t, total, base, reclaimed = rows[-1]
            self.state.power, self.state.reclaimed, self.state.as_of = total, reclaimed, t
        else:
            self.state.power, self.state.reclaimed = 0.0, 0.0

        month_start = day[:8] + "01"
        days = tigo_data.echart_rows(await self.client.aggregate("day", month_start, day))
        self.store.put_system_energy((t[:10], tot, base, rec) for t, tot, base, rec in days)
        today_row = next((r for r in days if r[0][:10] == day), None)
        self.state.today_wh = energy["total"] if energy["total"] is not None else (today_row[1] if today_row else None)
        self.state.today_reclaimed_wh = energy["reclaimed"] if energy["reclaimed"] is not None else (
            today_row[3] if today_row else None)
        self.state.month_wh = sum(r[1] or 0 for r in days)
        months = tigo_data.echart_rows(await self.client.aggregate("month", day[:5] + "01-01", day))
        self.state.year_wh = sum(r[1] or 0 for r in months) if months else self.state.month_wh

        last = energy["last"]
        if last and last != self._last_reading and last[:10] == day:
            await self._read_panels(day, last)
        if self._lifetime_at is None or self._clock() - self._lifetime_at >= LIFETIME_EVERY_S:
            try:
                self.state.lifetime_wh = tigo_data._num((await self.client.lifetime() or {}).get("energy"))
                self._lifetime_at = self._clock()
            except Exception as err:
                logger.debug("The lifetime total didn't come: %s", err)
        self.publish_panels()
        self.state.last_poll = self._now().strftime("%Y-%m-%dT%H:%M:%SZ")

    async def _read_panels(self, day: str, last: str) -> None:
        """Each panel's power and reclaimed power at the latest reading."""
        hhmm = last[11:16]
        values = {}
        for kind in ("pin", "reclaimedPower"):
            try:
                values[kind] = tigo_data.parse_lastvalue(await self.client.lastvalue(day, kind, hhmm))
            except Exception as err:
                logger.debug("Tigo didn't send each panel's %s: %s", kind, err)
                values[kind] = {}
        power, reclaimed = values["pin"], values["reclaimedPower"]
        if power or reclaimed:
            self.store.put_panel_power(last, power, reclaimed)
            for pid in set(power) | set(reclaimed):
                live = self._live.setdefault(pid, {})
                live["power"], live["reclaimed"] = power.get(pid), reclaimed.get(pid)
        self._last_reading = last

    # --- history ---------------------------------------------------------------------

    async def read_day(self, day: str) -> None:
        """A whole day: each panel's energy and the system's power by the minute; done."""
        energy = tigo_data.parse_aggenergy(await self.client.aggenergy(day))
        self.store.put_panel_energy(day, energy["panels"])
        await self._sleep(BACKFILL_GAP_S)
        rows = tigo_data.echart_rows(await self.client.aggregate("minute", day, day, line=True))
        self.store.put_system_power(rows)
        if energy["total"] is not None:
            self.store.put_system_energy([(day, energy["total"],
                                           None if energy["reclaimed"] is None else energy["total"] - energy["reclaimed"],
                                           energy["reclaimed"])])
        self.store.mark_done(day, "day")

    async def find_start(self) -> Optional[str]:
        if self._start:
            return self._start
        day = self.today()
        start = (datetime.date.fromisoformat(day) - datetime.timedelta(days=365 * BACKFILL_YEARS)).replace(day=1)
        first = tigo_data.first_month(await self.client.aggregate("month", start.isoformat(), day))
        if first:
            # (its days: the first one with production)
            rows = tigo_data.echart_rows(await self.client.aggregate("day", first, min(_month_end(first[:7]), day)))
            self.store.put_system_energy((t[:10], tot, b, r) for t, tot, b, r in rows)
            self._start = next((t[:10] for t, tot, _, _ in rows if tot), first)
        return self._start

    async def backfill_step(self) -> bool:
        """Read one more piece of history. False when there's nothing left."""
        start = await self.find_start()
        today = self.today()
        if not start:
            self.state.history = {"from": None, "done": 0, "days": 0, "running": False}
            return False
        yesterday = (datetime.date.fromisoformat(today) - datetime.timedelta(days=1)).isoformat()
        days = _days(start, yesterday) if start <= yesterday else []
        # Each earlier month's days (one request a month; this month's come with each poll)
        months = sorted({d[:7] for d in days if d[:7] < today[:7]})
        for month in reversed(months):
            if not self.store.is_done(month, "month"):
                rows = tigo_data.echart_rows(await self.client.aggregate("day", month + "-01", _month_end(month)))
                self.store.put_system_energy((t[:10], tot, b, r) for t, tot, b, r in rows)
                self.store.mark_done(month, "month")
                self._history(start, days)
                return True
        for day in reversed(days):
            if not self.store.is_done(day, "day"):
                await self.read_day(day)
                self._history(start, days)
                return True
        self._history(start, days, running=False)
        return False

    def _history(self, start: str, days: list, running: bool = True) -> None:
        done = sum(1 for d in days if self.store.is_done(d, "day"))
        self.state.history = {"from": start, "done": done, "days": len(days), "running": running and done < len(days),
                              "panel_power_from": self.store.panel_power_since()}

    # --- the loop --------------------------------------------------------------------

    async def run(self) -> None:
        failures = 0
        next_poll = 0.0
        history_left = True
        while True:
            try:
                if self._clock() >= next_poll:
                    await self.poll()
                    self.state.status = "Running"
                    self.state.error = None
                    failures = 0
                    next_poll = self._clock() + (POLL_PREMIUM_S if self.state.premium else POLL_S)
                    history_left = True  # (a new day may have one more)
                if history_left:
                    history_left = await self.backfill_step()
                    await self._sleep(BACKFILL_GAP_S)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as err:
                failures += 1
                self.state.error = str(err) or type(err).__name__
                self.state.status = "Can't reach Tigo" if failures > 1 else self.state.status
                wait = ERROR_BACKOFF_S[min(failures - 1, len(ERROR_BACKOFF_S) - 1)]
                logger.warning("Reading Tigo failed (%s): trying again in %d s", self.state.error, wait)
                if type(err).__name__ == "TigoAuthError":
                    self.state.status = "Tigo refused the login"
                next_poll = self._clock() + wait
                history_left = False
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), max(1.0, next_poll - self._clock()))
                next_poll = 0.0
            except asyncio.TimeoutError:
                pass
