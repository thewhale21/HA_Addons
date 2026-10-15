"""Reads Octopus's planned dispatches every poll_seconds and works out what
the sensors show (src/dispatches.py); src/__main__.py starts it. Kept apart
from the web server so it can be tested without one."""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import time
from typing import Optional

from src.dispatches import summarise, track_changes, track_completed
from src.octopus import AuthError, OctopusClient
from src.shared_state import SharedState

logger = logging.getLogger(__name__)

NO_KEY_WAIT_S = 300  # with no API key, how often to look again (it needs a restart anyway)
DEVICES_EVERY_S = 6 * 3600  # the account's devices (for the page's list) are read again this often


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
    """The device to follow when none is picked: the only one there is, else None (the user picks)."""
    return devices[0].get("id") if len(devices) == 1 and devices[0].get("id") else None


async def read_once(state: SharedState, client: OctopusClient, kept: dict, wanted: Optional[str],
                    find_devices: bool = False) -> None:
    """Read the planned dispatches once and update the state (raises on failure). `wanted` is the
    device picked on the page (or the device_id option); with `find_devices` (or no device yet) the
    account's devices are read too, for the page's list."""
    if find_devices or not state.devices:
        state.devices = await client.find_devices()
    device = wanted or pick_device(state.devices)
    if not device:
        raise ValueError("Pick your device on the Settings tab (your account has "
                         f"{len(state.devices) or 'no'} device{'' if len(state.devices) == 1 else 's'})")
    if device != state.device_id:
        if state.device_id is not None:
            kept.pop("plan", None)  # another device: its plan isn't a change to this one's
        logger.info("Following device %s", device)
        state.device_id, state.summary = device, {}
    dispatches = await client.planned_dispatches(device)
    now = datetime.datetime.now(datetime.timezone.utc)
    state.summary = summarise(dispatches, now, None, kept)
    for kind in ("charge", "discharge"):
        kept[f"{kind}_start_time"] = state.summary.get(f"{kind}_start_time")
    # Completed sessions: still listed within two reads (and a minute) of their end
    for c in track_completed(kept, dispatches, now, grace_s=2 * (state.poll_seconds or 60) + 60):
        logger.info("Completed %s: %s to %s (%s kWh)", c["kind"] or "dispatch", c["start"], c["end"], c["energyAddedKwh"])
    state.completed = list(kept.get("completed") or [])
    for c in track_changes(kept, dispatches, now):
        d = c["dispatch"]
        logger.info("Plan change: %s %s %s to %s (%s kWh)", c["change"], d["kind"], d["start"], d["end"], d["energyAddedKwh"])
    state.changes = list(kept.get("changes") or [])
    state.last_update = now.strftime("%Y-%m-%dT%H:%M:%SZ")


async def worker(state: SharedState, config, data_dir: Optional[str], settings=None,
                 wake: Optional[asyncio.Event] = None, after_read=None) -> None:
    """Every poll_seconds (or when the device or interval picked on the page changes): read the planned
    dispatches and work out the sensors. The account's devices are read again every DEVICES_EVERY_S."""
    path = os.path.join(data_dir, "state.json") if data_dir else None
    kept = _load(path)
    state.completed = list(kept.get("completed") or [])
    state.changes = list(kept.get("changes") or [])
    wake = wake or asyncio.Event()
    if not config.api_key:
        state.status, state.error = "Needs an API key", "Set your Octopus API key on the add-on's Configuration tab"
        logger.warning(state.error)
        while True:
            await asyncio.sleep(NO_KEY_WAIT_S)
    client = OctopusClient(config.api_key)
    devices_at = 0.0
    try:
        while True:
            wake.clear()
            wanted = (settings.device_id if settings is not None else "") or config.device_id or None
            state.poll_seconds = settings.poll_seconds if settings is not None else config.poll_seconds
            now = time.time()
            try:
                await read_once(state, client, kept, wanted, find_devices=now - devices_at >= DEVICES_EVERY_S)
                devices_at = devices_at if now - devices_at < DEVICES_EVERY_S else now
                if state.error:
                    logger.info("Reading the dispatches again")
                state.status, state.error = "OK", None
                _save(path, kept)
                if after_read is not None:
                    try:
                        # (it may add to the completed sessions, e.g. the SoC check: saved then)
                        if await after_read((state.summary or {}).get("dispatches") or [], kept):
                            state.completed = list(kept.get("completed") or [])
                            _save(path, kept)
                    except Exception:
                        logger.warning("After reading the dispatches", exc_info=True)
            except AuthError as err:
                if state.error != str(err):
                    logger.warning("Octopus refused the API key: %s", err)
                state.status, state.error = "API key refused", str(err)
            except Exception as err:
                message = str(err) or type(err).__name__
                if state.error != message:
                    logger.warning("Couldn't read the dispatches: %s", message)
                state.status, state.error = "Error", message
            try:
                await asyncio.wait_for(wake.wait(), state.poll_seconds)
            except asyncio.TimeoutError:
                pass
    finally:
        await client.close()
