"""The drawing's data: OpenStreetMap's buildings, roads, railways, green areas, water and trees
around your home, turned into a small "scene" the page and the dashboard card draw
(src/static/neighbourhood-view-card.js).

Everything here is pure (no I/O): src/places.py fetches the OpenStreetMap data (Overpass) and
the postcode's location, and hands them to build_scene().

The scene, in metres from your home (x east, y north), clipped to a square HALF metres each way:

    {"v": 1, "half": 250, "home": {"x", "y", "id", "found"},
     "buildings": [{"id", "k" (kind), "p" [[x, y], ...] (anticlockwise), "h" (wall height),
                    "r": "flat" | "gable", "rect" (gable: [[x, y]] x4, the long side first), "rh" (roof height)}],
     "roads": [{"k", "w" (width), "p"}], "rails": [{"k", "w", "p"}], "areas": [{"k", "p"}],
     "water": [{"w", "p"}], "trees": [[x, y, size]], "cars": [[x, y, angle, colour]],
     "plots": [{"id", "c", "u", "n", "hl", "w", "hf", "hb", "f", "b"}] (houses' gardens: see _plots),
     "poi": [[x, y, kind]] (bus_stop, bench, post_box, bin: OpenStreetMap's)}

A building may also have "lm": "church" | "school" | "pub" (a landmark, drawn as one).
SCENE_V goes up when the scene gains something: saved maps older than it are made again.
"""
from __future__ import annotations

import math
import re
from typing import Optional

SCENE_V = 3  # 2: gardens (plots), landmarks (lm), street furniture (poi); 3: gardens not overlapping, cars at the kerb
HALF = 150.0  # metres each way from your home (Settings › Address › Map size): a 300 m square by default
EARTH_R = 6371008.8

# --- buildings -------------------------------------------------------------------------------

HOUSE_TYPES = {"house", "detached", "semidetached_house", "semi", "terrace", "bungalow", "cabin", "farm", "static_caravan"}
FLAT_TYPES = {"apartments", "flats", "dormitory", "hotel"}
COMMERCIAL_TYPES = {"commercial", "retail", "office", "supermarket", "kiosk", "shop", "bank"}
INDUSTRIAL_TYPES = {"industrial", "warehouse", "factory", "manufacture", "storage_tank", "hangar"}
SMALL_TYPES = {"garage", "garages", "shed", "carport", "roof", "hut", "greenhouse", "allotment_house", "toilets", "service"}
CIVIC_TYPES = {"school", "college", "university", "hospital", "church", "chapel", "mosque", "temple", "synagogue",
               "public", "civic", "government", "train_station", "transportation", "fire_station", "police",
               "library", "community_centre", "sports_hall", "sports_centre", "stadium"}
HEIGHTS = {"house": 6.0, "flats": 12.0, "commercial": 8.0, "industrial": 8.5, "small": 2.8, "civic": 10.0, "large": 9.0}
HOUSE_MAX_AREA = 220.0  # m²: "yes"/"residential" buildings up to this are drawn as houses (pitched roofs)
LEVEL_M = 3.0

# --- roads, rails, areas ---------------------------------------------------------------------

ROAD_WIDTHS = {"motorway": 16, "trunk": 13, "primary": 11, "secondary": 9.5, "tertiary": 8.5,
               "motorway_link": 8, "trunk_link": 8, "primary_link": 7, "secondary_link": 7, "tertiary_link": 7,
               "residential": 7, "unclassified": 7, "living_street": 6, "road": 6, "service": 4.5,
               "pedestrian": 4, "busway": 6}
PATH_TYPES = {"footway", "path", "cycleway", "steps", "bridleway", "track", "corridor"}
RAIL_TYPES = {"rail": 4.5, "light_rail": 4, "subway": 4, "narrow_gauge": 3, "tram": 2.5, "preserved": 3}
GRASS = {"grass", "meadow", "village_green", "recreation_ground", "park", "garden", "playground", "dog_park",
         "cemetery", "grave_yard", "allotments", "farmland", "orchard", "common", "nature_reserve", "golf_course",
         "greenfield", "plant_nursery", "flowerbed"}
WOOD = {"forest", "wood", "scrub", "heath"}
WATER = {"water", "reservoir", "basin", "riverbank", "pond", "swimming_pool"}
PITCH = {"pitch", "track", "sports_centre"}
PAVED = {"parking", "garages", "railway", "platform", "marketplace", "bus_station"}
YARD = {"retail", "commercial", "industrial", "construction", "brownfield", "depot", "fuel"}  # (not lawn: hard standing)
WATERWAY_WIDTHS = {"river": 10, "canal": 8, "stream": 2.5, "drain": 1.5, "ditch": 1.5}
TREE_SPACING = {"wood": 9.0, "grass": 26.0}  # synthetic trees in woods and parks, about one per this many m
STREET_TREE_EVERY = 15.0  # ...and along residential streets: a place for one this often on each side
STREET_TREE_CHANCE = 0.4  # ...with a tree in about this many of them
GARDEN_TREE_EVERY = 16.0  # trees in gardens: a place for one about this often...
GARDEN_TREE_CHANCE = 0.33  # ...with a tree in about this many (not on a road, pavement, building or yard)


# --- geometry ---------------------------------------------------------------------------------

def project(lat: float, lon: float, lat0: float, lon0: float) -> tuple:
    """A point in metres from (lat0, lon0): x east, y north (good to a few cm over a few km)."""
    return (math.radians(lon - lon0) * EARTH_R * math.cos(math.radians(lat0)),
            math.radians(lat - lat0) * EARTH_R)


def unproject(x: float, y: float, lat0: float, lon0: float) -> tuple:
    """project() back: (lat, lon) of a point x, y metres from (lat0, lon0)."""
    return (lat0 + math.degrees(y / EARTH_R), lon0 + math.degrees(x / (EARTH_R * math.cos(math.radians(lat0)))))


def area(poly: list) -> float:
    """Signed area (positive: anticlockwise)."""
    s = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return s / 2


def anticlockwise(poly: list) -> list:
    return poly if area(poly) >= 0 else poly[::-1]


def centroid(poly: list) -> tuple:
    a = area(poly)
    if abs(a) < 1e-9:
        return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
    cx = cy = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        f = x1 * y2 - x2 * y1
        cx += (x1 + x2) * f
        cy += (y1 + y2) * f
    return (cx / (6 * a), cy / (6 * a))


def inside(pt: tuple, poly: list) -> bool:
    """Whether the point is inside the polygon (ray casting)."""
    x, y = pt
    hit = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def clip_polygon(poly: list, half: float) -> list:
    """The polygon clipped to the square -half..half (Sutherland–Hodgman); [] if none of it's in it."""
    def clip(pts, inside_fn, cross):
        out = []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            if inside_fn(cur):
                if not inside_fn(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside_fn(prev):
                out.append(cross(prev, cur))
        return out

    def at_x(xv):
        return lambda p, q: (xv, p[1] + (q[1] - p[1]) * (xv - p[0]) / (q[0] - p[0]))

    def at_y(yv):
        return lambda p, q: (p[0] + (q[0] - p[0]) * (yv - p[1]) / (q[1] - p[1]), yv)

    pts = list(poly)
    for inside_fn, cross in ((lambda p: p[0] >= -half, at_x(-half)), (lambda p: p[0] <= half, at_x(half)),
                             (lambda p: p[1] >= -half, at_y(-half)), (lambda p: p[1] <= half, at_y(half))):
        if not pts:
            return []
        pts = clip(pts, inside_fn, cross)
    return pts if len(pts) >= 3 else []


def clip_line(line: list, half: float) -> list:
    """The polyline clipped to the square: the runs of it inside, [[(x, y), ...], ...] (Liang–Barsky)."""
    runs, cur = [], []
    for (x1, y1), (x2, y2) in zip(line, line[1:]):
        dx, dy = x2 - x1, y2 - y1
        t0, t1, ok = 0.0, 1.0, True
        for p, q in ((-dx, x1 + half), (dx, half - x1), (-dy, y1 + half), (dy, half - y1)):
            if p == 0:
                if q < 0:
                    ok = False
                    break
                continue
            r = q / p
            if p < 0:
                t0 = max(t0, r)
            else:
                t1 = min(t1, r)
            if t0 > t1:
                ok = False
                break
        if not ok:
            if cur:
                runs.append(cur)
                cur = []
            continue
        a = (x1 + t0 * dx, y1 + t0 * dy)
        b = (x1 + t1 * dx, y1 + t1 * dy)
        if not cur:
            cur = [a]
        elif cur[-1] != a:
            runs.append(cur)
            cur = [a]
        cur.append(b)
        if t1 < 1.0:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return [r for r in runs if len(r) >= 2]


def min_rect(poly: list) -> list:
    """The smallest rectangle around the polygon, its corners anticlockwise with the long side
    first (corners 0→1): a house's pitched roof runs along it."""
    best = None
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        ln = math.hypot(x2 - x1, y2 - y1)
        if ln < 1e-6:
            continue
        ux, uy = (x2 - x1) / ln, (y2 - y1) / ln
        us = [px * ux + py * uy for px, py in poly]
        vs = [-px * uy + py * ux for px, py in poly]
        a = (max(us) - min(us)) * (max(vs) - min(vs))
        if best is None or a < best[0]:
            best = (a, ux, uy, min(us), max(us), min(vs), max(vs))
    if best is None:
        return []
    _, ux, uy, u0, u1, v0, v1 = best
    pt = lambda u, v: (u * ux - v * uy, u * uy + v * ux)  # noqa: E731
    corners = [pt(u0, v0), pt(u1, v0), pt(u1, v1), pt(u0, v1)]  # anticlockwise; 0→1 along u
    if (u1 - u0) < (v1 - v0):  # the long side first
        corners = corners[1:] + corners[:1]
    return corners


def _r(pts) -> list:
    return [[round(x, 1), round(y, 1)] for x, y in pts]


def _num(text) -> Optional[float]:
    m = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)", str(text or ""))
    return float(m.group(1)) if m else None


# --- OpenStreetMap ----------------------------------------------------------------------------

def overpass_query(lat: float, lon: float, half: float = HALF) -> str:
    """The Overpass query for everything drawn, a little past the square (so roads reach its edge)."""
    r = int(half * 1.5)
    a = f"(around:{r},{lat:.6f},{lon:.6f})"
    return (f'[out:json][timeout:60];('
            f'way["building"]{a};relation["building"]["type"="multipolygon"]{a};'
            f'way["highway"]{a};way["railway"]{a};'
            f'way["landuse"]{a};way["leisure"]{a};way["natural"]{a};way["amenity"="parking"]{a};'
            f'relation["landuse"]["type"="multipolygon"]{a};relation["leisure"]["type"="multipolygon"]{a};'
            f'relation["natural"]["type"="multipolygon"]{a};'
            f'way["waterway"]{a};node["natural"="tree"]{a};'
            f'node["highway"="bus_stop"]{a};node["amenity"~"^(bench|post_box|waste_basket|pub|bar|place_of_worship|school)$"]{a};'
            f');out geom;')


def address_query(lat: float, lon: float, number: str, radius: int = 400) -> str:
    """The Overpass query for the places with your house number near the postcode."""
    num = str(number).replace('"', "")
    return (f'[out:json][timeout:30];nwr["addr:housenumber"="{num}"](around:{radius},{lat:.6f},{lon:.6f});'
            f'out center tags;')


def _rings(el: dict, lat0: float, lon0: float) -> list:
    """The outer rings of a way or multipolygon relation, in metres."""
    def pts(geom):
        return [project(g["lat"], g["lon"], lat0, lon0) for g in geom or [] if g]

    if el.get("type") == "way":
        p = pts(el.get("geometry"))
        if len(p) >= 4 and p[0] == p[-1]:
            return [p[:-1]]
        return []
    if el.get("type") == "relation":
        parts = [pts(m.get("geometry")) for m in el.get("members") or [] if m.get("role") in ("outer", "")]
        return [r[:-1] for r in _join(parts) if len(r) >= 4]
    return []


def _join(parts: list) -> list:
    """Ways joined end to end into closed rings."""
    parts = [p for p in parts if len(p) >= 2]
    rings = []
    while parts:
        ring = list(parts.pop(0))
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, p in enumerate(parts):
                if p[0] == ring[-1]:
                    ring += p[1:]
                elif p[-1] == ring[-1]:
                    ring += p[::-1][1:]
                elif p[-1] == ring[0]:
                    ring = p[:-1] + ring
                elif p[0] == ring[0]:
                    ring = p[::-1][:-1] + ring
                else:
                    continue
                parts.pop(i)
                changed = True
                break
        if ring[0] == ring[-1]:
            rings.append(ring)
    return rings


def building_kind(tags: dict, a: float) -> str:
    b = str(tags.get("building") or "yes").lower()
    if b in HOUSE_TYPES:
        return "house"
    if b in FLAT_TYPES:
        return "flats"
    if b in COMMERCIAL_TYPES or tags.get("shop"):
        return "commercial"
    if b in INDUSTRIAL_TYPES:
        return "industrial"
    if b in SMALL_TYPES:
        return "small"
    if b in CIVIC_TYPES or tags.get("amenity") in ("school", "place_of_worship", "hospital"):
        return "civic"
    if a < 25:
        return "small"
    return "house" if a <= HOUSE_MAX_AREA else "large"


CHURCH = {"church", "chapel", "cathedral"}


def landmark(tags: dict) -> Optional[str]:
    """What a building's known for, drawn as one: a church (a spire), a school (a flag and a
    playground) or a pub (its sign)."""
    b, am = str(tags.get("building") or "").lower(), str(tags.get("amenity") or "").lower()
    if b in CHURCH or am == "place_of_worship" and tags.get("religion") in (None, "christian"):
        return "church"
    if b == "school" or am in ("school", "college"):
        return "school"
    if b == "pub" or am in ("pub", "bar"):
        return "pub"
    return None


POI_KINDS = {"bus_stop": "bus_stop", "bench": "bench", "post_box": "post_box", "waste_basket": "bin"}


HOUSE_STOREYS = ((0.14, 3.2), (0.86, 5.8), (1.0, 8.4))  # houses with no height: bungalows, 2 and 3 storeys


def building_height(tags: dict, kind: str, bid: int = 0) -> float:
    """Wall height in metres: its height tag (less the roof), else its levels, else by kind (a house:
    mostly 2 storeys, some bungalows and 3 storeys, the same each time for the same building)."""
    h = _num(tags.get("height"))
    roof = _num(tags.get("roof:height")) or 0.0
    if h:
        return max(2.5, h - roof)
    levels = _num(tags.get("building:levels"))
    if levels:
        return max(2.5, levels * LEVEL_M)
    if kind == "house":
        r = _hash01(bid or 0, 7, 6)
        return next(h for p, h in HOUSE_STOREYS if r <= p)
    return HEIGHTS[kind]


def _area_kind(tags: dict) -> Optional[str]:
    vals = {str(tags.get(k) or "").lower() for k in ("landuse", "leisure", "natural", "amenity", "railway", "water")}
    if vals & WATER:
        return "water"
    if vals & WOOD:
        return "wood"
    if vals & PITCH:
        return "pitch"
    if vals & GRASS:
        return "grass"
    if vals & PAVED or tags.get("public_transport") == "platform":
        return "paved"
    if vals & YARD:
        return "yard"
    return None


def _hash01(x: float, y: float, salt: int = 0) -> float:
    """A repeatable number 0..1 for a place (so synthetic trees don't move between plans)."""
    h = (int(x * 7919) * 73856093) ^ (int(y * 6151) * 19349663) ^ (salt * 83492791)
    return ((h & 0xFFFFFFFF) % 10007) / 10007.0


def _scatter(poly: list, spacing: float, avoid: list) -> list:
    """Trees on a jittered grid inside the polygon, not inside a building."""
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    out = []
    y = math.floor(min(ys) / spacing) * spacing
    while y <= max(ys):
        x = math.floor(min(xs) / spacing) * spacing
        while x <= max(xs):
            px = x + (_hash01(x, y, 1) - 0.5) * spacing * 0.8
            py = y + (_hash01(x, y, 2) - 0.5) * spacing * 0.8
            if inside((px, py), poly) and not any(inside((px, py), b) for b in avoid):
                out.append([round(px, 1), round(py, 1), round(0.7 + 1.0 * _hash01(x, y, 3), 2)])
            x += spacing
        y += spacing
    return out


def _garden_trees(roads: list, buildings: list, areas: list, half: float) -> list:
    """Trees in gardens and open ground: a jittered grid over the square, keeping off roads (and
    their pavements), buildings, car parks, yards, water and pitches."""
    cell = 30.0
    grid: dict = {}
    for r in roads:
        pad = r["w"] / 2 + (3.5 if r["k"] != "path" else 1.0)
        for (x1, y1), (x2, y2) in zip(r["p"], r["p"][1:]):
            for gx in range(int(math.floor((min(x1, x2) - pad) / cell)), int(math.floor((max(x1, x2) + pad) / cell)) + 1):
                for gy in range(int(math.floor((min(y1, y2) - pad) / cell)), int(math.floor((max(y1, y2) + pad) / cell)) + 1):
                    grid.setdefault((gx, gy), []).append((x1, y1, x2, y2, pad))
    boxes = [(min(p[0] for p in b) - 1.5, min(p[1] for p in b) - 1.5, max(p[0] for p in b) + 1.5, max(p[1] for p in b) + 1.5)
             for b in buildings]
    bgrid: dict = {}
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        for gx in range(int(math.floor(x0 / cell)), int(math.floor(x1 / cell)) + 1):
            for gy in range(int(math.floor(y0 / cell)), int(math.floor(y1 / cell)) + 1):
                bgrid.setdefault((gx, gy), []).append(i)
    hard = [a["p"] for a in areas if a["k"] in ("paved", "yard", "water", "pitch")]
    hard_boxes = [(min(p[0] for p in a), min(p[1] for p in a), max(p[0] for p in a), max(p[1] for p in a), a) for a in hard]
    out = []
    step = GARDEN_TREE_EVERY
    y = -half + step / 2
    while y < half:
        x = -half + step / 2
        while x < half:
            if _hash01(x, y, 12) < GARDEN_TREE_CHANCE:
                px = x + (_hash01(x, y, 13) - 0.5) * step * 0.9
                py = y + (_hash01(x, y, 14) - 0.5) * step * 0.9
                g = (int(math.floor(px / cell)), int(math.floor(py / cell)))
                ok = not any(bx0 <= px <= bx1 and by0 <= py <= by1 for bx0, by0, bx1, by1 in (boxes[i] for i in bgrid.get(g, ())))
                if ok:
                    for x1, y1, x2, y2, pad in grid.get(g, ()):
                        vx, vy = x2 - x1, y2 - y1
                        ln2 = vx * vx + vy * vy or 1e-9
                        t = max(0.0, min(1.0, ((px - x1) * vx + (py - y1) * vy) / ln2))
                        if math.hypot(x1 + vx * t - px, y1 + vy * t - py) < pad:
                            ok = False
                            break
                if ok and any(x0 <= px <= x1 and y0 <= py <= y1 and inside((px, py), a) for x0, y0, x1, y1, a in hard_boxes):
                    ok = False
                if ok:
                    out.append([round(px, 1), round(py, 1), round(0.6 + 1.1 * _hash01(x, y, 15), 2)])
            x += step
        y += step
    return out


def _street_trees(roads: list, buildings: list, half: float) -> list:
    """Trees along the streets (minor roads), a little back from the kerb, not in a building."""
    boxes = [(min(p[0] for p in b), min(p[1] for p in b), max(p[0] for p in b), max(p[1] for p in b), b) for b in buildings]
    out = []
    for r in roads:
        if r["k"] != "minor":
            continue
        off = r["w"] / 2 + 2.2  # (in the pavement, by its outer edge)
        for (x1, y1), (x2, y2) in zip(r["p"], r["p"][1:]):
            ln = math.hypot(x2 - x1, y2 - y1)
            if ln < 1:
                continue
            ux, uy = (x2 - x1) / ln, (y2 - y1) / ln
            t = STREET_TREE_EVERY / 2
            while t < ln:
                cx, cy = x1 + ux * t, y1 + uy * t
                for side in (1, -1):
                    px, py = cx - uy * off * side, cy + ux * off * side
                    if _hash01(px, py, 4) > STREET_TREE_CHANCE or abs(px) > half - 2 or abs(py) > half - 2:
                        continue
                    if any(bx0 - 1 <= px <= bx1 + 1 and by0 - 1 <= py <= by1 + 1 and inside((px, py), b)
                           for bx0, by0, bx1, by1, b in boxes):
                        continue
                    out.append([round(px, 1), round(py, 1), round(0.6 + 0.8 * _hash01(px, py, 5), 2)])
                t += STREET_TREE_EVERY
    return out


FACE_STREET_M = 40.0  # a house's ridge runs along the street within this distance of it


def _face_streets(buildings: list, roads: list) -> None:
    """Turns each pitched roof so its ridge runs along the nearest street, as British houses' do
    (a terraced or semi-detached house is usually deeper than it is wide, so its longer side would
    put the ridge front to back). With no street near, the ridge stays along the longer side."""
    cell = FACE_STREET_M
    grid: dict = {}
    for r in roads:
        if r["k"] == "path":
            continue
        for (x1, y1), (x2, y2) in zip(r["p"], r["p"][1:]):
            for gx in range(int(math.floor(min(x1, x2) / cell)), int(math.floor(max(x1, x2) / cell)) + 1):
                for gy in range(int(math.floor(min(y1, y2) / cell)), int(math.floor(max(y1, y2) / cell)) + 1):
                    grid.setdefault((gx, gy), []).append((x1, y1, x2, y2))
    for b in buildings:
        if b.get("r") != "gable" or not b.get("rect"):
            continue
        cx, cy = centroid(b["p"])
        gx, gy = int(math.floor(cx / cell)), int(math.floor(cy / cell))
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for x1, y1, x2, y2 in grid.get((gx + dx, gy + dy), ()):
                    vx, vy = x2 - x1, y2 - y1
                    ln2 = vx * vx + vy * vy
                    if ln2 < 1e-6:
                        continue
                    t = max(0.0, min(1.0, ((cx - x1) * vx + (cy - y1) * vy) / ln2))
                    d = math.hypot(x1 + vx * t - cx, y1 + vy * t - cy)
                    if best is None or d < best[0]:
                        best = (d, vx, vy)
        if best is None or best[0] > FACE_STREET_M:
            continue
        rect = b["rect"]
        _, vx, vy = best
        e1 = (rect[1][0] - rect[0][0], rect[1][1] - rect[0][1])
        e2 = (rect[2][0] - rect[1][0], rect[2][1] - rect[1][1])
        along = lambda e: abs(e[0] * vx + e[1] * vy) / ((math.hypot(*e) or 1) * math.hypot(vx, vy))  # noqa: E731
        if along(e2) > along(e1):
            b["rect"] = rect[1:] + rect[:1]  # (the ridge along the street; the span is now the other side)
            span = math.hypot(*e1)
            b["rh"] = round(min(4.5, max(1.5, span * 0.38)), 1)


CAR_EVERY = 9.0  # a place for a parked car this often on each side of a street...
CAR_CHANCE = 0.22  # ...with one in about this many


def _cars(roads: list, buildings: list, half: float) -> list:
    """Cars parked along the kerbs of streets (not near a junction): [[x, y, angle°, colour 0-9]]."""
    seen: dict = {}
    for r in roads:
        if r["k"] in ("minor", "major"):
            for x, y in r["p"]:
                key = (round(x), round(y))
                seen[key] = seen.get(key, 0) + 1
    junctions = [k for k, n in seen.items() if n > 1]
    for r in roads:
        if r["k"] in ("minor", "major"):
            junctions += [(round(r["p"][0][0]), round(r["p"][0][1])), (round(r["p"][-1][0]), round(r["p"][-1][1]))]
    out = []
    for r in roads:
        if r["k"] not in ("minor", "major"):
            continue
        off = r["w"] / 2 - 0.95  # (tucked against the kerb: the traffic passes between them and the middle)
        for (x1, y1), (x2, y2) in zip(r["p"], r["p"][1:]):
            ln = math.hypot(x2 - x1, y2 - y1)
            if ln < 6:
                continue
            ux, uy = (x2 - x1) / ln, (y2 - y1) / ln
            ang = round(math.degrees(math.atan2(uy, ux)))
            t = CAR_EVERY / 2
            while t < ln - 3:
                cx, cy = x1 + ux * t, y1 + uy * t
                for side in (1, -1):
                    px, py = cx - uy * off * side, cy + ux * off * side
                    if _hash01(px, py, 9) > CAR_CHANCE or abs(px) > half - 4 or abs(py) > half - 4:
                        continue
                    if any(math.hypot(px - jx, py - jy) < 14 for jx, jy in junctions):
                        continue
                    out.append([round(px, 1), round(py, 1), ang, int(_hash01(px, py, 10) * 10) % 10])
                t += CAR_EVERY
    return out[:800]


GARDEN_MAX = 30.0  # m: a back garden's longest
GARDEN_NONE = 18.0  # m: ...with nothing behind it


def _plots(buildings: list, roads: list, half: float) -> list:
    """Each house's front and back garden, from where its street is: {"id", "c": its middle,
    "u": along the street, "n": away from the street (to the back), "hl": half its width along the
    street, "hf"/"hb": from its middle to its front / back, "f": the front garden's depth (to the
    pavement), "w": half the plot's width (to half way to the next house), "b": the back garden's (to the next building or road behind: half way to a house
    backing onto it)}. The page draws fences, patios, sheds, driveways, paths... on them."""
    cell = 40.0
    rgrid: dict = {}
    for r in roads:
        if r["k"] == "path":
            continue
        for (x1, y1), (x2, y2) in zip(r["p"], r["p"][1:]):
            for gx in range(int(math.floor(min(x1, x2) / cell)) - 1, int(math.floor(max(x1, x2) / cell)) + 2):
                for gy in range(int(math.floor(min(y1, y2) / cell)) - 1, int(math.floor(max(y1, y2) / cell)) + 2):
                    rgrid.setdefault((gx, gy), []).append((x1, y1, x2, y2, r["w"]))
    bgrid: dict = {}
    for i, b in enumerate(buildings):
        cx, cy = centroid(b["p"])
        bgrid.setdefault((int(math.floor(cx / cell)), int(math.floor(cy / cell))), []).append(i)
    out = []
    for i, b in enumerate(buildings):
        if b.get("r") != "gable" or b.get("k") != "house":
            continue
        cx, cy = centroid(b["p"])
        g = (int(math.floor(cx / cell)), int(math.floor(cy / cell)))
        # the street it faces: in a row of houses (terraces, semis), the row runs along it, and
        # its front's the side with a street nearer; else the nearest street
        pts = []
        for x1, y1, x2, y2, w in rgrid.get(g, ()):
            n = max(1, int(math.hypot(x2 - x1, y2 - y1) / 3))
            pts += [(x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n, w) for k in range(n + 1)]
        if not pts:
            continue
        near = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in bgrid.get((g[0] + dx, g[1] + dy), ()):
                    o = buildings[j]
                    if j == i or o.get("k") != "house":
                        continue
                    ox, oy = centroid(o["p"])
                    dd = math.hypot(ox - cx, oy - cy)
                    if dd < 16 and (near is None or dd < near[0]):
                        near = (dd, ox - cx, oy - cy)
        choice = None
        if near:
            ux, uy = near[1] / near[0], near[2] / near[0]
            for sgn in (1, -1):
                nx, ny = -uy * sgn, ux * sgn
                for px, py, w in pts:
                    s = (px - cx) * nx + (py - cy) * ny
                    if 0 < s < FACE_STREET_M and abs((px - cx) * ux + (py - cy) * uy) <= 12 and (choice is None or s < choice[0]):
                        choice = (s, -nx, -ny, w)  # (n: away from it)
        if choice is None:
            px, py, w = min(pts, key=lambda q: math.hypot(q[0] - cx, q[1] - cy))
            d = math.hypot(px - cx, py - cy)
            if d > FACE_STREET_M or d < 1:
                continue
            choice = (d, (cx - px) / d, (cy - py) / d, w)
        d, nx, ny, w = choice
        ux, uy = -ny, nx
        corners = b.get("rect") or b["p"]
        ls = [(px - cx) * ux + (py - cy) * uy for px, py in corners]
        ss = [(px - cx) * nx + (py - cy) * ny for px, py in corners]
        hl, hf, hb = max(abs(v) for v in ls), -min(ss), max(ss)
        front = d - hf - (w / 2 + 2.8)
        # what's behind: the nearest building or street across the garden's width
        def first_behind(p, q, width):
            """How far behind the house (s past hb) the segment p→q first comes, within |l| <= width; None if not."""
            s1, l1 = (p[0] - cx) * nx + (p[1] - cy) * ny, (p[0] - cx) * ux + (p[1] - cy) * uy
            s2, l2 = (q[0] - cx) * nx + (q[1] - cy) * ny, (q[0] - cx) * ux + (q[1] - cy) * uy
            t0, t1 = 0.0, 1.0
            dl = l2 - l1
            if abs(dl) < 1e-9:
                if abs(l1) > width:
                    return None
            else:
                ta, tb = (-width - l1) / dl, (width - l1) / dl
                t0, t1 = max(t0, min(ta, tb)), min(t1, max(ta, tb))
                if t0 > t1:
                    return None
            sa, sb = s1 + (s2 - s1) * t0, s1 + (s2 - s1) * t1
            best_s = None
            for sv, other in ((sa, sb), (sb, sa)):
                if sv > hb:
                    best_s = sv if best_s is None else min(best_s, sv)
                elif other > hb:
                    best_s = hb + 0.01 if best_s is None else min(best_s, hb + 0.01)
            return None if best_s is None else best_s - hb
        # the plot's half width: to half way to the house next door (along the street), else a little past the house
        pw = hl + 1.5
        if near:
            along = abs(near[1] * ux + near[2] * uy)
            if along > near[0] * 0.8:
                pw = max(hl, min(along / 2, hl + 4))
        back = GARDEN_NONE
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in bgrid.get((g[0] + dx, g[1] + dy), ()):
                    if j == i:
                        continue
                    o = buildings[j]
                    gaps = [first_behind(o["p"][k], o["p"][(k + 1) % len(o["p"])], pw - 0.3) for k in range(len(o["p"]))]
                    gaps = [v for v in gaps if v is not None]
                    if gaps:
                        gap = min(gaps)
                        back = min(back, gap / 2 if o.get("k") == "house" else gap - 0.5)
        for x1, y1, x2, y2, rw in rgrid.get(g, ()):
            v = first_behind((x1, y1), (x2, y2), pw + 2)
            if v is not None:
                back = min(back, v - rw / 2 - 2.8)
        back = min(back, GARDEN_MAX)
        # (kept to the map)
        for k in (back, ):
            ex, ey = cx + nx * (hb + k), cy + ny * (hb + k)
            if abs(ex) > half - 2 or abs(ey) > half - 2:
                back = max(0.0, back - max(abs(ex) - half + 2, abs(ey) - half + 2))
        out.append({"id": b["id"], "c": [round(cx, 1), round(cy, 1)], "u": [round(ux, 3), round(uy, 3)], "n": [round(nx, 3), round(ny, 3)],
                    "hl": round(hl, 1), "w": round(pw, 1), "hf": round(hf, 1), "hb": round(hb, 1), "f": round(max(0.0, min(front, 15.0)), 1),
                    "b": round(max(0.0, back), 1)})
    _no_overlaps(out)
    return out


def _back_rect(p: dict, shrink: float = 0.0) -> list:
    """A plot's back garden as 4 corners (shrunk a little each side, so neighbours touching don't count)."""
    (cx, cy), (ux, uy), (nx, ny) = p["c"], p["u"], p["n"]
    s0, s1, w = p["hb"] + shrink, p["hb"] + p["b"] - shrink, p["w"] - shrink
    return [(cx + nx * s + ux * l, cy + ny * s + uy * l) for s, l in ((s0, -w), (s0, w), (s1, w), (s1, -w))]


def _overlap(a: list, b: list) -> bool:
    """Whether two convex quads overlap (separating axes)."""
    for poly in (a, b):
        for i in range(len(poly)):
            (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
            ax, ay = y1 - y2, x2 - x1
            pa = [ax * x + ay * y for x, y in a]
            pb = [ax * x + ay * y for x, y in b]
            if max(pa) <= min(pb) or max(pb) <= min(pa):
                return False
    return True


def _no_overlaps(plots: list) -> None:
    """Back gardens that overlap (houses at odd angles, round corners) are cut back, the deeper one
    first, until they don't; one cut right back has no garden drawn."""
    cell = 40.0
    grid: dict = {}
    for i, p in enumerate(plots):
        grid.setdefault((int(math.floor(p["c"][0] / cell)), int(math.floor(p["c"][1] / cell))), []).append(i)
    for _ in range(20):
        changed = False
        for i, p in enumerate(plots):
            if p["b"] < 2:
                continue
            gx, gy = int(math.floor(p["c"][0] / cell)), int(math.floor(p["c"][1] / cell))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in grid.get((gx + dx, gy + dy), ()):
                        q = plots[j]
                        if j <= i or q["b"] < 2 or p["b"] < 2:
                            continue
                        if _overlap(_back_rect(p, 0.4), _back_rect(q, 0.4)):
                            big = p if p["b"] >= q["b"] else q
                            big["b"] = round(big["b"] * 0.75, 1) if big["b"] * 0.75 >= 2 else 0.0
                            changed = True
        if not changed:
            break


def build_scene(osm: dict, lat0: float, lon0: float, home_pt: Optional[tuple] = None,
                home_id: Optional[int] = None, half: float = HALF) -> dict:
    """The scene (see the top of this file) from Overpass's answer (out geom), centred on (lat0, lon0).
    Your home: the building with OpenStreetMap id home_id, else the one at home_pt (lat, lon) or
    nearest it (within 30 m)."""
    buildings, roads, rails, areas, water, trees, poi, lm_nodes = [], [], [], [], [], [], [], []
    tree_areas = []
    for el in (osm or {}).get("elements") or []:
        tags = el.get("tags") or {}
        t = el.get("type")
        if t == "node":
            if "lat" not in el:
                continue
            x, y = project(el["lat"], el["lon"], lat0, lon0)
            if abs(x) > half or abs(y) > half:
                continue
            if tags.get("natural") == "tree":
                trees.append([round(x, 1), round(y, 1), round(0.8 + 0.8 * _hash01(x, y, 8), 2)])
            kind = POI_KINDS.get(tags.get("highway")) or POI_KINDS.get(tags.get("amenity"))
            if kind:
                poi.append([round(x, 1), round(y, 1), kind])
            lm = landmark(tags) if tags.get("amenity") else None
            if lm:
                lm_nodes.append((x, y, lm))
            continue
        if tags.get("building") and tags.get("building") != "no" and tags.get("location") != "underground":
            for ring in _rings(el, lat0, lon0):
                ring = anticlockwise(ring)
                a = area(ring)
                if a < 4:
                    continue
                clipped = clip_polygon(ring, half)
                if not clipped:
                    continue
                kind = building_kind(tags, a)
                b = {"id": el.get("id"), "k": kind, "p": _r(anticlockwise(clipped)), "h": round(building_height(tags, kind, el.get("id") or 0), 1)}
                lm = landmark(tags)
                if lm:
                    b["lm"] = lm
                    if kind == "house":  # (a pub or chapel tagged as a house: drawn as a building)
                        b["k"] = "civic" if lm != "pub" else "commercial"
                shape = str(tags.get("roof:shape") or "").lower()
                if kind == "house" and shape not in ("flat",) and len(clipped) == len(ring):
                    rect = min_rect(ring)
                    if rect:
                        short = math.hypot(rect[2][0] - rect[1][0], rect[2][1] - rect[1][1])
                        b.update(r="gable", rect=_r(rect), rh=round(min(4.5, max(1.5, short * 0.38)), 1))
                b.setdefault("r", "flat")
                buildings.append(b)
            continue
        if t != "way" and t != "relation":
            continue
        hw = tags.get("highway")
        if hw and t == "way" and tags.get("area") != "yes" and tags.get("tunnel") not in ("yes", "building_passage"):
            kind = "path" if hw in PATH_TYPES else hw if hw in ROAD_WIDTHS else None
            if kind:
                w = 2.0 if kind == "path" else float(ROAD_WIDTHS[kind])
                lanes = _num(tags.get("lanes"))
                if lanes and kind != "path":
                    w = max(w, lanes * 3.2)
                line = [project(g["lat"], g["lon"], lat0, lon0) for g in el.get("geometry") or []]
                for run in clip_line(line, half):
                    roads.append({"k": "path" if kind == "path" else ("major" if w >= 9.5 else "minor" if kind != "service" else "service"),
                                  "w": round(w, 1), "p": _r(run)})
            continue
        rw = tags.get("railway")
        if rw in RAIL_TYPES and t == "way" and tags.get("tunnel") != "yes":
            line = [project(g["lat"], g["lon"], lat0, lon0) for g in el.get("geometry") or []]
            for run in clip_line(line, half):
                rails.append({"k": "tram" if rw == "tram" else "rail", "w": RAIL_TYPES[rw], "p": _r(run)})
            continue
        ww = tags.get("waterway")
        if ww in WATERWAY_WIDTHS and t == "way" and tags.get("tunnel") != "culvert":
            line = [project(g["lat"], g["lon"], lat0, lon0) for g in el.get("geometry") or []]
            for run in clip_line(line, half):
                water.append({"w": WATERWAY_WIDTHS[ww], "p": _r(run)})
            continue
        kind = _area_kind(tags)
        if kind:
            for ring in _rings(el, lat0, lon0):
                clipped = clip_polygon(anticlockwise(ring), half)
                if clipped:
                    areas.append({"k": kind, "p": _r(anticlockwise(clipped)), "_a": abs(area(clipped))})
                    if kind in TREE_SPACING:
                        tree_areas.append((kind, clipped))
    # (big areas first, so a park's pond or pitch is drawn over it)
    areas.sort(key=lambda a: -a.pop("_a"))
    foot = [b["p"] for b in buildings]
    for kind, poly in tree_areas:
        trees += _scatter(poly, TREE_SPACING[kind], foot)
    trees += _street_trees(roads, foot, half)
    trees += _garden_trees(roads, foot, areas, half)
    cars = _cars(roads, foot, half)
    _face_streets(buildings, roads)
    # (a pub, church or school mapped as a point: the building it's in)
    for x, y, lm in lm_nodes:
        for b in buildings:
            if "lm" not in b and inside((x, y), b["p"]):
                b["lm"] = lm
                if b["k"] == "house":
                    b.pop("rect", None)
                    b["r"], b["k"] = "flat", ("commercial" if lm == "pub" else "civic")
                break
    home = pick_home(buildings, lat0, lon0, home_pt, home_id)
    plots = _plots(buildings, roads, half)
    # (gardens' trees: off the patios and out of the sheds' corner; kept to the lawn)
    return {"v": SCENE_V, "half": half, "home": home, "buildings": buildings, "roads": roads, "rails": rails,
            "areas": areas, "water": water, "trees": trees[:4000], "cars": cars, "plots": plots, "poi": poi[:400]}


def pick_home(buildings: list, lat0: float, lon0: float, home_pt: Optional[tuple], home_id: Optional[int]) -> dict:
    """Your home: {"x", "y", "id" (the building's, or None), "found": "picked" (chosen on the page),
    "address" (OpenStreetMap has your address), "nearest" (a building near it) or "postcode" (none:
    the postcode's centre)}."""
    if home_id is not None:
        for b in buildings:
            if b["id"] == home_id:
                x, y = centroid(b["p"])
                return {"x": round(x, 1), "y": round(y, 1), "id": home_id, "found": "picked"}
    if home_pt is None:
        return {"x": 0.0, "y": 0.0, "id": None, "found": "postcode"}
    px, py = project(home_pt[0], home_pt[1], lat0, lon0)
    best, dist = None, 30.0
    for b in buildings:
        if inside((px, py), b["p"]):
            best, dist = b, 0.0
            break
        cx, cy = centroid(b["p"])
        d = math.hypot(cx - px, cy - py)
        if d < dist:
            best, dist = b, d
    if best is None:
        return {"x": round(px, 1), "y": round(py, 1), "id": None, "found": "postcode"}
    x, y = centroid(best["p"])
    return {"x": round(x, 1), "y": round(y, 1), "id": best["id"], "found": "address" if dist == 0 else "nearest"}


def find_address(osm: dict, postcode: str, number: str, lat0: float, lon0: float) -> Optional[tuple]:
    """Your house in Overpass's answer to address_query: (lat, lon) of the place with your house number
    and postcode, else None (OpenStreetMap doesn't have it: the page asks you to pick it)."""
    want = norm_postcode(postcode)
    best = None
    for el in (osm or {}).get("elements") or []:
        tags = el.get("tags") or {}
        if str(tags.get("addr:housenumber") or "").strip().lower() != str(number).strip().lower():
            continue
        if norm_postcode(tags.get("addr:postcode") or "") != want:
            continue
        pt = (el["lat"], el["lon"]) if "lat" in el else ((el.get("center") or {}).get("lat"), (el.get("center") or {}).get("lon"))
        if pt[0] is None:
            continue
        d = math.hypot(*project(pt[0], pt[1], lat0, lon0))
        if best is None or d < best[0]:
            best = (d, pt)
    return best[1] if best else None


POSTCODE_RE = re.compile(r"^([A-Z]{1,2}[0-9][A-Z0-9]?)\s*([0-9][A-Z]{2})$")


def norm_postcode(text: str) -> str:
    """A UK postcode in capitals with one space (e.g. "rg412ab" -> "RG41 2AB"), or "" if it isn't one."""
    m = POSTCODE_RE.match(re.sub(r"\s+", "", str(text or "").upper()))
    return f"{m.group(1)} {m.group(2)}" if m else ""
