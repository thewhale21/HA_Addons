"""A made-up neighbourhood in Overpass's form (out geom), for the tests and for looking at the
drawing: a grid of streets with houses along them, a main road, a railway, a park with a pond,
some flats and shops, and a few trees."""
from __future__ import annotations

import math

from src.scene import unproject

LAT0, LON0 = 51.4100, -0.8500


def _geom(pts):
    out = []
    for x, y in pts:
        lat, lon = unproject(x, y, LAT0, LON0)
        out.append({"lat": round(lat, 7), "lon": round(lon, 7)})
    return out


def _rect(cx, cy, w, d, ang=0.0):
    c, s = math.cos(ang), math.sin(ang)
    corners = [(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)]
    pts = [(cx + x * c - y * s, cy + x * s + y * c) for x, y in corners]
    return pts + [pts[0]]


def sample() -> dict:
    els, nid = [], [1000]

    def way(pts, tags):
        nid[0] += 1
        els.append({"type": "way", "id": nid[0], "tags": tags, "geometry": _geom(pts)})
        return nid[0]

    # streets: east-west every 80 m, north-south every 120 m
    for y in range(-320, 321, 80):
        way([(-380, y), (380, y)], {"highway": "residential", "name": f"Street {y}"})
    for x in range(-360, 361, 120):
        way([(x, -380), (x, 380)], {"highway": "residential"})
    way([(-380, 40), (380, 40)], {"highway": "primary", "name": "High Street"})
    way([(-380, 150), (380, 210)], {"railway": "rail"})
    way([(-380, 140), (380, 200)], {"highway": "footway"})
    # a park with a pond and a pitch
    way([(-240, -240), (-120, -240), (-120, -120), (-240, -120), (-240, -240)], {"leisure": "park"})
    way([(-200, -200), (-160, -200), (-170, -170), (-205, -175), (-200, -200)], {"natural": "water"})
    way([(-110, -230), (-20, -230), (-20, -170), (-110, -170), (-110, -230)], {"leisure": "pitch"})
    way([(130, -110), (230, -110), (230, -40), (130, -40), (130, -110)], {"amenity": "parking"})
    # houses along the streets
    for y in range(-320, 320, 80):
        for x in range(-370, 370, 12):
            if -240 <= x <= -20 and -240 <= y <= -120:
                continue
            if any(abs(x - sx) < 10 for sx in range(-360, 361, 120)):
                continue
            for side, off in ((1, 16), (-1, -16)):
                yy = y + off
                if 120 < yy < 230 or (130 <= x <= 230 and -110 <= yy <= -40):
                    continue
                tags = {"building": "house" if (x // 12) % 3 else "semidetached_house"}
                if x == -10 and y == -80 and side == 1:
                    tags.update({"addr:housenumber": "12", "addr:postcode": "RG41 2AB"})
                way(_rect(x + 6, yy, 8, 10), tags)
    # flats, shops, a warehouse, a station
    way(_rect(60, 70, 40, 18), {"building": "apartments", "building:levels": "5"})
    way(_rect(-60, 70, 50, 16), {"building": "retail"})
    way(_rect(260, 120, 70, 40, 0.08), {"building": "warehouse"})
    way(_rect(0, 180, 60, 14, 0.08), {"building": "train_station"})
    # a church, a school, a pub (a point in its building), a river off the edge, and street furniture
    way(_rect(137, -96, 20, 10), {"building": "church", "amenity": "place_of_worship"})
    way(_rect(137, -56, 20, 12), {"building": "school"})
    way(_rect(-150, 98, 14, 10), {"building": "yes"})
    way([(-380, -20), (-200, -30), (-130, -100)], {"waterway": "river"})

    def node(x, y, tags):
        nid[0] += 1
        la, lo = unproject(x, y, LAT0, LON0)
        els.append({"type": "node", "id": nid[0], "lat": la, "lon": lo, "tags": tags})
    node(-150, 98, {"amenity": "pub", "name": "The Crown"})
    node(30, -86, {"highway": "bus_stop"})
    node(-150, -118, {"amenity": "bench"})
    node(70, -84, {"amenity": "post_box"})
    els.append({"type": "node", "id": 9, "lat": unproject(30, -60, LAT0, LON0)[0],
                "lon": unproject(30, -60, LAT0, LON0)[1], "tags": {"natural": "tree"}})
    return {"elements": els}


def address_answer() -> dict:
    """Overpass's answer to address_query: two number 12s, one in another postcode."""
    lat, lon = unproject(-4, -64, LAT0, LON0)
    lat2, lon2 = unproject(100, 100, LAT0, LON0)
    return {"elements": [
        {"type": "way", "id": 1, "center": {"lat": lat2, "lon": lon2}, "tags": {"addr:housenumber": "12", "addr:postcode": "RG41 9ZZ"}},
        {"type": "way", "id": 2, "center": {"lat": lat, "lon": lon}, "tags": {"addr:housenumber": "12", "addr:postcode": "RG412AB"}},
    ]}
