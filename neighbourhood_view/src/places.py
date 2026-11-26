"""Finding your home and fetching the map around it, and keeping it.

- Your postcode's location: postcodes.io (free, no key).
- Your house: OpenStreetMap's addresses near it (Overpass), by house number and postcode. Not
  every house has its address in OpenStreetMap: then the drawing centres on the postcode, and you
  pick your house on the Overview (click it), which is kept.
- The map: OpenStreetMap (Overpass), turned into a scene by src/scene.py, saved in
  /data/scene.json so it's only fetched again when your address changes, you ask (Refresh), or
  it's REFRESH_DAYS old.
"""
from __future__ import annotations

import datetime
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


class PlaceError(Exception):
    """Something the page should say (e.g. "That postcode wasn't found")."""


async def postcode_location(session, postcode: str) -> tuple:
    """(lat, lon) of the postcode's centre."""
    pc = S.norm_postcode(postcode)
    if not pc:
        raise PlaceError("That isn't a UK postcode")
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


async def overpass(session, query: str) -> dict:
    """Overpass's answer, from the first server that gives one."""
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
    raise PlaceError(f"Couldn't read OpenStreetMap: {last}")


async def fetch_scene(session, postcode: str, number: str, picked: Optional[dict] = None, half: float = S.HALF) -> dict:
    """The scene for your address (src/scene.py), with where it's from. picked: your house chosen on
    the page, {"id", "lat", "lon"}: centred on it, without looking your address up."""
    if picked:
        lat, lon = float(picked["lat"]), float(picked["lon"])
        osm = await overpass(session, S.overpass_query(lat, lon, half))
        sc = S.build_scene(osm, lat, lon, home_id=int(picked["id"]), half=half)
        return _finish(sc, postcode, number, (lat, lon))
    lat, lon = await postcode_location(session, postcode)
    home_pt = None
    if number:
        try:
            home_pt = S.find_address(await overpass(session, S.address_query(lat, lon, number)), postcode, number, lat, lon)
        except PlaceError as err:
            logger.info("Your house number couldn't be looked up (%s): centred on the postcode", err)
    centre = home_pt or (lat, lon)
    osm = await overpass(session, S.overpass_query(centre[0], centre[1], half))
    sc = S.build_scene(osm, centre[0], centre[1], home_pt=home_pt, half=half)
    return _finish(sc, postcode, number, centre)


async def fetch_area(session, lat: float, lon: float, half: float) -> dict:
    """The scene round another place (Settings › Other places: a Home Assistant zone), no house in it."""
    osm = await overpass(session, S.overpass_query(lat, lon, half))
    sc = S.build_scene(osm, lat, lon, half=half)
    sc.update(lat=round(lat, 6), lon=round(lon, 6), made=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return sc


def _finish(sc: dict, postcode: str, number: str, centre: tuple) -> dict:
    sc.update(postcode=S.norm_postcode(postcode), number=str(number or ""), lat=round(centre[0], 6), lon=round(centre[1], 6),
              made=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              attribution="© OpenStreetMap contributors")
    logger.info("Map made for %s %s: %d buildings, %d roads, %d trees (your house: %s)", sc["number"], sc["postcode"],
                len(sc["buildings"]), len(sc["roads"]), len(sc["trees"]), sc["home"]["found"])
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

    def fits(self, postcode: str, number: str, picked: Optional[dict] = None, half: float = S.HALF) -> bool:
        """The saved scene is for this address (and house picked, and map size), and not too old."""
        sc = self.scene or {}
        if sc.get("postcode") != S.norm_postcode(postcode) or sc.get("number") != str(number or ""):
            return False
        if float(sc.get("half") or 0) != float(half):
            return False
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

    def fits(self, zone: str, lat: float, lon: float, half: float) -> bool:
        sc = self.scenes.get(zone) or {}
        return (sc.get("lat") == round(lat, 6) and sc.get("lon") == round(lon, 6)
                and float(sc.get("half") or 0) == float(half) and _fresh(sc))

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
