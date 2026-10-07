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

logger = logging.getLogger(__name__)

# key -> (helper type, what to make)
HELPERS = {
    "soc_high": ("input_number", {
        "name": "EVDC SoC High Limit", "min": 21, "max": 99, "step": 1, "mode": "slider",
        "unit_of_measurement": "%", "icon": "mdi:battery-arrow-up", "initial": 80}),
    "soc_low": ("input_number", {
        "name": "EVDC SoC Low Limit", "min": 20, "max": 98, "step": 1, "mode": "slider",
        "unit_of_measurement": "%", "icon": "mdi:battery-arrow-down", "initial": 40}),
    "capacity": ("input_number", {
        "name": "EVDC Vehicle Battery Capacity", "min": 0, "max": 200, "step": 0.1, "mode": "box",
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


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


OCTOPUS_RATE = re.compile(r"^sensor\.octopus_energy_electricity_.+_current_rate$")


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


async def ensure_helpers(link) -> list[str]:
    """Fill any empty helper picker: an existing helper of the same name, or a new one.
    Returns what was done, for the log."""
    missing = [key for key in HELPERS if not link.settings.get(key)]
    rates_missing = not link.settings.get("import_rate") and not link.settings.get("export_rate")
    if not missing and not rates_missing:
        return []
    states = {st.get("entity_id"): st for st in await link.all_states(fresh=True)}
    changes, done = {}, []
    if rates_missing:
        for key, entity_id in find_rates(states).items():
            changes[key] = entity_id
            done.append(f"{'Import' if key == 'import_rate' else 'Export'} rate: using {entity_id}")
    for key in missing:
        kind, spec = HELPERS[key]
        existing = f"{kind}.{slugify(spec['name'])}"
        if existing in states:
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
    return done
