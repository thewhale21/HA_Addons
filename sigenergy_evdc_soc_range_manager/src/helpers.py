"""Makes the Home Assistant helpers the add-on needs, the first time it
connects: the high and low SoC limits, the car's battery capacity and a V2X
mode select (V2X, Solar Surplus, Fast Charging). Each is only made when its picker on the Settings tab is
empty, so you can point any of them at a helper you already have instead.

They're ordinary helpers (Settings › Devices & services › Helpers): use them
on dashboards and in automations, and the web page's limit sliders set them.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# key -> (helper type, what to make)
HELPERS = {
    "soc_high": ("input_number", {
        "name": "EVDC SoC Range High Limit", "min": 21, "max": 99, "step": 1, "mode": "slider",
        "unit_of_measurement": "%", "icon": "mdi:battery-arrow-up", "initial": 80}),
    "soc_low": ("input_number", {
        "name": "EVDC SoC Range Low Limit", "min": 20, "max": 98, "step": 1, "mode": "slider",
        "unit_of_measurement": "%", "icon": "mdi:battery-arrow-down", "initial": 40}),
    "capacity": ("input_number", {
        "name": "EVDC SoC Range Vehicle Battery Capacity", "min": 0, "max": 200, "step": 0.1, "mode": "box",
        "unit_of_measurement": "kWh", "icon": "mdi:car-battery", "initial": 0}),
    "v2x_mode": ("input_select", {
        "name": "SigEnergy EVDC Charging Mode", "options": ["V2X", "Solar Surplus", "Fast Charging"],
        "initial": "V2X", "icon": "mdi:ev-station"}),
}
# Helpers a hand-made V2X automation may already have: a new helper starts at their value
KNOWN_VALUES = {
    "soc_high": "input_number.v2x_cut_off_threshold_high",
    "soc_low": "input_number.v2x_cut_off_threshold",
    "capacity": "input_number.vehicle_max_capacity",
}


CAPACITY_MIN_KWH, CAPACITY_MAX_KWH = 1.0, 200.0


def capacity_target(entity_id: str, value) -> tuple:
    """(domain, kWh) to set the car's battery capacity from the web page (raises ValueError).
    The domain is None when it can't be set where it comes from (nothing picked, or a sensor):
    the add-on's own capacity helper is made (or found) and used instead."""
    try:
        kwh = float(value)
    except (TypeError, ValueError):
        raise ValueError("Give the battery capacity in kWh") from None
    if not CAPACITY_MIN_KWH <= kwh <= CAPACITY_MAX_KWH:
        raise ValueError(f"The battery capacity must be between {CAPACITY_MIN_KWH:g} and {CAPACITY_MAX_KWH:g} kWh")
    domain = (entity_id or "").split(".", 1)[0]
    return (domain if domain in ("input_number", "number") else None), kwh


async def make_capacity_helper(link, kwh: float) -> str:
    """The add-on's EVDC SoC Range Vehicle Battery Capacity helper, found or made at `kwh`, and
    picked on the Settings tab. Returns its entity ID."""
    kind, spec = HELPERS["capacity"]
    entity_id = f"{kind}.{slugify(spec['name'])}"
    states = {st.get("entity_id") for st in await link.all_states(fresh=True)}
    if entity_id not in states:
        result = await link.query({"type": f"{kind}/create", **spec, "initial": kwh})
        entity_id = f"{kind}.{(result or {}).get('id') or slugify(spec['name'])}"
        logger.info("Helpers: %s: made %s at %g", spec["name"], entity_id, kwh)
    await link.update_settings({"capacity": entity_id})
    logger.info("Battery capacity: now from %s", entity_id)
    return entity_id


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


OCTOPUS_RATE = re.compile(r"^sensor\.octopus_energy_electricity_.+_current_rate$")


def automatic(key: str, entity_id: str) -> bool:
    """Was this picker filled in by the add-on (a Sigenergy default, a helper it makes or
    finds, or the Octopus rate sensors), rather than picked by hand? For the Settings tab."""
    from src.ha_link import DEFAULT_ENTITIES

    if not entity_id:
        return False
    if DEFAULT_ENTITIES.get(key) == entity_id:
        return True
    if key in HELPERS:
        kind, spec = HELPERS[key]
        return entity_id.startswith(f"{kind}.{slugify(spec['name'])}")  # e.g. ..._2 if the name was taken
    if key in ("import_rate", "export_rate"):
        return bool(OCTOPUS_RATE.match(entity_id))
    return False


def find_rates(states: dict) -> dict:
    """The Octopus Energy integration's import and export current rate sensors, if there are any."""
    ids = sorted(e for e in states if OCTOPUS_RATE.match(e or ""))
    found = {}
    imports = [e for e in ids if "export" not in e]
    exports = [e for e in ids if e.endswith("_export_current_rate")]
    if imports:
        found["import_rate"] = imports[0]
    if exports:
        found["export_rate"] = exports[0]
    return found


# The helpers' names before 0.23.0 (now named like the sensors, "EVDC SoC Range ..."): one of
# these picked on the Settings tab is moved to the new name, at its value, and the old one removed
LEGACY = {
    "soc_high": "input_number.evdc_soc_high_limit",
    "soc_low": "input_number.evdc_soc_low_limit",
    "capacity": "input_number.evdc_vehicle_battery_capacity",
}


async def rename_legacy(link, states: dict) -> list[str]:
    """Move any picked helper with an old name (LEGACY) to its new name, keeping its value.
    Returns what was done, for the log."""
    done, changes, ui = [], {}, None
    for key, old in LEGACY.items():
        if link.settings.get(key) != old:
            continue
        kind, spec = HELPERS[key]
        new = f"{kind}.{slugify(spec['name'])}"
        old_st = states.get(old)
        if new in states:
            done.append(f"{spec['name']}: using {new} in place of {old}")
        else:
            spec = dict(spec)
            for source in (old, KNOWN_VALUES.get(key, "")):  # its value, else the V2X helper's
                try:
                    spec["initial"] = float((states.get(source) or {}).get("state"))
                    break
                except (TypeError, ValueError):
                    pass
            result = await link.query({"type": f"{kind}/create", **spec})
            new = f"{kind}.{(result or {}).get('id') or slugify(spec['name'])}"
            states[new] = {"entity_id": new, "state": str(spec["initial"])}
            done.append(f"{spec['name']}: made {new} at {spec['initial']:g}, in place of {old}")
        changes[key] = new
        if old_st is not None:
            if ui is None:
                ui = {item.get("id") for item in (await link.query({"type": f"{kind}/list"}) or [])}
            if old.split(".", 1)[1] in ui:  # the add-on's own (UI) helper: removed, not one from YAML
                await link.query({"type": f"{kind}/delete", f"{kind}_id": old.split(".", 1)[1]})
                done.append(f"removed the old {old}")
    if changes:
        await link.update_settings(changes)
    return done


# Helpers the add-on makes and owns as its own (UI) helpers, not ones from YAML, so they can be
# changed in Home Assistant: the high and low limits. (The charging mode is only made if its
# picker is empty, like the capacity: it's often kept in YAML.)
OWNED = ("soc_high", "soc_low")


async def _owned_helper(link, key: str, states: dict, notes: list) -> Optional[str]:
    """For an owned helper whose picker is empty or on the add-on's own entity ID: "ok" if
    Home Assistant has it as a UI helper, "yaml" if only YAML defines it (a note says to remove
    it there), "make" if there's none at all (and Home Assistant has finished starting).
    None: leave it alone."""
    kind, spec = HELPERS[key]
    own = f"{kind}.{slugify(spec['name'])}"
    picked = link.settings.get(key)
    if picked not in (None, "", own):
        # Something else is picked: that's the user's choice. Said in the log, as it's why the
        # add-on's own helper isn't made
        logger.info("Helpers: %s uses %s (picked on the Settings tab), so %s isn't made. Clear it there "
                    "and restart the add-on to use the add-on's own helper.", key.replace("soc_", "") + " limit",
                    picked, own)
        return None
    ui = {item.get("id") for item in (await link.query({"type": f"{kind}/list"}) or [])}
    if own.split(".", 1)[1] in ui:
        return "ok"
    if own in states:
        notes.append(f"{own} is defined in YAML. Remove it from your YAML and restart Home Assistant: "
                     f"the add-on then makes it as a helper of its own ({spec['name']}).")
        return "yaml"
    config = await link.query({"type": "get_config"}) or {}
    return "make" if config.get("state", "RUNNING") == "RUNNING" else None


async def ensure_helpers(link, notes: Optional[list] = None) -> list[str]:
    """Fill any empty helper picker: an existing helper of the same name, or a new one. The
    limits (OWNED) are the add-on's own UI helpers: made if they're missing, even if the picker
    still names them (unless something else is picked). Returns what was done, for the log; `notes` gets anything the
    user needs to do."""
    notes = [] if notes is None else notes
    missing = [key for key in HELPERS if not link.settings.get(key)]
    rates_missing = not link.settings.get("import_rate") and not link.settings.get("export_rate")
    states = {st.get("entity_id"): st for st in await link.all_states(fresh=True)}
    renamed = await rename_legacy(link, states)
    make = set()
    for key in OWNED:  # "ok" / "yaml": an empty picker is filled with it below, as for the others
        if await _owned_helper(link, key, states, notes) == "make":
            make.add(key)
    missing = list(dict.fromkeys(missing + sorted(make)))
    if not missing and not rates_missing:
        for line in renamed:
            logger.info("Helpers: %s", line)
        return renamed
    changes, done = {}, list(renamed)
    if rates_missing:
        for key, entity_id in find_rates(states).items():
            changes[key] = entity_id
            done.append(f"{'Import' if key == 'import_rate' else 'Export'} rate: using {entity_id}")
    for key in missing:
        kind, spec = HELPERS[key]
        existing = f"{kind}.{slugify(spec['name'])}"
        if existing in states and key not in make:
            changes[key] = existing
            done.append(f"{spec['name']}: using {existing}")
            continue
        spec = dict(spec)
        try:
            spec["initial"] = float((states.get(KNOWN_VALUES.get(key, "")) or {}).get("state"))
        except (TypeError, ValueError):
            pass
        result = await link.query({"type": f"{kind}/create", **spec})
        entity_id = f"{kind}.{(result or {}).get('id') or slugify(spec['name'])}"
        changes[key] = entity_id
        done.append(f"{spec['name']}: made {entity_id}" + (f" at {spec['initial']:g}" if kind == "input_number" else ""))
    if changes:
        await link.update_settings(changes)
    for line in done:
        logger.info("Helpers: %s", line)
    for line in notes:
        logger.warning("Helpers: %s", line)
    return done
