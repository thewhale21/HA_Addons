"""The add-on: starts the web page, the Home Assistant link and the worker,
and stops them cleanly when Home Assistant stops the add-on.

Put your add-on's own work in worker() (or start more tasks next to it).
"""
from __future__ import annotations

import asyncio
import datetime
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
from src.ha_link import HaLink
from src.health import Health
from src.shared_state import SharedState

logger = logging.getLogger("addon_template")

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATA_DIR = os.environ.get("ADDON_DATA", "/data")
PORT = 8099  # ingress_port in config.yaml defaults to 8099
WORKER_INTERVAL_S = 60


async def worker(state: SharedState, link: HaLink) -> None:
    """The add-on's own work: replace this. The example counts ticks, which
    the Overview tab shows and the ticks sensor publishes to Home Assistant."""
    state.status = "Running"
    while True:
        state.ticks += 1
        state.last_tick = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.debug("Tick %d", state.ticks)
        await asyncio.sleep(WORKER_INTERVAL_S)


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    log_filters.install()
    log_buffer = install_log_buffer(LOG_FORMAT)
    data_dir: Optional[str] = DATA_DIR if os.path.isdir(DATA_DIR) else None

    settings = AppSettings(data_dir)  # applies a new log level itself
    settings.apply_log_level()
    config = load_config()
    state = SharedState(example_option=config.example_option)
    health = Health()

    async def entity_changed(entity_id: str, st: Optional[dict]) -> None:
        """A watched entity changed in Home Assistant (src/ha_link.py)."""
        if entity_id == link.settings.get("example_entity"):
            state.example_entity = entity_id
            state.example_value = (st or {}).get("state")

    link = HaLink(data_dir, state, on_entity_changed=entity_changed)
    state.example_entity = link.settings.get("example_entity") or None
    debug = DebugTools(config=config, log_buffer=log_buffer, settings=settings)

    app = create_api_app(state, ha_link=link, health=health, debug=debug, app_settings=settings)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("Web page and API on port %d (version %s)", PORT, health.version)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows, when run by hand
            pass

    tasks = [asyncio.create_task(link.run()), asyncio.create_task(worker(state, link))]
    try:
        await stop.wait()
        logger.info("Stopping")
    finally:
        state.status = "Stopped"
        try:
            await asyncio.wait_for(link.shutdown(), 5)  # its sensors show unavailable while stopped
        except Exception:
            logger.debug("Couldn't mark the sensors unavailable", exc_info=True)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await runner.cleanup()
        logger.info("Stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
