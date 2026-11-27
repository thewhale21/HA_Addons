"""Finding your home and fetching the map around it, and keeping it.

- Your postcode's location: postcodes.io (free, no key).
- Your house: OpenStreetMap's addresses near it (Overpass), by house number and postcode. Not
  every house has its address in OpenStreetMap: then the drawing centres on the postcode, and you
  pick your house on the Overview (click it), which is kept.
- The map: OpenStreetMap (Overpass), turned into a scene by src/scene.py, saved in
  /data/scene.json so it's only fetched again when your address changes, you ask (Refresh), or
  it's REFRESH_DAYS old.
- What OpenStreetMap and postcodes.io answered is kept too (OsmCache, /data/osm/), so the map can
  be redrawn without them: after an update that draws it differently (no fetching at all), and
  when they can't be reached (the last copy used instead).
"""
from __future__ import annotations

import datetime
import gzip
import hashlib
import json
import logging
import os
from typing import Optional

from src import scene as S

logger = logging.getLogger(__name__)

POSTCODES_URL = "https://api.postcodes.io/postcodes/{pc}"
OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
USER_AGENT = "HomeAssistant-NeighbourhoodView/1 (https://github.com/thewhale21/HA_Addons)"
REFRESH_DAYS = 30


CACHE_DIR = "osm"
CACHE_KEEP = 16  # answers kept (the oldest used dropped): your map, your house's lookup, other places'


class PlaceError(Exception):
    """Something the page should say (e.g. "That postcode wasn't found")."""


class OsmCache:
    """OpenStreetMap's and postcodes.io's answers, kept (gzipped JSON) in /data/osm/, by question.

    offline_first: a kept answer is used without asking (the map redrawn after an update); else
    asked, and a kept answer used only if that fails (no connection, the server busy). self.used_copy
    says when the last fetch fell back to one (its date)."""

    def __init__(self, data_dir: Optional[str]) -> None:
        self._dir = os.path.join(data_dir, CACHE_DIR) if data_dir else None
        self.offline_first = False
        self.used_copy: Optional[str] = None

    def _path(self, key: str) -> Optional[str]:
        return os.path.join(self._dir, hashlib.sha1(key.encode()).hexdigest()[:20] + ".json.gz") if self._dir else None

    def get(self, key: str) -> Optional[tuple]:
        """(answer, when it was fetched "YYYY-MM-DDTHH:MM:SSZ") or None."""
        path = self._path(key)
        if not path:
            return None
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                kept = json.load(f)
            os.utime(path)  # (used: kept longer)
            return kept["data"], kept["at"]
        except FileNotFoundError:
            return None
        except Exception:
            logger.debug("Kept answer unreadable", exc_info=True)
            return None

    def put(self, key: str, data) -> None:
        path = self._path(key)
        if not path:
            return
        try:
            os.makedirs(self._dir, exist_ok=True)
            tmp = path + ".tmp"
            with gzip.open(tmp, "wt", encoding="utf-8") as f:
                json.dump({"at": _now(), "data": data}, f, separators=(",", ":"))
            os.replace(tmp, path)
            files = sorted((os.path.join(self._dir, n) for n in os.listdir(self._dir) if n.endswith(".json.gz")), key=os.path.getmtime)
            for old in files[:-CACHE_KEEP]:
                os.remove(old)
        except OSError:
            logger.warning("Couldn't keep OpenStreetMap's answer", exc_info=True)

    async def ask(self, key: str, fetch):
        """The answer to key: kept or fetched (await fetch()), as above."""
        if self.offline_first:
            kept = self.get(key)
            if kept:
                return kept[0]
        try:
            data = await fetch()
        except Exception as err:
            kept = self.get(key)
            if not kept:
                raise
            logger.warning("%s: using the copy kept from %s", _why(err), kept[1][:10])
            self.used_copy = min(self.used_copy or kept[1], kept[1])
            return kept[0]
        self.put(key, data)
        return data


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _why(err: Exception) -> str:
    """What went wrong, in words (a timeout's own message is empty)."""
    import asyncio
    if isinstance(err, PlaceError):
        return str(err)
    if isinstance(err, (asyncio.TimeoutError, TimeoutError)):
        return "Couldn't read OpenStreetMap: it didn't answer in time"
    return f"Couldn't read OpenStreetMap: {err or type(err).__name__}"


async def postcode_location(session, postcode: str, cache: Optional[OsmCache] = None) -> tuple:
    """(lat, lon) of the postcode's centre."""
    pc = S.norm_postcode(postcode)
    if not pc:
        raise PlaceError("That isn't a UK postcode")
    if cache:
        return tuple(await cache.ask("postcode:" + pc, lambda: postcode_location(session, pc)))
    async with session.get(POSTCODES_URL.format(pc=pc.replace(" ", "")), headers={"User-Agent": USER_AGENT},
                           timeout=_timeout(20)) as r:
        if r.status == 404:
            raise PlaceError(f"The postcode {pc} wasn't found")
        r.raise_for_status()
        data = await r.json()
    res = (data or {}).get("result") or {}
    if res.get("latitude") is None:
        raise PlaceError(f"The postcode {pc} has no location (e.g. a PO box)")
    return float(res["latitude"]), float(res["longitude"])


async def overpass(session, query: str, cache: Optional[OsmCache] = None) -> dict:
    """Overpass's answer, from the first server that gives one (or kept: see OsmCache)."""
    if cache:
        return await cache.ask("overpass:" + query, lambda: overpass(session, query))
    last = None
    for url in OVERPASS_URLS:
        try:
            async with session.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT},
                                    timeout=_timeout(90)) as r:
                if r.status in (429, 503, 504):
                    last = PlaceError(f"OpenStreetMap's server is busy ({r.status}): try again in a few minutes")
                    continue
                r.raise_for_status()
                return await r.json(content_type=None)
        except PlaceError:
            raise
        except Exception as err:  # (that server's down: the next)
            last = err
            logger.debug("Overpass %s: %s", url, err)
    raise PlaceError(_why(last) if last is not None else "Couldn't read OpenStreetMap")


async def fetch_scene(session, postcode: str, number: str, picked: Optional[dict] = None, half: float = S.HALF,
                      cache: Optional[OsmCache] = None, offline_first: bool = False) -> dict:
    """The scene for your address (src/scene.py), with where it's from. picked: your house chosen on
    the page, {"id", "lat", "lon"}: centred on it, without looking your address up. cache: what
    OpenStreetMap answered before (offline_first: used without asking; else if it can't be read)."""
    _start(cache, offline_first)
    if picked:
        lat, lon = float(picked["lat"]), float(picked["lon"])
        osm = await overpass(session, S.overpass_query(lat, lon, half), cache)
        sc = S.build_scene(osm, lat, lon, home_id=int(picked["id"]), half=half)
        return _finish(sc, postcode, number, (lat, lon), cache)
    lat, lon = await postcode_location(session, postcode, cache)
    home_pt = None
    if number:
        try:
            home_pt = S.find_address(await overpass(session, S.address_query(lat, lon, number), cache), postcode, number, lat, lon)
        except PlaceError as err:
            logger.info("Your house number couldn't be looked up (%s): centred on the postcode", err)
    centre = home_pt or (lat, lon)
    osm = await overpass(session, S.overpass_query(centre[0], centre[1], half), cache)
    sc = S.build_scene(osm, centre[0], centre[1], home_pt=home_pt, half=half)
    return _finish(sc, postcode, number, centre, cache)


async def fetch_area(session, lat: float, lon: float, half: float, cache: Optional[OsmCache] = None, offline_first: bool = False) -> dict:
    """The scene round another place (Settings › Other places: a Home Assistant zone), no house in it."""
    _start(cache, offline_first)
    osm = await overpass(session, S.overpass_query(lat, lon, half), cache)
    sc = S.build_scene(osm, lat, lon, half=half)
    sc.update(lat=round(lat, 6), lon=round(lon, 6), made=_made(cache))
    return sc


def _start(cache: Optional[OsmCache], offline_first: bool) -> None:
    if cache:
        cache.offline_first, cache.used_copy = offline_first, None


def _made(cache: Optional[OsmCache]) -> str:
    """When the map's data is from: now, or (made from a kept copy as OpenStreetMap couldn't be
    read) that copy's date, so it's fetched again when that's REFRESH_DAYS old."""
    return (cache.used_copy if cache and cache.used_copy else None) or _now()


def _finish(sc: dict, postcode: str, number: str, centre: tuple, cache: Optional[OsmCache] = None) -> dict:
    sc.update(postcode=S.norm_postcode(postcode), number=str(number or ""), lat=round(centre[0], 6), lon=round(centre[1], 6),
              made=_made(cache), attribution="© OpenStreetMap contributors")
    logger.info("Map made for %s %s: %d buildings, %d roads, %d trees (your house: %s)%s", sc["number"], sc["postcode"],
                len(sc["buildings"]), len(sc["roads"]), len(sc["trees"]), sc["home"]["found"],
                " (from the copy of OpenStreetMap's data kept on " + cache.used_copy[:10] + ")" if cache and cache.used_copy else "")
    return sc


def _timeout(s: float):
    import aiohttp
    return aiohttp.ClientTimeout(total=s)


def picked_home(sc: dict, building_id: int) -> dict:
    """Your house chosen on the page: {"id", "lat", "lon"} (its middle), for fetch_scene."""
    for b in (sc or {}).get("buildings") or []:
        if b["id"] == building_id:
            x, y = S.centroid(b["p"])
            lat, lon = S.unproject(x, y, sc["lat"], sc["lon"])
            return {"id": building_id, "lat": round(lat, 7), "lon": round(lon, 7)}
    raise PlaceError("That building isn't on the map")


class SceneStore:
    """The scene, kept in /data/scene.json."""

    def __init__(self, data_dir: Optional[str], name: str = "scene.json") -> None:
        self._path = os.path.join(data_dir, name) if data_dir else None
        self.scene: Optional[dict] = None
        if self._path:
            try:
                with open(self._path, encoding="utf-8") as f:
                    self.scene = json.load(f)
            except FileNotFoundError:
                pass
            except Exception:
                logger.warning("The saved map is unreadable: it's made again")

    def save(self, sc: Optional[dict]) -> None:
        self.scene = sc
        if not self._path:
            return
        try:
            if sc is None:
                os.remove(self._path)
                return
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(sc, f, separators=(",", ":"))
            os.replace(tmp, self._path)
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("Couldn't save the map", exc_info=True)

    def fits(self, postcode: str, number: str, picked: Optional[dict] = None, half: float = S.HALF, version: bool = True) -> bool:
        """The saved scene is for this address (and house picked, and map size), and not too old
        (version False: whether it would, if it weren't from an older version)."""
        sc = self.scene or {}
        if sc.get("postcode") != S.norm_postcode(postcode) or sc.get("number") != str(number or ""):
            return False
        if float(sc.get("half") or 0) != float(half):
            return False
        if version and int(sc.get("v") or 1) < S.SCENE_V:
            return False  # (made before the scene had everything now drawn: made again)
        if (picked or {}).get("id") != ((sc.get("home") or {}).get("id") if (sc.get("home") or {}).get("found") == "picked" else None):
            return False
        try:
            made = datetime.datetime.strptime(sc["made"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        except (KeyError, ValueError):
            return False
        return datetime.datetime.now(datetime.timezone.utc) - made < datetime.timedelta(days=REFRESH_DAYS)


def _fresh(sc: dict) -> bool:
    try:
        made = datetime.datetime.strptime(sc["made"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except (KeyError, ValueError, TypeError):
        return False
    return datetime.datetime.now(datetime.timezone.utc) - made < datetime.timedelta(days=REFRESH_DAYS)


class PlaceStore:
    """The other places' scenes (Settings › Other places), kept in /data/places.json: {zone: scene}."""

    def __init__(self, data_dir: Optional[str]) -> None:
        self._inner = SceneStore(data_dir, "places.json")
        self.scenes: dict = self._inner.scene if isinstance(self._inner.scene, dict) else {}

    def get(self, zone: str) -> Optional[dict]:
        return self.scenes.get(zone)

    def fits(self, zone: str, lat: float, lon: float, half: float, version: bool = True) -> bool:
        sc = self.scenes.get(zone) or {}
        return (sc.get("lat") == round(lat, 6) and sc.get("lon") == round(lon, 6)
                and float(sc.get("half") or 0) == float(half) and (not version or int(sc.get("v") or 1) >= S.SCENE_V) and _fresh(sc))

    def put(self, zone: str, sc: dict) -> None:
        self.scenes[zone] = sc
        self._inner.save(self.scenes)

    def keep_only(self, zones: list) -> None:
        """Forgets the places no longer set."""
        gone = [z for z in self.scenes if z not in zones]
        for z in gone:
            del self.scenes[z]
        if gone:
            self._inner.save(self.scenes)
