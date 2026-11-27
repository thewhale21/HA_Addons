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
    areas = [{"area_id": "lounge", "name": "Living Room", "icon": "mdi:sofa"}, {"area_id": "kitchen", "name": "Kitchen"}]
    by = {a["area_id"]: S.area_entities(a["area_id"], ENTS, DEVS, STATES) for a in areas}
    cfg = S.build_home(areas, by, weather="weather.home", people=["person.matt"])
    home, lounge, kitchen = cfg["views"]
    assert home["path"] == "home" and home["theme"] == S.THEME
    cards = home["sections"][0]["cards"]
    assert any(c["type"] == "weather-forecast" for c in cards)
    assert any(c.get("tap_action", {}).get("navigation_path") == S.MAP_PATH for c in cards)
    rooms = home["sections"][1]["cards"][1:]
    assert [r["tap_action"]["navigation_path"] for r in rooms] == ["/neighbourhood-home/living-room", "/neighbourhood-home/kitchen"]
    assert lounge["subview"] and lounge["back_path"] == S.HOME_PATH
    assert [c["entity"] for c in lounge["sections"][0]["cards"] if c["type"] == "tile"] == ["light.lounge", "switch.lamp"]
    assert lounge["sections"][1]["cards"][1]["type"] == "thermostat"
    assert kitchen["path"] == "kitchen"


def test_tap_paths():
    assert S.tap_path({"target": "none"}) == ""
    assert S.tap_path({"target": "own", "path": "/wall-display-2/home"}) == "/wall-display-2/home"
    assert S.tap_path({"target": "ours"}) == S.HOME_PATH


def test_screen_settings(tmp_path):
    s = AppSettings(str(tmp_path))
    assert s.data["screen"]["target"] == "none"
    s.update({"screen": {"target": "own", "path": "wall-display-2/home", "idle": 120}})
    assert s.data["screen"]["path"] == "/wall-display-2/home"
    with pytest.raises(ValueError):
        s.update({"screen": {"target": "own", "path": ""}})
    with pytest.raises(ValueError):
        s.update({"screen": {"target": "ours", "areas": []}})
    with pytest.raises(ValueError):
        s.update({"screen": {"target": "none", "idle": 5}})
    s.update({"screen": {"target": "ours", "areas": ["lounge", "lounge"], "idle": 0}})
    assert s.data["screen"]["areas"] == ["lounge"] and AppSettings(str(tmp_path)).data["screen"]["idle"] == 0


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
        if t == "config/entity_registry/list":
            return ENTS
        if t == "config/device_registry/list":
            return DEVS
        if t == "get_states":
            return [{"entity_id": k, **v} for k, v in STATES.items()]
        return None

    out = asyncio.run(S.apply(query, {"target": "ours", "areas": ["lounge", "gone"]}, config_dir=str(tmp_path)))
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
    assert body["places"][0]["name"] == "Work" and body["screen"] == {"tap": "/x/home", "idle": 60, "map": "/neighbourhood-map/map"}
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
