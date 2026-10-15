"""Reads Octopus's planned dispatches every poll_seconds and works out what
the sensors show (src/dispatches.py); src/__main__.py starts it. Kept apart
from the web server so it can be tested without one."""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
from typing import Optional

from src.dispatches import summarise
from src.octopus import AuthError, OctopusClient
from src.shared_state import SharedState

logger = logging.getLogger(__name__)

NO_KEY_WAIT_S = 300  # with no API key, how often to look again (it needs a restart anyway)


def _load(path: Optional[str]) -> dict:
    """What's kept between restarts: the last charge and discharge start times (the templates kept their state)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except (TypeError, FileNotFoundError, ValueError):
        return {}


def _save(path: Optional[str], data: dict) -> None:
    if not path:
        return
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except OSError:
        logger.warning("Couldn't save %s", path, exc_info=True)


def pick_device(devices: list) -> Optional[str]:
    """The device to follow when none is set: the only one there is, else None (the user picks)."""
    return devices[0].get("id") if len(devices) == 1 and devices[0].get("id") else None


async def read_once(state: SharedState, client: OctopusClient, kept: dict) -> None:
    """Read the planned dispatches once and update the state (raises on failure)."""
    if not state.device_id:
        state.devices = await client.find_devices()
        state.device_id = pick_device(state.devices)
        if not state.device_id:
            listed = ", ".join(f"{d.get('id')} ({d.get('name') or d.get('deviceType') or 'device'})"
                               for d in state.devices) or "none found"
            raise ValueError(f"Set device_id on the Configuration tab to one of: {listed}")
        logger.info("Following device %s", state.device_id)
    dispatches = await client.planned_dispatches(state.device_id)
    now = datetime.datetime.now(datetime.timezone.utc)
    state.summary = summarise(dispatches, now, None, kept)
    for kind in ("charge", "discharge"):
        kept[f"{kind}_start_time"] = state.summary.get(f"{kind}_start_time")
    state.last_update = now.strftime("%Y-%m-%dT%H:%M:%SZ")


async def worker(state: SharedState, config, data_dir: Optional[str]) -> None:
    """Every poll_seconds: read the planned dispatches and work out the sensors."""
    path = os.path.join(data_dir, "state.json") if data_dir else None
    kept = _load(path)
    state.device_id = config.device_id or None
    state.poll_seconds = config.poll_seconds
    if not config.api_key:
        state.status, state.error = "Needs an API key", "Set your Octopus API key on the add-on's Configuration tab"
        logger.warning(state.error)
        while True:
            await asyncio.sleep(NO_KEY_WAIT_S)
    client = OctopusClient(config.api_key)
    try:
        while True:
            try:
                await read_once(state, client, kept)
                if state.error:
                    logger.info("Reading the dispatches again")
                state.status, state.error = "OK", None
                _save(path, kept)
            except AuthError as err:
                if state.error != str(err):
                    logger.warning("Octopus refused the API key: %s", err)
                state.status, state.error = "API key refused", str(err)
            except Exception as err:
                message = str(err) or type(err).__name__
                if state.error != message:
                    logger.warning("Couldn't read the dispatches: %s", message)
                state.status, state.error = "Error", message
            await asyncio.sleep(config.poll_seconds)
    finally:
        await client.close()
