"""Settings made on the web page rather than in the add-on's options: your address (Settings ›
Your home), your house if you picked it on the Overview, and the log level (Diagnostics › Debug).
Saved in /data/settings.json. Add your own: a default in DEFAULTS, a check in _valid, a property."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Callable, Optional

from src.scene import norm_postcode

logger = logging.getLogger(__name__)

LEVELS = ("debug", "info", "warning", "error")
DEFAULTS = {"log_level": "info", "postcode": "", "house_number": "",
            # your house picked on the Overview: {"id": OpenStreetMap way id, "lat", "lon"}, or None
            "picked": None,
            # how far round your house the map goes (m), and other places shown beside it:
            # [{"zone": "zone.work", "side": "left"|"right"|"up"|"down", "radius": m}]
            "radius": 150, "places": [],
            # the map as a screensaver (src/screen.py), for every device and user, or not (enabled):
            # the map's on a view (map: a path, or "" for the Map dashboard made here); tapping it
            # goes to a view ("own": path) or a dashboard made from rooms ("ours": areas, in order,
            # and the things ticked in each, entities {area: [entity, ...]}, all if not there); and
            # any screen left alone `idle` s comes back to it
            "screen": {"enabled": False, "map": "", "target": "own", "path": "", "idle": 120, "areas": [], "entities": {}}}
SIDES = ("left", "right", "up", "down")
MAX_PLACES = 6
MAX_ROOMS = 30
PATH_RE = re.compile(r"^/[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*/?$")
NUMBER_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z /-]{0,11}$")


class AppSettings:
    def __init__(self, data_dir: Optional[str] = None, on_change: Optional[Callable[[dict], None]] = None) -> None:
        self._path = os.path.join(data_dir, "settings.json") if data_dir else None
        self.on_change = on_change  # called with what changed
        self.data = dict(DEFAULTS)
        for key, value in self._load().items():
            try:
                self.data.update(self._valid({key: value}))
            except ValueError:
                pass  # an old or bad value: the default stays

    @property
    def log_level(self) -> str:
        return self.data["log_level"]

    def apply_log_level(self) -> None:
        logging.getLogger().setLevel(getattr(logging, self.log_level.upper()))

    @staticmethod
    def _valid(body: dict) -> dict:
        out = {}
        if "postcode" in body:
            raw = str(body["postcode"] or "").strip()
            pc = norm_postcode(raw)
            if raw and not pc:
                raise ValueError("That isn't a UK postcode (e.g. RG41 2AB)")
            out["postcode"] = pc
        if "house_number" in body:
            num = str(body["house_number"] or "").strip()
            if num and not NUMBER_RE.match(num):
                raise ValueError("The house number is up to 12 letters and numbers (e.g. 12 or 12A)")
            out["house_number"] = num
        if "radius" in body:
            try:
                r = int(float(body["radius"]))
            except (TypeError, ValueError):
                raise ValueError("The map size is a number of metres") from None
            if not 50 <= r <= 500:
                raise ValueError("The map size is 50 to 500 m round your house")
            out["radius"] = r
        if "places" in body:
            places = body["places"]
            if not isinstance(places, list) or len(places) > MAX_PLACES:
                raise ValueError(f"Up to {MAX_PLACES} other places")
            clean = []
            for pl in places:
                if not isinstance(pl, dict) or not str(pl.get("zone") or "").startswith("zone."):
                    raise ValueError("Each place is a Home Assistant zone (zone.…)")
                side = str(pl.get("side") or "left")
                if side not in SIDES:
                    raise ValueError("A place's side is left, right, up or down")
                try:
                    r = int(float(pl.get("radius") or 100))
                except (TypeError, ValueError):
                    raise ValueError("A place's size is a number of metres") from None
                if not 30 <= r <= 400:
                    raise ValueError("A place's size is 30 to 400 m round it")
                clean.append({"zone": str(pl["zone"]).strip(), "side": side, "radius": r})
            out["places"] = clean
        if "screen" in body:
            s = body["screen"]
            if not isinstance(s, dict):
                raise ValueError("screen must be an object")
            target = str(s.get("target") or "own")
            # (before 0.14.0: target "none" was off, the others on)
            enabled = bool(s["enabled"]) if "enabled" in s else target != "none"
            if target == "none":
                target = "own"
            if target not in ("own", "ours"):
                raise ValueError("Tapping the map goes to: own or ours")

            def a_path(raw, what):
                p = str(raw or "").strip()
                if not p:
                    return ""
                if not p.startswith("/"):
                    p = "/" + p
                if not PATH_RE.match(p):
                    raise ValueError(f"{what} is a dashboard view's address, like /wall-display-2/home")
                return p.rstrip("/")
            path = a_path(s.get("path"), "Where tapping the map goes")
            map_at = a_path(s.get("map"), "Where the map is")
            try:
                idle = int(float(s.get("idle", 120)))
            except (TypeError, ValueError):
                raise ValueError("The time before coming back to the map is a number of seconds") from None
            if idle == 0:
                idle = 120  # (before 0.14.0, 0 was "never": now it's on or off as a whole)
            if not 30 <= idle <= 3600:
                raise ValueError("Back to the map after 30 s to an hour")
            areas = s.get("areas") or []
            if not isinstance(areas, list) or len(areas) > MAX_ROOMS or not all(isinstance(a, str) and a for a in areas):
                raise ValueError(f"Up to {MAX_ROOMS} rooms")
            areas = list(dict.fromkeys(areas))
            ents = s.get("entities") or {}
            if not isinstance(ents, dict):
                raise ValueError("entities must be {room: [entity, ...]}")
            picked = {}
            for area, lst in ents.items():
                if area not in areas:
                    continue  # (a room no longer ticked)
                if not isinstance(lst, list) or len(lst) > 60 or not all(isinstance(e, str) and "." in e for e in lst):
                    raise ValueError("A room's things are up to 60 entities")
                picked[area] = list(dict.fromkeys(lst))
            if enabled and target == "own" and not path:
                raise ValueError("Choose where tapping the map goes (e.g. /wall-display-2/home)")
            if enabled and target == "ours" and not areas:
                raise ValueError("Choose at least one room for the dashboard")
            if enabled and map_at and path and map_at == path:
                raise ValueError("Tapping the map can't go to the map's own view")
            out["screen"] = {"enabled": enabled, "map": map_at, "target": target, "path": path, "idle": idle,
                             "areas": areas, "entities": picked}
        if "picked" in body:
            p = body["picked"]
            if p is not None:
                try:
                    p = {"id": int(p["id"]), "lat": float(p["lat"]), "lon": float(p["lon"])}
                except (KeyError, TypeError, ValueError):
                    raise ValueError("picked must be {id, lat, lon} or null") from None
            out["picked"] = p
        if "log_level" in body:
            level = str(body["log_level"] or "").lower()
            if level not in LEVELS:
                raise ValueError("Log level must be one of: " + ", ".join(LEVELS))
            out["log_level"] = level
        return out

    def update(self, body) -> dict:
        if not isinstance(body, dict):
            raise ValueError("Send a JSON object")
        changes = self._valid(body)
        if not changes:
            raise ValueError("Nothing to change: " + ", ".join(DEFAULTS))
        # (a new address: the house picked for the old one goes)
        if any(k in changes and changes[k] != self.data[k] for k in ("postcode", "house_number")) and "picked" not in changes:
            changes["picked"] = None
        self.data.update(changes)
        self._save()
        if "log_level" in changes:
            self.apply_log_level()  # straight away, from the web page or the API
        if self.on_change is not None:
            self.on_change(changes)
        return dict(self.data)

    def _load(self) -> dict:
        if not self._path:
            return {}
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception:
            logger.warning("Settings %s are unreadable: using the defaults", self._path)
            return {}

    def _save(self) -> None:
        if not self._path:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, self._path)
        except Exception:
            logger.warning("Could not save the settings", exc_info=True)
