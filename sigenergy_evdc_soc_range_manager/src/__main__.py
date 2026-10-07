"""The add-on: starts the web page, the Home Assistant link and the manager
loop, and stops them cleanly when Home Assistant stops the add-on.

The manager looks at the charger whenever a followed entity changes, and
every few seconds anyway (the restart wait and "exporting for 10 s" need
time to pass, not just changes).
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import signal
import time
from typing import Optional

from aiohttp import web

from src import log_filters
from src.api import create_api_app
from src.app_settings import AppSettings
from src.config import load_config
from src.debug_tools import DebugTools, install_log_buffer
from src.ha_link import HaLink
from src.health import Health
from src.helpers import ensure_helpers
from src.manager import Manager, samples_from_history
from src.schedule import Schedule
from src.stats import StatsRecorder
from src.shared_state import SharedState

logger = logging.getLogger("sigenergy_evdc_soc_range_manager")

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATA_DIR = os.environ.get("ADDON_DATA", "/data")
PORT = 8099  # ingress_port in config.yaml defaults to 8099
CHECK_INTERVAL_S = 5  # look at least this often
STATS_BRIEF_S = 60  # the statistics sensors are worked out this often
HISTORY_DAYS = 30  # how far back the statistics look in Home Assistant's history, once
SETTLE_S = 1  # after a change, wait this long for related changes before looking


class Runner:
    """Ties the manager to Home Assistant: looks, decides, presses, publishes."""

    def __init__(self, link: HaLink, manager: Manager, settings: AppSettings, state: SharedState,
                 stats: StatsRecorder) -> None:
        self.link, self.manager, self.settings, self.state, self.stats = link, manager, settings, state, stats
        self._brief_at = 0.0
        self.wake = asyncio.Event()
        self.lock = asyncio.Lock()
        manager.press = self.press
        manager.notify = self.notify

    async def press(self, entity_id: str) -> None:
        domain = entity_id.split(".", 1)[0]
        await self.link.call_service(domain, "press", target={"entity_id": entity_id})

    async def notify(self, title: str, message: str) -> None:
        service = self.settings.data.get("notify_service") or ""
        if service:
            stamp = datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
            await self.link.call_service("notify", service.split(".", 1)[1],
                                         data={"title": title, "message": f"{stamp} - {message}"})

    def publish(self) -> None:
        self.state.apply(self.manager.snapshot(), bool(self.settings.data.get("observe_only")))
        self.state.updated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    async def check(self) -> None:
        async with self.lock:
            if self.link.available and not self.link.connected:
                self.state.status, self.state.reason = "Waiting for Home Assistant", self.link.error or ""
                return
            entities = dict(self.link.settings)
            if self.link.available and entities.get("running_state") not in self.link.states:
                self.state.status = "Waiting for the charger"
                self.state.reason = ("No reading from the charger's running state yet." if entities.get("running_state")
                                     else "Pick the charger's running state sensor on the Settings tab.")
                return
            if not self.link.available:  # outside HA: nothing to read or press
                self.manager.press = None
            now = time.time()
            decision = await self.manager.step(self.link.states, entities, self.settings.data, now)
            while self.manager.dropouts:
                await self.dropout(self.manager.dropouts.pop(0))
            sample = self.manager.stats_sample(self.link.states, entities, now)
            if sample is not None:
                self.stats.feed(sample, self.settings.data)
            if now - self._brief_at >= STATS_BRIEF_S:
                self._brief_at = now
                self.state.stats = self.stats_brief()
            today = self.stats.days.get(datetime.datetime.fromtimestamp(now).strftime("%Y-%m-%d")) or {}
            self.state.stats = {**self.state.stats, "today_in_kwh": round(today.get("car_in_kwh", 0.0), 2),
                                "today_out_kwh": round(today.get("car_out_kwh", 0.0), 2),
                                "dropouts_today": int(today.get("dropouts", 0))}
            if decision.rule != getattr(self, "_last_rule", None):
                logger.debug("%s: %s", decision.status, decision.reason)
                self._last_rule = decision.rule
            self.publish()

    def stats_summary(self) -> dict:
        return self.stats.summary(self.manager.readings.get("capacity_kwh") or None, settings=self.settings.data)

    async def dropout(self, ts: float) -> None:
        """The car stopped discharging by itself: count it, and say so if it's happening a lot."""
        self.stats.record_dropout(ts)
        today = int(self.stats.days.get(datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d"), {}).get("dropouts", 0))
        alert = int(self.settings.data.get("dropout_alert") or 0)
        if alert and today >= alert:
            try:
                await self.notify("V2X: car keeps stopping discharging",
                                  f"The car has stopped discharging by itself {today} times today.")
            except Exception as err:
                logger.warning("Couldn't send the notification: %s", err)

    def stats_brief(self) -> dict:
        """What the statistics sensors show."""
        s = self.stats_summary()
        return {"capacity_kwh": s["capacity_kwh"], "health_pct": s["health_pct"],
                "round_trip": s["round_trip"], "dropouts_today": s["dropouts_today"],
                "charge_efficiency": s["charge_efficiency"]["median"],
                "discharge_efficiency": s["discharge_efficiency"]["median"],
                "today_car_loss_kwh": s["today_car_loss_kwh"]}

    async def backfill(self) -> None:
        """Once: the car's sessions from Home Assistant's history, before recording began."""
        if self.stats.backfilled:
            return
        from src.manager import HISTORY_KEYS

        entities = dict(self.link.settings)
        ids = [entities[k] for k in HISTORY_KEYS if entities.get(k)]
        if not entities.get("running_state") or not ids:
            return
        start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=HISTORY_DAYS)
        history = await self.link.query({
            "type": "history/history_during_period", "start_time": start.isoformat(), "entity_ids": ids,
            "minimal_response": True, "no_attributes": True, "significant_changes_only": False,
        }, timeout=120)
        units = {k: ((self.link.states.get(entities.get(k) or "") or {}).get("attributes") or {}).get(
            "unit_of_measurement") for k in HISTORY_KEYS}
        samples = samples_from_history(history or {}, entities, self.settings.data, units)
        async with self.lock:
            found = self.stats.backfill(samples, self.settings.data)
            self._brief_at = 0.0
        logger.info("Statistics: %d session%s found in the last %d days of history",
                    found, "" if found == 1 else "s", HISTORY_DAYS)

    async def manual(self, action: str) -> dict:
        """Start or Stop pressed on the web page."""
        async with self.lock:
            entry = await self.manager.act(action, "manual", "",
                                           dict(self.link.settings), self.settings.data)
            self.publish()
            return entry

    async def run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self.wake.wait(), CHECK_INTERVAL_S)
                await asyncio.sleep(SETTLE_S)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()
            try:
                await self.check()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Checking the charger failed", exc_info=True)


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    log_filters.install()
    log_buffer = install_log_buffer(LOG_FORMAT)
    data_dir: Optional[str] = DATA_DIR if os.path.isdir(DATA_DIR) else None

    settings = AppSettings(data_dir)  # applies a new log level itself
    settings.apply_log_level()
    config = load_config()
    state = SharedState()
    health = Health()
    manager = Manager(data_dir)
    schedule = Schedule(data_dir)
    manager.schedule = schedule
    runner: Optional[Runner] = None

    async def entity_changed(entity_id: str, st: Optional[dict]) -> None:
        if runner is not None:
            runner.wake.set()

    async def connected() -> None:
        """Make any helpers that aren't set yet (the limits, capacity, V2X mode)."""
        try:
            await ensure_helpers(link)
            state.setup_note = None
        except Exception as err:
            state.setup_note = (f"Couldn't make the helpers ({err}). Make them in Home Assistant "
                                "(Settings › Devices & services › Helpers) and pick them on the Settings tab.")
            logger.warning(state.setup_note)
        runner.wake.set()
        try:
            await runner.backfill()
        except Exception as err:
            logger.warning("Couldn't read Home Assistant's history for the statistics: %s", err)

    link = HaLink(data_dir, state, on_entity_changed=entity_changed, on_connected=connected)
    stats = StatsRecorder(data_dir)
    runner = Runner(link, manager, settings, state, stats)
    settings.on_change = lambda changes: runner.wake.set()
    debug = DebugTools(config=config, log_buffer=log_buffer, settings=settings)

    app = create_api_app(state, ha_link=link, health=health, debug=debug, app_settings=settings, runner=runner,
                         schedule=schedule)
    web_runner = web.AppRunner(app)
    await web_runner.setup()
    await web.TCPSite(web_runner, "0.0.0.0", PORT).start()
    logger.info("Web page and API on port %d (version %s)", PORT, health.version)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows, when run by hand
            pass

    tasks = [asyncio.create_task(link.run()), asyncio.create_task(runner.run())]
    try:
        await stop.wait()
        logger.info("Stopping")
    finally:
        state.status = "Stopped"
        stats.save()
        try:
            await asyncio.wait_for(link.shutdown(), 5)  # its sensors show unavailable while stopped
        except Exception:
            logger.debug("Couldn't mark the sensors unavailable", exc_info=True)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await web_runner.cleanup()
        logger.info("Stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
