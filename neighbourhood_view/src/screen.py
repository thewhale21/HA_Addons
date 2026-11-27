"""The map as a screensaver (Settings › Screensaver).

- Tapping the map on a dashboard goes to another dashboard: your own (a path, e.g.
  /wall-display-2/home), or one made here from the rooms (Home Assistant areas) you choose.
- After a while left alone, a device that's been told to (the 🖵 button on the map's toolbar)
  comes back to the map. That's done in the browser by the card's file, which Home Assistant loads
  on every dashboard (static/neighbourhood-view-card.js: the idle watcher).

Made through Home Assistant's websocket API (src/ha_link.py HaLink.query):
- the Map dashboard (MAP_URL): one panel view with the card;
- the Home dashboard (HOME_URL), when chosen: a Home view (clock, weather, people, a button a
  room) and a view a room with its lights, switches, heating and sensors;
- the "Neighbourhood View" theme, written to themes/ in Home Assistant's config folder, so both
  look like the map (glassy dark cards over a sky: day, or night in dark mode).

build_home() and area_entities() are pure, for the tests.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

MAP_URL = "neighbourhood-map"
HOME_URL = "neighbourhood-home"
MAP_PATH = f"/{MAP_URL}/map"
HOME_PATH = f"/{HOME_URL}/home"
THEME = "Neighbourhood View"
THEME_FILE = "neighbourhood_view.yaml"

SKY_DAY = "linear-gradient(180deg, #3b8fd0 0%, #6fb6e4 45%, #a9d8ee 100%)"
SKY_NIGHT = "linear-gradient(180deg, #050c20 0%, #0c1a3b 55%, #17284d 100%)"

THEME_YAML = f"""# The Neighbourhood View add-on's theme (written by the add-on: changes here are overwritten).
# Glassy dark cards over a sky, like the map: blue by day, night sky in dark mode.
{THEME}:
  primary-color: "#2196f3"
  accent-color: "#ffb74d"
  primary-text-color: "#ffffff"
  secondary-text-color: "rgba(255, 255, 255, 0.72)"
  disabled-text-color: "rgba(255, 255, 255, 0.4)"
  text-primary-color: "#ffffff"
  state-icon-color: "#9ccdf5"
  state-active-color: "#ffd36b"
  divider-color: "rgba(255, 255, 255, 0.12)"
  ha-card-background: "rgba(18, 22, 30, 0.78)"
  card-background-color: "#18202c"
  primary-background-color: "#121a26"
  secondary-background-color: "#1c2533"
  ha-card-border-radius: "18px"
  ha-card-border-width: "1px"
  ha-card-border-color: "rgba(255, 255, 255, 0.14)"
  ha-card-box-shadow: "0 4px 16px rgba(8, 16, 36, 0.30)"
  app-header-background-color: "rgba(18, 22, 30, 0.88)"
  app-header-text-color: "#ffffff"
  sidebar-background-color: "#121a26"
  sidebar-text-color: "#e6edf5"
  sidebar-icon-color: "#9ccdf5"
  sidebar-selected-icon-color: "#2196f3"
  sidebar-selected-text-color: "#ffffff"
  lovelace-background: "center / cover no-repeat fixed {SKY_DAY}"
  modes:
    dark:
      lovelace-background: "center / cover no-repeat fixed {SKY_NIGHT}"
"""

# what a room's view shows, in this order
CONTROL_DOMAINS = ("light", "switch", "fan", "cover", "lock", "media_player")
SENSOR_CLASSES = ("temperature", "humidity", "illuminance", "co2", "carbon_dioxide")
BINARY_CLASSES = ("door", "window", "motion", "occupancy", "presence", "opening", "garage_door")
MAX_A_ROOM = 30


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s or "room"


def area_entities(area_id: str, entity_reg: list, device_reg: list, states: dict) -> dict:
    """A room's entities, by kind: {"controls": [...], "climate": [...], "sensors": [...]}.
    In the room: the entity's own area, else its device's. Hidden, disabled and config/diagnostic
    entities are left out."""
    dev_area = {d.get("id"): d.get("area_id") for d in device_reg or []}
    out = {"controls": [], "climate": [], "sensors": []}
    for e in entity_reg or []:
        eid = e.get("entity_id") or ""
        if e.get("disabled_by") or e.get("hidden_by") or e.get("entity_category"):
            continue
        if (e.get("area_id") or dev_area.get(e.get("device_id"))) != area_id:
            continue
        domain = eid.split(".", 1)[0]
        attrs = (states.get(eid) or {}).get("attributes") or {}
        dc = attrs.get("device_class") or e.get("device_class") or e.get("original_device_class")
        if domain in CONTROL_DOMAINS:
            out["controls"].append(eid)
        elif domain == "climate":
            out["climate"].append(eid)
        elif domain == "sensor" and dc in SENSOR_CLASSES:
            out["sensors"].append(eid)
        elif domain == "binary_sensor" and dc in BINARY_CLASSES:
            out["sensors"].append(eid)
    order = {d: i for i, d in enumerate(CONTROL_DOMAINS)}
    out["controls"].sort(key=lambda x: (order.get(x.split(".", 1)[0], 9), x))
    for k in out:
        out[k] = out[k][:MAX_A_ROOM]
    return out


def _nav(path: str) -> dict:
    return {"action": "navigate", "navigation_path": path}


def chosen_entities(found: dict, picked: Optional[list]) -> dict:
    """A room's entities, by kind, cut to those ticked (picked: entity ids, or None for all), in the
    order ticked within each kind."""
    if picked is None:
        return found
    pos = {e: i for i, e in enumerate(picked)}
    return {k: sorted([e for e in v if e in pos], key=pos.get) for k, v in found.items()}


def floors_in_order(floors: Optional[list]) -> list:
    """Home Assistant's floors, bottom up (by level, then name)."""
    return sorted(floors or [], key=lambda fl: (fl.get("level") if fl.get("level") is not None else 999, str(fl.get("name") or "").lower()))


def build_home(areas: list, by_area: dict, weather: Optional[str] = None, people: Optional[list] = None,
               floors: Optional[list] = None, map_path: str = MAP_PATH) -> dict:
    """The Home dashboard's config. areas: [{"area_id", "name", "icon", "floor_id"}] in the order
    chosen; by_area: {area_id: {"controls", "climate", "sensors"}}; floors: Home Assistant's floors,
    the rooms grouped under them (bottom floor first; rooms on no floor last)."""
    home_cards = [
        {"type": "heading", "heading": "Home", "heading_style": "title", "icon": "mdi:home",
         "badges": [{"type": "entity", "entity": p, "show_state": True} for p in (people or [])]},
        {"type": "clock", "clock_size": "large", "clock_style": "digital", "time_format": "24", "show_seconds": False,
         "grid_options": {"columns": "full"}},
    ]
    if weather:
        home_cards.append({"type": "weather-forecast", "entity": weather, "show_current": True, "show_forecast": True,
                           "forecast_type": "daily", "grid_options": {"columns": "full"}})
    home_cards.append({"type": "button", "name": "Map", "icon": "mdi:map-marker-radius", "show_state": False,
                       "tap_action": _nav(map_path), "grid_options": {"columns": "full", "rows": 1}})
    views, used, paths = [], {"home", "map"}, {}
    for a in areas:
        path = slug(a.get("name") or a["area_id"])
        while path in used:
            path += "-2"
        used.add(path)
        paths[a["area_id"]] = path
    # the rooms, a section a floor
    room_sections = []
    groups = [(fl, [a for a in areas if a.get("floor_id") == fl.get("floor_id")]) for fl in floors_in_order(floors)]
    known = {fl.get("floor_id") for fl in floors or []}
    groups.append(({"name": "Other rooms" if any(g for _, g in groups) else "Rooms", "icon": "mdi:floor-plan"},
                   [a for a in areas if a.get("floor_id") not in known or not a.get("floor_id")]))
    for fl, rooms in groups:
        if not rooms:
            continue
        cards = [{"type": "heading", "heading": fl.get("name") or "Rooms", "heading_style": "title", "icon": fl.get("icon") or "mdi:home-floor-0"}]
        cards += [{"type": "button", "name": a.get("name") or a["area_id"], "icon": a.get("icon") or "mdi:door", "show_state": False,
                   "tap_action": _nav(f"/{HOME_URL}/{paths[a['area_id']]}"), "grid_options": {"columns": 6, "rows": 2}} for a in rooms]
        room_sections.append({"type": "grid", "cards": cards})
    for a in areas:
        icon = a.get("icon") or "mdi:door"
        ents = by_area.get(a["area_id"]) or {}
        top = [{"type": "heading", "heading": a.get("name") or a["area_id"], "heading_style": "title", "icon": icon,
                "tap_action": _nav(HOME_PATH)},
               {"type": "button", "name": "Home", "icon": "mdi:home", "show_state": False, "tap_action": _nav(HOME_PATH),
                "grid_options": {"columns": 6, "rows": 1}},
               {"type": "button", "name": "Map", "icon": "mdi:map-marker-radius", "show_state": False, "tap_action": _nav(map_path),
                "grid_options": {"columns": 6, "rows": 1}}]
        top += [{"type": "tile", "entity": e, "grid_options": {"columns": 6}} for e in ents.get("controls") or []]
        if not ents.get("controls") and not ents.get("climate") and not ents.get("sensors"):
            top.append({"type": "markdown", "content": "Nothing in this room yet: tick its things in the add-on's Screensaver settings (or give its devices this area in Home Assistant), then save again."})
        sections = [{"type": "grid", "cards": top}]
        if ents.get("climate"):
            sections.append({"type": "grid", "cards": [{"type": "heading", "heading": "Heating and cooling", "heading_style": "subtitle", "icon": "mdi:thermostat"}]
                             + [{"type": "thermostat", "entity": e, "show_current_as_primary": True, "grid_options": {"columns": "full"}} for e in ents["climate"]]})
        if ents.get("sensors"):
            sections.append({"type": "grid", "cards": [{"type": "heading", "heading": "Sensors", "heading_style": "subtitle", "icon": "mdi:gauge"}]
                             + [{"type": "tile", "entity": e, "grid_options": {"columns": 6}} for e in ents["sensors"]]})
        views.append({"title": a.get("name") or a["area_id"], "path": paths[a["area_id"]], "icon": icon, "theme": THEME, "type": "sections",
                      "max_columns": 3, "subview": True, "back_path": HOME_PATH, "sections": sections})
    home = {"title": "Home", "path": "home", "icon": "mdi:home", "theme": THEME, "type": "sections", "max_columns": 3,
            "sections": [{"type": "grid", "cards": home_cards}] + room_sections}
    return {"title": "Home", "views": [home] + views}


def build_map() -> dict:
    """The Map dashboard's config: the card, filling the screen."""
    return {"title": "Map",
            # (hides the header and sidebar for non-admins if the kiosk-mode plugin's installed; ignored if not)
            "kiosk_mode": {"non_admin_settings": {"hide_header": True, "hide_sidebar": True}},
            "views": [{"title": "Map", "path": "map", "icon": "mdi:map-marker-radius", "theme": THEME, "type": "panel",
                       "cards": [{"type": "custom:neighbourhood-view-card"}]}]}


def map_path(screen: dict) -> str:
    """Where the map is: a view of yours, or the Map dashboard made here."""
    return (screen or {}).get("map") or MAP_PATH


def tap_path(screen: dict) -> str:
    """Where tapping the map goes ('' for nowhere: the screensaver's off)."""
    s = screen or {}
    if not s.get("enabled"):
        return ""
    if s.get("target") == "ours":
        return HOME_PATH
    return s.get("path") or ""


def saver(screen: dict) -> dict:
    """For the card and the idle watcher on every dashboard (the status sensor's screensaver
    attribute): {"tap", "idle" (s, 0: off), "map"}."""
    s = screen or {}
    on = bool(s.get("enabled"))
    return {"tap": tap_path(s), "idle": int(s.get("idle") or 0) if on else 0, "map": map_path(s)}


def write_theme(config_dir: str) -> Optional[str]:
    """Writes the theme to themes/ in Home Assistant's config folder. Returns the error, or None."""
    try:
        folder = os.path.join(config_dir, "themes")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, THEME_FILE)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(THEME_YAML)
        os.replace(tmp, path)
        return None
    except OSError as err:
        return f"Couldn't write the theme: {err}"


async def _dashboard(query, url_path: str, title: str, icon: str, config: dict) -> None:
    boards = await query({"type": "lovelace/dashboards/list"}) or []
    if not any(b.get("url_path") == url_path for b in boards):
        await query({"type": "lovelace/dashboards/create", "url_path": url_path, "title": title, "icon": icon,
                     "show_in_sidebar": True, "require_admin": False})
        logger.info("Dashboard %s made", url_path)
    await query({"type": "lovelace/config/save", "url_path": url_path, "config": config})


async def registries(query) -> dict:
    """Home Assistant's floors, areas, entities and devices, and its states by entity."""
    out = {}
    for key, kind in (("floors", "config/floor_registry/list"), ("areas", "config/area_registry/list"),
                      ("entities", "config/entity_registry/list"), ("devices", "config/device_registry/list")):
        try:
            out[key] = await query({"type": kind}) or []
        except Exception:
            if key != "floors":  # (floors: Home Assistant 2024.4 and later)
                raise
            out[key] = []
    out["states"] = {s["entity_id"]: s for s in await query({"type": "get_states"}) or [] if s.get("entity_id")}
    return out


async def views_list(query) -> list:
    """Every dashboard's views, for the pickers: [{"path": "/wall-display-2/home", "title": "Wall display › Home"}]."""
    out = []
    boards = [{"url_path": None, "title": "Overview"}] + [b for b in await query({"type": "lovelace/dashboards/list"}) or [] if b.get("url_path")]
    for b in boards:
        base = b.get("url_path") or "lovelace"
        try:
            cfg = await query({"type": "lovelace/config", "url_path": b.get("url_path")}) or {}
        except Exception:
            cfg = {}
        views = cfg.get("views") if isinstance(cfg, dict) else None
        if not views:
            out.append({"path": f"/{base}", "title": b.get("title") or base})
            continue
        for i, v in enumerate(views):
            vp = v.get("path") or str(i)
            out.append({"path": f"/{base}/{vp}", "title": f"{b.get('title') or base} › {v.get('title') or vp}"})
    return out


async def apply(query, screen: dict, *, weather: Optional[str] = None, people: Optional[list] = None,
                states: Optional[dict] = None, config_dir: Optional[str] = None) -> dict:
    """Makes (or brings up to date) the theme, the Map dashboard (when the map's not on a view of
    yours) and, when chosen, the Home dashboard. Returns what happened, for the page:
    {"map", "home", "theme", "theme_detail", "rooms"}."""
    s = screen or {}
    out: dict = {"map": map_path(s), "home": None, "theme": "ok", "theme_detail": None, "rooms": 0}
    # the theme: written, then Home Assistant asked to read its themes again
    if config_dir:
        err = write_theme(config_dir)
        if err:
            out.update(theme="manual", theme_detail=err)
    if out["theme"] == "ok":
        try:
            await query({"type": "call_service", "domain": "frontend", "service": "reload_themes"})
            themes = await query({"type": "frontend/get_themes"}) or {}
            if THEME not in (themes.get("themes") or {}):
                out.update(theme="manual", theme_detail="Home Assistant doesn't read the themes folder: add "
                           "'frontend:' with 'themes: !include_dir_merge_named themes' to configuration.yaml, restart, "
                           "and save these settings again.")
        except Exception as err:
            out.update(theme="manual", theme_detail=f"Couldn't reload Home Assistant's themes: {err}")
    if not s.get("map"):
        await _dashboard(query, MAP_URL, "Map", "mdi:map-marker-radius", build_map())
    if s.get("enabled") and s.get("target") == "ours":
        reg = await registries(query)
        if states is not None:
            reg["states"] = states
        by_id = {a["area_id"]: a for a in reg["areas"]}
        chosen = [by_id[a] for a in (s.get("areas") or []) if a in by_id]
        picks = s.get("entities") or {}
        by_area = {a["area_id"]: chosen_entities(area_entities(a["area_id"], reg["entities"], reg["devices"], reg["states"]), picks.get(a["area_id"]))
                   for a in chosen}
        await _dashboard(query, HOME_URL, "Home", "mdi:home", build_home(chosen, by_area, weather, people, reg["floors"], map_path(s)))
        out.update(home=HOME_PATH, rooms=len(chosen))
    return out
