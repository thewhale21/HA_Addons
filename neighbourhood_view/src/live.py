"""What's happening now, drawn over the map: the weather, who's home, and whether it's night
(Home Assistant's sun). Pure: built from the entities' states (src/ha_link.py) for the add-on's
page; the dashboard card builds the same from Home Assistant's states itself
(liveFrom() in static/neighbourhood-view-card.js), from the entities in entities()."""
from __future__ import annotations

import datetime
from typing import Optional

from src.ha_link import ENTITY_KEYS


ENERGY_KEYS = {"solar": "solar_entity", "car": "car_entity", "heat": "heat_pump_entity"}
HOUSE_KEYS = {"bins": "bins_entity", "door": "door_entity", "garage": "garage_entity", "lights": "garden_lights_entity"}
OPEN_WORDS = {"on", "open", "opening", "unlocked", "unlocking", "true"}
EVENING = 18  # bins go out the evening before
ON_WORDS = {"on", "charging", "heating", "heat", "cooling", "cool", "running", "true", "active", "producing", "heat_pump", "eco", "performance"}


def entities(settings: dict) -> dict:
    """The entities the map follows: {"weather": entity or "", "people": [entity, ...], "sun": "sun.sun",
    "energy": {"solar", "car", "heat"}: entity or ""}."""
    people = [settings.get(k) for k in sorted(ENTITY_KEYS) if k.startswith("person_") and settings.get(k)]
    return {"weather": settings.get("weather_entity") or "", "people": people, "sun": "sun.sun",
            "energy": {k: settings.get(v) or "" for k, v in ENERGY_KEYS.items()},
            "house": {k: settings.get(v) or "" for k, v in HOUSE_KEYS.items()}}


def bin_day(st: Optional[dict], now: Optional[datetime.datetime] = None) -> bool:
    """Whether the bins are out: a bin-collection entity saying it's today (on, "today", 0 days, or
    today's date), or tomorrow from EVENING (1 day, "tomorrow", tomorrow's date); a calendar's
    event on now, or starting today. The same as binDay() in the card."""
    if not st:
        return False
    now = now or datetime.datetime.now()
    s = str(st.get("state") or "").strip().lower()
    a = st.get("attributes") or {}
    late = now.hour >= EVENING
    today, tomorrow = now.date().isoformat(), (now.date() + datetime.timedelta(days=1)).isoformat()
    if s in ("on", "true", "today"):
        return True
    if s == "tomorrow":
        return late
    try:
        days = float(s)
        return days == 0 or (days == 1 and late)
    except ValueError:
        pass
    for v in (s, str(a.get("start_time") or "").lower()):
        if v[:10] == today or (late and v[:10] == tomorrow):
            return True
    return False


def is_open(st: Optional[dict]) -> bool:
    return bool(st) and str(st.get("state") or "").lower() in OPEN_WORDS


def active(st: Optional[dict]) -> bool:
    """Whether an energy entity says it's going: on / charging / heating..., a climate entity heating
    or cooling, or a power over a little (20 W, or 0.02 kW)."""
    if not st:
        return False
    a = st.get("attributes") or {}
    if a.get("hvac_action") is not None:  # (a thermostat: what it's doing, not its mode)
        return str(a.get("hvac_action")).lower() in ("heating", "cooling", "defrosting", "preheating")
    s = str(st.get("state") or "").lower()
    if s in ON_WORDS:
        return True
    try:
        v = float(s)
    except ValueError:
        return False
    unit = str(a.get("unit_of_measurement") or "").lower()
    return v > (0.02 if unit in ("kw", "kwh") else 20)


def _initials(name: str) -> str:
    parts = [p for p in str(name or "").replace("_", " ").split() if p]
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


def compute(settings: dict, states: dict) -> dict:
    """{"night": bool or None (no sun), "weather": {"entity", "state", "temperature", "unit"} or None,
    "people": [{"entity_id", "name", "initials", "picture", "state", "home", "lat", "lon"}]}
    (lat, lon: where they are, if their tracker says: drawn there when it's on one of the maps)"""
    ents = entities(settings)
    sun = states.get(ents["sun"]) or {}
    night = None if not sun.get("state") else sun.get("state") == "below_horizon"
    weather: Optional[dict] = None
    if ents["weather"]:
        st = states.get(ents["weather"]) or {}
        a = st.get("attributes") or {}
        weather = {"entity": ents["weather"], "state": st.get("state"), "temperature": a.get("temperature"),
                   "unit": a.get("temperature_unit") or "°C"}
    people = []
    for e in ents["people"]:
        st = states.get(e) or {}
        a = st.get("attributes") or {}
        name = a.get("friendly_name") or e.split(".", 1)[-1].replace("_", " ").title()
        state = st.get("state")
        people.append({"entity_id": e, "name": name, "initials": _initials(name), "picture": a.get("entity_picture"),
                       "state": state, "home": state == "home", "lat": a.get("latitude"), "lon": a.get("longitude")})
    # the sun: where it is (for the shadows, and a golden light near sunrise and sunset)
    sa = sun.get("attributes") or {}
    sun_at = None
    if sa.get("azimuth") is not None and sa.get("elevation") is not None:
        sun_at = {"az": round(float(sa["azimuth"]) / 5) * 5, "el": round(float(sa["elevation"]))}
    en = ents.get("energy") or {}
    energy = {"solar": active(states.get(en.get("solar"))) if en.get("solar") else None,
              "car": bool(en.get("car")), "charging": active(states.get(en.get("car"))) if en.get("car") else False,
              "heat": active(states.get(en.get("heat"))) if en.get("heat") else None}
    ho = ents.get("house") or {}
    house = {"bins": bin_day(states.get(ho["bins"])) if ho.get("bins") else None,
             "door": is_open(states.get(ho.get("door"))) if ho.get("door") else False,
             "garage": is_open(states.get(ho.get("garage"))) if ho.get("garage") else None,
             "lights": is_open(states.get(ho.get("lights"))) if ho.get("lights") else False}
    return {"night": night, "weather": weather, "people": people, "sun": sun_at, "energy": energy, "house": house}
