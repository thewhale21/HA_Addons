"""The add-on: starts the web page, the Home Assistant link, the map maker and the dashboard
card's set-up, and stops them cleanly when Home Assistant stops the add-on."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Optional

import aiohttp
from aiohttp import web

from src import card_install, live, log_filters, places
from src.api import create_api_app
from src.app_settings import AppSettings
from src.config import load_config
from src.debug_tools import DebugTools, install_log_buffer
from src.ha_link import HaLink
from src.health import Health
from src.shared_state import SharedState

logger = logging.getLogger("neighbourhood_view")

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATA_DIR = os.environ.get("ADDON_DATA", "/data")
PORT = 8099  # ingress_port in config.yaml defaults to 8099
WORKER_INTERVAL_S = 60


MAP_RETRY_S = 15 * 60  # after it couldn't be made (e.g. OpenStreetMap busy): tried again then
MAP_CHECK_S = 6 * 3600  # ...and looked at this often anyway (made again once it's 30 days old)


async def map_maker(state: SharedState, settings: AppSettings, store: places.SceneStore, wake: asyncio.Event) -> None:
    """Makes the map for your address (src/places.py) when there's none for it (or it's old, or
    Refresh was pressed: wake with state.extra["force"]), and keeps the page's state up to date."""
    async with aiohttp.ClientSession() as session:
        while True:
            wake.clear()
            s = settings.data
            force = state.extra.pop("force", False)
            wait = MAP_CHECK_S
            if not s["postcode"]:
                state.status, state.error = "Waiting for your address", None
            elif force or not store.fits(s["postcode"], s["house_number"], s["picked"]):
                state.status, state.error = "Making the map", None
                try:
                    store.save(await places.fetch_scene(session, s["postcode"], s["house_number"], s["picked"]))
                except places.PlaceError as err:
                    state.error = str(err)
                    wait = MAP_RETRY_S
                    logger.warning("The map couldn't be made: %s", err)
                except Exception as err:
                    state.error = f"The map couldn't be made: {err}"
                    wait = MAP_RETRY_S
                    logger.warning("The map couldn't be made", exc_info=True)
            sc = store.scene
            if sc and s["postcode"] and sc.get("postcode") == s["postcode"]:
                state.made, state.buildings = sc.get("made"), len(sc.get("buildings") or [])
                state.home_found = (sc.get("home") or {}).get("found")
                state.address = ", ".join(x for x in (sc.get("number"), sc.get("postcode")) if x)
                if not state.error:
                    state.status = "Ready"
            elif not s["postcode"]:
                state.made, state.buildings, state.home_found, state.address = None, 0, None, None
            if state.error:
                state.status = "Problem"
            try:
                await asyncio.wait_for(wake.wait(), wait)
            except asyncio.TimeoutError:
                pass


async def card_setup(state: SharedState, link: HaLink, version: str) -> None:
    """Puts the dashboard card in place and adds it to your dashboards' resources, once Home
    Assistant's connected (src/card_install.py)."""
    err = card_install.write_card(version)
    if err:
        state.card = {"status": "manual", "url": card_install.URL, "detail": err}
        logger.warning("Dashboard card: %s", err)
        return
    if not link.available:
        state.card = {"status": "manual", "url": card_install.URL, "detail": "Not running under Home Assistant"}
        return
    for _ in range(120):  # (up to 2 minutes for the link)
        if link.connected:
            break
        await asyncio.sleep(1)
    state.card = await card_install.register(link.query, version)
    if state.card["status"] == "manual":
        logger.warning("Dashboard card: %s", state.card.get("detail"))


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
    store = places.SceneStore(data_dir)
    wake = asyncio.Event()

    async def entity_changed(entity_id: str, st) -> None:
        """The weather, someone's home/away or the sun changed: drawn over the map."""
        state.live = live.compute(link.settings, link.states)

    link = HaLink(data_dir, state, on_entity_changed=entity_changed)
    debug = DebugTools(config=config, log_buffer=log_buffer, settings=settings)

    app = create_api_app(state, ha_link=link, health=health, debug=debug, app_settings=settings,
                         store=store, wake=wake)
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

    tasks = [asyncio.create_task(link.run()), asyncio.create_task(map_maker(state, settings, store, wake)),
             asyncio.create_task(card_setup(state, link, health.version))]
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
