"""The add-on: starts the web page, the Home Assistant link and the
statistics (src/runner.py, src/evstats.py), and stops them cleanly when
Home Assistant stops the add-on (saving the statistics).
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Optional

from aiohttp import web

from src import log_filters
from src.api import create_api_app
from src.app_settings import AppSettings
from src.config import load_config
from src.debug_tools import DebugTools, install_log_buffer
from src.evstats import EvStats
from src.ha_link import HaLink
from src.health import Health
from src.runner import Runner
from src.shared_state import SharedState

logger = logging.getLogger("stellantis_ev_stats")

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATA_DIR = os.environ.get("ADDON_DATA", "/data")
PORT = 8099  # ingress_port in config.yaml defaults to 8099
REFRESH_S = 60


async def worker(runner: Runner, link: HaLink) -> None:
    """Finds the Stellantis Vehicles sensors, reads the history once, then keeps the
    headline figures (and the add-on's sensors) up to date and the statistics saved."""
    ready = False
    while True:
        try:
            if link.connected and not ready:
                await link.autodetect()
                ready = True
            elif not link.connected:
                ready = False  # look again (e.g. a car added) when it's back
            if ready and not runner.stats.backfilled:
                try:
                    await runner.backfill()
                except Exception as err:
                    logger.warning("Couldn't read Home Assistant's history (trying again in a minute): %s", err)
            if ready:
                await runner.refresh_forecast()
            runner.refresh()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Updating the statistics failed", exc_info=True)
        await asyncio.sleep(REFRESH_S if ready else 5)


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
    stats = EvStats(data_dir)

    link = HaLink(data_dir, state)
    runner = Runner(link, stats, settings, state)
    link.on_entity_changed = runner.entity_changed
    def settings_changed(changes: dict) -> None:
        if any(k.startswith("commute") for k in changes):
            runner._forecast_at = 0.0  # look again for the new time
        runner.refresh()
    settings.on_change = settings_changed
    debug = DebugTools(config=config, log_buffer=log_buffer, settings=settings)

    app = create_api_app(state, ha_link=link, health=health, debug=debug, app_settings=settings, runner=runner)
    web_runner = web.AppRunner(app)  # (not `runner`: that's the statistics' Runner, used below)
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

    tasks = [asyncio.create_task(link.run()), asyncio.create_task(worker(runner, link))]
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
