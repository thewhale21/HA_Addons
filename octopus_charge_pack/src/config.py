"""The add-on's options (Settings › Add-ons › Octopus Charge Pack › Configuration).

Home Assistant writes them to /data/options.json; the schema is in
config.yaml and the labels in translations/en.yaml."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields

OPTIONS_PATH = os.environ.get("ADDON_OPTIONS", "/data/options.json")


@dataclass(frozen=True)
class Config:
    api_key: str = ""  # Octopus API key (sk_live_...)
    # Options before 0.3.0, read once to copy them to the page's settings (src/app_settings.py):
    device_id: str = ""  # the device whose dispatches to follow
    poll_seconds: int = 60  # how often the planned dispatches are read


SCHEMA = ("api_key",)  # the options in config.yaml's schema now


def stale_options(path: str = OPTIONS_PATH) -> "dict | None":
    """The options without ones no longer in the schema (device_id and poll_seconds,
    which moved to the page in 0.3.0), if any are still there: the Supervisor warns
    about them each time it checks the options. None if there are none to drop."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, ValueError):
        return None
    if not isinstance(raw, dict) or not set(raw) - set(SCHEMA):
        return None
    return {k: v for k, v in raw.items() if k in SCHEMA}


async def drop_stale_options(path: str = OPTIONS_PATH) -> bool:
    """Save the options without the old ones (once they've been copied to the page's
    settings), through the Supervisor, so it stops warning about them. Whether it did."""
    import logging

    import aiohttp

    options = stale_options(path)
    token = os.environ.get("SUPERVISOR_TOKEN")
    if options is None or not token:
        return False
    log = logging.getLogger(__name__)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("http://supervisor/addons/self/options", json={"options": options},
                                    headers={"Authorization": f"Bearer {token}"},
                                    timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status >= 400:
                    log.info("Couldn't drop the old options (HTTP %s): %s", resp.status, (await resp.text())[:200])
                    return False
    except Exception as err:
        log.info("Couldn't drop the old options: %s", err)
        return False
    log.info("Dropped the old device_id / poll_seconds options (they're on the Settings tab since 0.3.0)")
    return True


def load_config(path: str = OPTIONS_PATH) -> Config:
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, ValueError):
        raw = {}  # running outside Home Assistant (development): the defaults
    known = {f.name for f in fields(Config)}
    out = {k: v for k, v in (raw or {}).items() if k in known}
    for key in ("api_key", "device_id"):
        out[key] = str(out.get(key) or "").strip()
    if "poll_seconds" in out:
        out["poll_seconds"] = max(30, min(3600, int(out["poll_seconds"] or 60)))
    return Config(**out)
