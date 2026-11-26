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
     "water": [{"w", "p"}], "trees": [[x, y, size]]}
"""
from __future__ import annotations

import math
import re
from typing import Optional

HALF = 250.0  # metres each way from your home: a 500 m square
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
        off = r["w"] / 2 - 1.3
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


def build_scene(osm: dict, lat0: float, lon0: float, home_pt: Optional[tuple] = None,
                home_id: Optional[int] = None, half: float = HALF) -> dict:
    """The scene (see the top of this file) from Overpass's answer (out geom), centred on (lat0, lon0).
    Your home: the building with OpenStreetMap id home_id, else the one at home_pt (lat, lon) or
    nearest it (within 30 m)."""
    buildings, roads, rails, areas, water, trees = [], [], [], [], [], []
    tree_areas = []
    for el in (osm or {}).get("elements") or []:
        tags = el.get("tags") or {}
        t = el.get("type")
        if t == "node":
            if tags.get("natural") == "tree" and "lat" in el:
                x, y = project(el["lat"], el["lon"], lat0, lon0)
                if abs(x) <= half and abs(y) <= half:
                    trees.append([round(x, 1), round(y, 1), round(0.8 + 0.8 * _hash01(x, y, 8), 2)])
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
    home = pick_home(buildings, lat0, lon0, home_pt, home_id)
    return {"v": 1, "half": half, "home": home, "buildings": buildings, "roads": roads, "rails": rails,
            "areas": areas, "water": water, "trees": trees[:4000], "cars": cars}


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
