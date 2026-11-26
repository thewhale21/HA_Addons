"""The map: geometry, OpenStreetMap's data turned into a scene, finding your house, settings."""
import asyncio
import datetime
import math

import pytest

from src import scene as S
from src.app_settings import AppSettings
from src.card_install import URL, register, write_card
from src.places import SceneStore, picked_home
from tests.osm_sample import LAT0, LON0, address_answer, sample


def test_postcodes():
    assert S.norm_postcode("rg412ab") == "RG41 2AB"
    assert S.norm_postcode(" SW1A  1aa ") == "SW1A 1AA"
    assert S.norm_postcode("M1 1AE") == "M1 1AE"
    assert S.norm_postcode("12345") == "" and S.norm_postcode("") == ""


def test_projection_there_and_back():
    x, y = S.project(51.41, -0.849, LAT0, LON0)
    assert abs(y - 0) < 1 and 60 < x < 80  # (0.001° of longitude at 51° is about 70 m)
    lat, lon = S.unproject(x, y, LAT0, LON0)
    assert abs(lat - 51.41) < 1e-9 and abs(lon + 0.849) < 1e-9


def test_clipping():
    sq = [(-300, -10), (10, -10), (10, 10), (-300, 10)]
    got = S.clip_polygon(sq, 250)
    assert min(p[0] for p in got) == -250 and abs(S.area(got) - 260 * 20) < 1e-6
    assert S.clip_polygon([(300, 300), (310, 300), (310, 310)], 250) == []
    runs = S.clip_line([(-400, 0), (0, 0), (0, 400)], 250)
    assert runs == [[(-250.0, 0.0), (0, 0), (0.0, 250.0)]]
    runs = S.clip_line([(-400, 0), (-300, 0), (0, 0), (0, 300), (100, 300), (100, 0)], 250)
    assert len(runs) == 2 and runs[1][0] == (100.0, 250.0)


def test_min_rect_long_side_first():
    house = [(0, 0), (12, 0), (12, 7), (0, 7)]
    r = S.min_rect(house)
    a, b, c = r[0], r[1], r[2]
    assert abs(math.hypot(b[0] - a[0], b[1] - a[1]) - 12) < 1e-6 and abs(math.hypot(c[0] - b[0], c[1] - b[1]) - 7) < 1e-6
    assert S.area(r) > 0  # anticlockwise
    tilted = [(math.cos(0.5) * x - math.sin(0.5) * y, math.sin(0.5) * x + math.cos(0.5) * y) for x, y in house]
    assert abs(abs(S.area(S.min_rect(tilted))) - 84) < 1e-6


def test_building_kinds_and_heights():
    assert S.building_kind({"building": "house"}, 80) == "house"
    assert S.building_kind({"building": "yes"}, 80) == "house" and S.building_kind({"building": "yes"}, 900) == "large"
    assert S.building_kind({"building": "apartments"}, 500) == "flats"
    assert S.building_kind({"building": "yes", "shop": "bakery"}, 100) == "commercial"
    assert S.building_kind({"building": "garage"}, 15) == "small"
    assert S.building_height({"building:levels": "4"}, "flats") == 12
    assert S.building_height({"height": "15 m", "roof:height": "3"}, "flats") == 12
    # (a house with no height: mostly 2 storeys, some bungalows and 3 storeys; the same each time)
    hs = [S.building_height({}, "house", i) for i in range(1, 400)]
    assert set(hs) == {3.2, 5.8, 8.4} and hs.count(5.8) > 250
    assert S.building_height({}, "house", 42) == S.building_height({}, "house", 42)


def test_the_scene_from_openstreetmap():
    pt = S.find_address(address_answer(), "RG41 2AB", "12", LAT0, LON0)
    assert pt is not None  # (the number 12 with your postcode, not the one in another)
    sc = S.build_scene(sample(), pt[0], pt[1], home_pt=pt)
    assert sc["home"]["found"] == "address" and sc["home"]["id"] is not None
    assert abs(sc["home"]["x"]) < 6 and abs(sc["home"]["y"]) < 6  # (your house in the middle)
    assert len(sc["buildings"]) > 100 and any(b["r"] == "gable" for b in sc["buildings"])
    assert any(b["k"] == "flats" and b["h"] == 15 for b in sc["buildings"])
    assert {r["k"] for r in sc["roads"]} >= {"minor", "major", "path"}
    assert sc["rails"] and {a["k"] for a in sc["areas"]} >= {"grass", "water", "pitch", "paved"}
    assert len(sc["trees"]) > 20 and len({t[2] for t in sc["trees"]}) > 10  # (trees of many sizes)
    assert sc["cars"] and all(len(c) == 4 and 0 <= c[3] <= 9 for c in sc["cars"])
    h = sc["half"]
    for b in sc["buildings"]:
        assert S.area(b["p"]) > 0 and all(abs(x) <= h + 0.05 and abs(y) <= h + 0.05 for x, y in b["p"])
    for r in sc["roads"]:
        assert all(abs(x) <= h + 0.05 and abs(y) <= h + 0.05 for x, y in r["p"])
    # (the big park first, its pond after: drawn over it)
    kinds = [a["k"] for a in sc["areas"]]
    assert kinds.index("grass") < kinds.index("water")
    # the same each time (the trees don't move)
    assert S.build_scene(sample(), pt[0], pt[1], home_pt=pt)["trees"] == sc["trees"]


def test_your_house_when_openstreetmap_hasnt_its_address():
    assert S.find_address(address_answer(), "RG41 2AB", "14", LAT0, LON0) is None
    sc = S.build_scene(sample(), LAT0, LON0, home_pt=None)
    assert sc["home"] == {"x": 0.0, "y": 0.0, "id": None, "found": "postcode"}
    # picked on the page: centred on it
    some = sc["buildings"][5]
    sc.update(lat=LAT0, lon=LON0)
    picked = picked_home(sc, some["id"])
    sc2 = S.build_scene(sample(), picked["lat"], picked["lon"], home_id=picked["id"])
    assert sc2["home"]["found"] == "picked" and abs(sc2["home"]["x"]) < 0.2 and abs(sc2["home"]["y"]) < 0.2


def test_address_settings(tmp_path):
    s = AppSettings(str(tmp_path))
    s.update({"postcode": "rg41 2ab", "house_number": "12A"})
    assert s.data["postcode"] == "RG41 2AB" and s.data["house_number"] == "12A"
    s.update({"picked": {"id": 5, "lat": 51.4, "lon": -0.85}})
    assert s.data["picked"]["id"] == 5
    s.update({"house_number": "14"})
    assert s.data["picked"] is None  # (a new address: the house picked goes)
    for bad in ({"postcode": "nope"}, {"house_number": "<script>"}, {"picked": {"id": "x"}}):
        with pytest.raises(ValueError):
            s.update(bad)
    assert AppSettings(str(tmp_path)).data["house_number"] == "14"


def test_the_saved_map(tmp_path):
    store = SceneStore(str(tmp_path))
    assert not store.fits("RG41 2AB", "12")
    now = datetime.datetime.now(datetime.timezone.utc)
    sc = {"postcode": "RG41 2AB", "number": "12", "made": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "home": {"found": "address", "id": 3}}
    store.save(sc)
    assert SceneStore(str(tmp_path)).fits("RG41 2AB", "12")
    assert not store.fits("RG41 2AB", "14") and not store.fits("RG41 2AB", "12", {"id": 3})
    old = (now - datetime.timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.save({**sc, "made": old})
    assert not store.fits("RG41 2AB", "12")


def test_the_card_is_put_in_place_and_added(tmp_path):
    assert write_card("0.1.0", str(tmp_path)) is None
    text = (tmp_path / "www" / "neighbourhood-view" / "neighbourhood-view-card.js").read_text()
    assert "customElements.define('neighbourhood-view-card'" in text and "'0.1.0'" in text
    assert "isn't mapped" in write_card("0.1.0", str(tmp_path / "missing"))
    calls = []

    def fake(resources):
        async def query(msg):
            calls.append(msg)
            if msg["type"] == "lovelace/resources":
                return resources
            return {}
        return query

    run = lambda c: asyncio.new_event_loop().run_until_complete(c)  # noqa: E731
    assert run(register(fake([]), "0.1.0"))["status"] == "added"
    assert calls[-1] == {"type": "lovelace/resources/create", "res_type": "module", "url": URL + "?v=0.1.0"}
    assert run(register(fake([{"id": "r1", "url": URL + "?v=0.0.9", "type": "module"}]), "0.1.0"))["status"] == "updated"
    assert calls[-1]["resource_id"] == "r1"
    assert run(register(fake([{"id": "r1", "url": URL + "?v=0.1.0", "type": "module"}]), "0.1.0"))["status"] == "ok"

    async def yaml_mode(msg):
        raise RuntimeError("Not supported")
    assert run(register(yaml_mode, "0.1.0"))["status"] == "manual"


def test_ridges_run_along_the_street():
    """A terraced house 5 m wide and 9 m deep on an east-west street: its ridge runs east-west (along
    the street), not front to back as its longer side would have it."""
    def house(x):
        pts = [(x, 10), (x + 5, 10), (x + 5, 19), (x, 19), (x, 10)]
        return {"type": "way", "id": int(x) + 100, "tags": {"building": "terrace"},
                "geometry": [{"lat": S.unproject(px, py, LAT0, LON0)[0], "lon": S.unproject(px, py, LAT0, LON0)[1]} for px, py in pts]}
    road = {"type": "way", "id": 1, "tags": {"highway": "residential"},
            "geometry": [{"lat": S.unproject(px, 0, LAT0, LON0)[0], "lon": S.unproject(px, 0, LAT0, LON0)[1]} for px in (-60, 60)]}
    sc = S.build_scene({"elements": [road, house(0), house(5)]}, LAT0, LON0)
    for b in sc["buildings"]:
        (ax, ay), (bx, by) = b["rect"][0], b["rect"][1]
        assert abs(by - ay) < 0.2 and abs(abs(bx - ax) - 5) < 0.2  # (the ridge east-west, 5 m)
        assert b["rh"] == round(min(4.5, 9 * 0.38), 1)
    # with no street near, along its longer side
    sc = S.build_scene({"elements": [house(0)]}, LAT0, LON0)
    (ax, ay), (bx, by) = sc["buildings"][0]["rect"][:2]
    assert abs(abs(by - ay) - 9) < 0.2
