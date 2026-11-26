"""The dashboard card: its file put where Home Assistant serves it (/local/), and added to your
dashboards' resources, so "custom:neighbourhood-view-card" works without any setting up.

The add-on maps Home Assistant's config folder (config.yaml: map homeassistant_config), so the
file goes in its www folder: www/neighbourhood-view/neighbourhood-view-card.js, served at
/local/neighbourhood-view/neighbourhood-view-card.js. It has no data about you in it: the card
reads the map from the add-on (through ingress), as the add-on's own page does.

The resource is added (or its ?v= updated after an update, so browsers get the new one) through
Home Assistant's websocket API. With dashboards in YAML mode that can't be done: the page says to
add it by hand.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HA_CONFIG = os.environ.get("HA_CONFIG_DIR", "/homeassistant")
FOLDER = "neighbourhood-view"
FILE = "neighbourhood-view-card.js"
URL = f"/local/{FOLDER}/{FILE}"
SOURCE = Path(__file__).parent / "static" / FILE


def card_js(version: str) -> str:
    """The card's file, with the add-on's version in it."""
    return SOURCE.read_text(encoding="utf-8").replace("__VERSION__", version or "dev")


def write_card(version: str, config_dir: str = HA_CONFIG) -> Optional[str]:
    """Puts the card in Home Assistant's www folder. Returns the error, or None."""
    if not os.path.isdir(config_dir):
        return "Home Assistant's config folder isn't mapped into the add-on"
    folder = os.path.join(config_dir, "www", FOLDER)
    try:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, FILE)
        text = card_js(version)
        try:
            with open(path, encoding="utf-8") as f:
                if f.read() == text:
                    return None
        except FileNotFoundError:
            pass
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        logger.info("Dashboard card written to www/%s/%s", FOLDER, FILE)
        return None
    except OSError as err:
        return f"Couldn't write the card: {err}"


async def register(query, version: str) -> dict:
    """Adds the card to your dashboards' resources (or brings its version up to date).
    query: HaLink.query. Returns {"status": "added" / "updated" / "ok" / "manual", "url", "detail"}."""
    url = f"{URL}?v={version or 'dev'}"
    try:
        resources = await query({"type": "lovelace/resources"}) or []
    except Exception as err:
        return {"status": "manual", "url": url,
                "detail": f"Couldn't read your dashboards' resources ({err}): with dashboards in YAML mode, add it by hand"}
    mine = [r for r in resources if str(r.get("url") or "").split("?")[0] == URL]
    try:
        if not mine:
            await query({"type": "lovelace/resources/create", "res_type": "module", "url": url})
            logger.info("Dashboard card added to your dashboards' resources (%s)", url)
            return {"status": "added", "url": url}
        if mine[0].get("url") != url or mine[0].get("type") != "module":
            await query({"type": "lovelace/resources/update", "resource_id": mine[0]["id"], "res_type": "module", "url": url})
            logger.info("Dashboard card's resource updated (%s)", url)
            return {"status": "updated", "url": url}
        return {"status": "ok", "url": url}
    except Exception as err:
        return {"status": "manual", "url": url, "detail": f"Couldn't add it to your dashboards' resources: {err}"}
