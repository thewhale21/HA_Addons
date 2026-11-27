"""The map as a screensaver (src/screen.py): the dashboards made and the settings."""
import asyncio

import pytest

from src import screen as S
from src.app_settings import AppSettings

ENTS = [
    {"entity_id": "light.lounge", "area_id": "lounge"},
    {"entity_id": "switch.lamp", "device_id": "d1"},                       # (its device's area)
    {"entity_id": "climate.lounge", "device_id": "d1"},
    {"entity_id": "sensor.lounge_temp", "device_id": "d1"},
    {"entity_id": "sensor.lounge_power", "device_id": "d1"},               # (not a room sensor)
    {"entity_id": "switch.hidden", "area_id": "lounge", "hidden_by": "user"},
    {"entity_id": "switch.cfg", "area_id": "lounge", "entity_category": "config"},
    {"entity_id": "light.kitchen", "area_id": "kitchen"},
]
DEVS = [{"id": "d1", "area_id": "lounge"}]
STATES = {"sensor.lounge_temp": {"attributes": {"device_class": "temperature"}},
          "sensor.lounge_power": {"attributes": {"device_class": "power"}}}


def test_a_rooms_entities():
    e = S.area_entities("lounge", ENTS, DEVS, STATES)
    assert e == {"controls": ["light.lounge", "switch.lamp"], "climate": ["climate.lounge"], "sensors": ["sensor.lounge_temp"]}


def test_the_home_dashboard():
    floors = [{"floor_id": "first", "name": "First floor", "level": 1}, {"floor_id": "ground", "name": "Ground floor", "level": 0}]
    areas = [{"area_id": "lounge", "name": "Living Room", "icon": "mdi:sofa", "floor_id": "ground"},
             {"area_id": "bed", "name": "Bedroom", "floor_id": "first"}, {"area_id": "kitchen", "name": "Kitchen"}]
    by = {a["area_id"]: S.area_entities(a["area_id"], ENTS, DEVS, STATES) for a in areas}
    by["lounge"] = S.chosen_entities(by["lounge"], ["switch.lamp", "light.lounge", "sensor.lounge_temp"])
    cfg = S.build_home(areas, by, weather="weather.home", people=["person.matt"], floors=floors, map_path="/wall-display-2/map")
    home, lounge, bed, kitchen = cfg["views"]
    assert home["path"] == "home" and home["theme"] == S.THEME
    cards = home["sections"][0]["cards"]
    assert any(c["type"] == "weather-forecast" for c in cards)
    assert any(c.get("tap_action", {}).get("navigation_path") == "/wall-display-2/map" for c in cards)
    # rooms by floor, the ground floor first, rooms on no floor last
    heads = [s["cards"][0]["heading"] for s in home["sections"][1:]]
    assert heads == ["Ground floor", "First floor", "Other rooms"]
    assert home["sections"][1]["cards"][1]["tap_action"]["navigation_path"] == "/neighbourhood-home/living-room"
    assert lounge["subview"] and lounge["back_path"] == S.HOME_PATH
    # only the things ticked, in the order ticked; climate not ticked: left out
    assert [c["entity"] for c in lounge["sections"][0]["cards"] if c["type"] == "tile"] == ["switch.lamp", "light.lounge"]
    assert [s["cards"][0]["heading"] for s in lounge["sections"][1:]] == ["Sensors"]
    assert kitchen["path"] == "kitchen"


def test_tap_paths():
    assert S.tap_path({"enabled": False, "target": "own", "path": "/x/home"}) == ""
    assert S.tap_path({"enabled": True, "target": "own", "path": "/wall-display-2/home"}) == "/wall-display-2/home"
    assert S.tap_path({"enabled": True, "target": "ours"}) == S.HOME_PATH
    assert S.saver({"enabled": True, "target": "ours", "idle": 120, "map": "/wall-display-2/map"}) == {"tap": S.HOME_PATH, "idle": 120, "map": "/wall-display-2/map"}
    assert S.saver({"enabled": False, "idle": 120}) == {"tap": "", "idle": 0, "map": S.MAP_PATH}


def test_screen_settings(tmp_path):
    s = AppSettings(str(tmp_path))
    assert s.data["screen"]["enabled"] is False
    s.update({"screen": {"enabled": True, "map": "wall-display-2/map", "target": "own", "path": "wall-display-2/home", "idle": 120}})
    assert s.data["screen"]["path"] == "/wall-display-2/home" and s.data["screen"]["map"] == "/wall-display-2/map"
    with pytest.raises(ValueError):
        s.update({"screen": {"enabled": True, "target": "own", "path": ""}})
    with pytest.raises(ValueError):
        s.update({"screen": {"enabled": True, "target": "ours", "areas": []}})
    with pytest.raises(ValueError):
        s.update({"screen": {"enabled": True, "target": "own", "path": "/a/b", "idle": 5}})
    with pytest.raises(ValueError):
        s.update({"screen": {"enabled": True, "map": "/a/map", "target": "own", "path": "/a/map"}})
    s.update({"screen": {"enabled": False, "target": "own", "path": ""}})  # (off: nothing needed)
    s.update({"screen": {"enabled": True, "target": "ours", "areas": ["lounge", "lounge"], "idle": 300,
                         "entities": {"lounge": ["light.lounge"], "gone": ["light.x"]}}})
    assert s.data["screen"]["areas"] == ["lounge"] and s.data["screen"]["entities"] == {"lounge": ["light.lounge"]}
    assert AppSettings(str(tmp_path)).data["screen"]["idle"] == 300
    # (saved by 0.12/0.13: no "enabled", target "none" or a never-coming-back idle of 0)
    assert AppSettings._valid({"screen": {"target": "none", "path": "", "idle": 120, "areas": []}})["screen"]["enabled"] is False
    old = AppSettings._valid({"screen": {"target": "own", "path": "/w/home", "idle": 0, "areas": []}})["screen"]
    assert old["enabled"] is True and old["idle"] == 120


def test_making_the_dashboards(tmp_path):
    sent = []

    async def query(p):
        sent.append(p)
        t = p["type"]
        if t == "lovelace/dashboards/list":
            return [{"url_path": S.MAP_URL}]
        if t == "frontend/get_themes":
            return {"themes": {S.THEME: {}}}
        if t == "config/area_registry/list":
            return [{"area_id": "lounge", "name": "Lounge"}]
        if t == "config/floor_registry/list":
            raise RuntimeError("unknown command")  # (an older Home Assistant)
        if t == "config/entity_registry/list":
            return ENTS
        if t == "config/device_registry/list":
            return DEVS
        if t == "get_states":
            return [{"entity_id": k, **v} for k, v in STATES.items()]
        return None

    out = asyncio.run(S.apply(query, {"enabled": True, "target": "ours", "areas": ["lounge", "gone"]}, config_dir=str(tmp_path)))
    assert out == {"map": S.MAP_PATH, "home": S.HOME_PATH, "theme": "ok", "theme_detail": None, "rooms": 1}
    assert (tmp_path / "themes" / S.THEME_FILE).read_text().startswith("#")
    creates = [p["url_path"] for p in sent if p["type"] == "lovelace/dashboards/create"]
    assert creates == [S.HOME_URL]  # (the map's was there already)
    saves = {p["url_path"]: p["config"] for p in sent if p["type"] == "lovelace/config/save"}
    assert saves[S.MAP_URL]["views"][0]["cards"][0]["type"] == "custom:neighbourhood-view-card"
    assert saves[S.HOME_URL]["views"][1]["path"] == "lounge"


def test_the_cards_map_file(tmp_path):
    from src.card_data import CardData, payload
    data, cfg = tmp_path / "data", tmp_path / "ha"
    data.mkdir(); cfg.mkdir()
    cd = CardData(str(data), str(cfg))
    assert len(cd.token) >= 32 and CardData(str(data), str(cfg)).token == cd.token  # (kept)
    body = payload({"postcode": "RG1 1AA", "places": [{"zone": "zone.work", "side": "left"}], "screen": {"target": "own", "path": "/x/home", "idle": 60}},
                   {"postcode": "RG1 1AA", "buildings": []}, {"zone.work": {"name": "Work"}}.get, {"weather": ""})
    assert body["places"][0]["name"] == "Work" and body["screen"] == {"tap": "", "idle": 0, "map": "/neighbourhood-map/map"}  # (not enabled)
    assert payload({"postcode": "RG2 2BB"}, {"postcode": "RG1 1AA"}, None, None)["scene"] is None  # (the old address's)
    assert cd.write(body) is None
    first = cfg / "www" / "neighbourhood-view" / cd.name
    assert first.exists() and cd.url.endswith(cd.name)
    cd.new_token()
    assert cd.write(body) is None and not first.exists()  # (the old name's gone)


def test_the_status_sensor_says_where_the_map_is():
    from src.ha_entities import SensorPublisher
    from src.shared_state import SharedState
    pub, state = SensorPublisher(), SharedState(status="Ready")
    assert pub.due(state, 0)[0][2]["map_url"] is None
    state.extra["map_url"] = "/local/neighbourhood-view/map-abc.json"
    (eid, value, attrs), = pub.due(state, 1)
    assert value == "Ready" and attrs["map_url"].endswith("map-abc.json")


def test_the_views_to_pick(tmp_path):
    async def query(p):
        if p["type"] == "lovelace/dashboards/list":
            return [{"url_path": "wall-display-2", "title": "Wall display"}, {"url_path": "yaml-one", "title": "YAML"}]
        if p["type"] == "lovelace/config":
            if p["url_path"] == "wall-display-2":
                return {"views": [{"title": "Map", "path": "map"}, {"title": "Home", "path": "home"}, {"title": "Untitled"}]}
            if p["url_path"] == "yaml-one":
                raise RuntimeError("config not found")
            return {"strategy": {"type": "original-states"}}
    v = asyncio.run(S.views_list(query))
    assert [x["path"] for x in v] == ["/lovelace", "/wall-display-2/map", "/wall-display-2/home", "/wall-display-2/2", "/yaml-one"]
    assert v[2]["title"] == "Wall display › Home"
