"""The add-on: starts the web page, the Home Assistant link and the worker
that reads Octopus's planned dispatches, and stops them cleanly when Home
Assistant stops the add-on.
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
from src.ha_link import HaLink
from src.health import Health
from src.reader import worker
from src.shared_state import SharedState

logger = logging.getLogger("octopus_charge_pack")

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATA_DIR = os.environ.get("ADDON_DATA", "/data")
PORT = 8099  # ingress_port in config.yaml defaults to 8099


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

    link = HaLink(data_dir, state)
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

    wake = asyncio.Event()  # the device picked on the page changed: read it now
    settings.adopt_options(config)  # device_id / poll_seconds from the options, before they moved to the page
    settings.on_change = lambda changes: wake.set() if {"device_id", "poll_seconds"} & set(changes) else None
    tasks = [asyncio.create_task(link.run()), asyncio.create_task(worker(state, config, data_dir, settings, wake))]
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
