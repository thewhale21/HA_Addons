"""The map for the dashboard card, for any Home Assistant user (kiosk and other non-admin users too).

The add-on's page and API are behind ingress, which only administrators can open. So the add-on
also writes what the card needs (the map, the other places' maps, which entities to follow, where
a tap goes) to a file in Home Assistant's www folder, under a long random name:
www/neighbourhood-view/map-<token>.json, served at /local/neighbourhood-view/map-<token>.json.
The name is only told to signed-in users: it's the map_url attribute of
sensor.neighbourhood_view_status, which the card reads. (Files in www are served without signing
in, so the name is what keeps it private: a new one can be made in Settings › Dashboard card.)

payload() is pure, for the tests and /api/scene.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
from typing import Optional

from src import screen as SC

logger = logging.getLogger(__name__)

FOLDER = "neighbourhood-view"
TOKEN_FILE = "card_token"


def payload(settings_data: Optional[dict], store_scene: Optional[dict], place_scene, ents: Optional[dict]) -> dict:
    """What the card draws: {"scene", "places", "entities", "screen"}. place_scene(zone) -> scene."""
    s = settings_data or {}
    sc = store_scene
    if sc and sc.get("postcode") != s.get("postcode"):
        sc = None  # (the old address's)
    pls = []
    for pl in s.get("places") or []:
        psc = place_scene(pl["zone"]) if place_scene else None
        if psc:
            pls.append({"zone": pl["zone"], "side": pl["side"], "name": psc.get("name") or pl["zone"], "scene": psc})
    scr = s.get("screen") or {}
    return {"scene": sc, "places": pls, "entities": ents,
            # (where a tap goes, and when a device left alone comes back)
            "screen": {"tap": SC.tap_path(scr), "idle": int(scr.get("idle") or 0), "map": SC.MAP_PATH}}


class CardData:
    """Keeps the card's file up to date, under the add-on's token (kept in /data)."""

    def __init__(self, data_dir: Optional[str], config_dir: str) -> None:
        self._token_path = os.path.join(data_dir, TOKEN_FILE) if data_dir else None
        self._folder = os.path.join(config_dir, "www", FOLDER)
        self._config_dir = config_dir
        self._last: Optional[str] = None
        self.token = self._read_token() or self.new_token()

    def _read_token(self) -> Optional[str]:
        if not self._token_path:
            return None
        try:
            with open(self._token_path, encoding="utf-8") as f:
                t = f.read().strip()
            return t if len(t) >= 32 and t.isalnum() else None
        except FileNotFoundError:
            return None

    def new_token(self) -> str:
        """A new private name for the file (the old one stops working)."""
        self.token = secrets.token_hex(24)
        self._last = None
        if self._token_path:
            try:
                with open(self._token_path, "w", encoding="utf-8") as f:
                    f.write(self.token)
            except OSError:
                logger.warning("Couldn't keep the card's token", exc_info=True)
        return self.token

    @property
    def name(self) -> str:
        return f"map-{self.token}.json"

    @property
    def url(self) -> str:
        return f"/local/{FOLDER}/{self.name}"

    def write(self, data: dict) -> Optional[str]:
        """Writes the file if it changed (and removes old ones). Returns the error, or None."""
        if not os.path.isdir(self._config_dir):
            return "Home Assistant's config folder isn't mapped into the add-on"
        text = json.dumps(data, separators=(",", ":"))
        path = os.path.join(self._folder, self.name)
        if text == self._last and os.path.exists(path):
            return None
        try:
            os.makedirs(self._folder, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, path)
            self._last = text
            for other in os.listdir(self._folder):
                if other.startswith("map-") and other.endswith(".json") and other != self.name:
                    try:
                        os.remove(os.path.join(self._folder, other))
                    except OSError:
                        pass
            return None
        except OSError as err:
            return f"Couldn't write the map for the card: {err}"
