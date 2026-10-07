"""Reads Home Assistant's entities, asks src/controller.py what to do and
presses the charger's Start or Stop button.

Kept apart from the Home Assistant link so it can be tested with plain
dictionaries: `states` is entity_id -> {"state", "attributes",
"last_changed"}, `entities` is the Settings tab's picks (key -> entity_id)
and `press` / `notify` are coroutines supplied by src/__main__.py.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import time
from collections import deque
from typing import Awaitable, Callable, Optional

from src.controller import RULES, Decision, Inputs, decide

logger = logging.getLogger(__name__)

LOG_SIZE = 100
UNKNOWN = ("unknown", "unavailable", "none", "")

# Lists the Settings tab can change (Advanced); matched without regard to case
LIST_DEFAULTS = {
    # The charger's running states (sensor.sigen_inverter_dc_charger_running_state)
    "plugged_states": ["Occupied", "#Alarm", "Ended", "Preparing Comm", "Preparing Insulation",
                       "Charging", "Discharging"],
    "active_states": ["Charging", "Discharging", "Preparing Insulation", "Preparing Comm"],
    "discharging_states": ["Discharging"],
    # The V2X mode entity's state(s) that mean "manage the charger"
    "mode_states": ["V2X", "on"],
    # EMS modes in which exporting isn't spare power (the plant is being told to discharge)
    "blocked_ems_modes": ["Command Discharging (PV First)", "Command Discharging (ESS First)"],
}


def _float(st: Optional[dict]) -> Optional[float]:
    if not st:
        return None
    try:
        value = float(st.get("state"))
    except (TypeError, ValueError):
        return None
    return value if value == value else None  # not NaN


def power_kw(st: Optional[dict]) -> Optional[float]:
    """A power sensor's reading in kW (W and MW converted)."""
    value = _float(st)
    if value is None:
        return None
    unit = ((st.get("attributes") or {}).get("unit_of_measurement") or "kW").strip()
    return value / 1000 if unit == "W" else value * 1000 if unit == "MW" else value


def _text(st: Optional[dict]) -> Optional[str]:
    value = (st or {}).get("state")
    return None if value is None or str(value).lower() in UNKNOWN else str(value)


def _in(value: Optional[str], options) -> bool:
    return value is not None and value.strip().lower() in {o.strip().lower() for o in options}


def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Manager:
    def __init__(self, data_dir: Optional[str] = None, *,
                 press: Optional[Callable[[str], Awaitable[None]]] = None,
                 notify: Optional[Callable[[str, str], Awaitable[None]]] = None) -> None:
        self._path = os.path.join(data_dir, "state.json") if data_dir else None
        self.press = press  # (entity_id) -> presses that button
        self.notify = notify  # (title, message) -> sends a notification
        self.soc: Optional[float] = None  # the car's last known SoC
        self.soc_at: Optional[float] = None  # ...when it was read
        self.soc_before_plug_in = False  # ...and it's from before the car was last plugged in
        self.active: Optional[bool] = None
        self.active_since: Optional[float] = None
        self.plugged: Optional[bool] = None
        self.export_since: Optional[float] = None
        self.last_press_at: Optional[float] = None
        self.presses_today = 0
        self.day: Optional[str] = None
        self.log: deque = deque(maxlen=LOG_SIZE)
        self.inputs: Optional[Inputs] = None
        self.decision: Optional[Decision] = None
        self.readings: dict = {}
        self._load()

    # --- saved between restarts ------------------------------------------------

    def _load(self) -> None:
        if not self._path:
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            self.soc, self.soc_at = data.get("soc"), data.get("soc_at")
            self.soc_before_plug_in = bool(data.get("soc_before_plug_in"))
            self.log.extend(data.get("log") or [])
            self.presses_today, self.day = int(data.get("presses_today") or 0), data.get("day")
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("Saved state %s is unreadable: starting afresh", self._path)

    def _save(self) -> None:
        if not self._path:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"soc": self.soc, "soc_at": self.soc_at, "soc_before_plug_in": self.soc_before_plug_in,
                           "presses_today": self.presses_today, "day": self.day, "log": list(self.log)}, f)
            os.replace(tmp, self._path)
        except Exception:
            logger.warning("Could not save the state", exc_info=True)

    # --- reading Home Assistant ---------------------------------------------------

    def observe(self, states: dict, entities: dict, settings: dict, now: float) -> Inputs:
        """Turn the entities' states into the controller's inputs, keeping track of
        what needs remembering (last known SoC, when the charger stopped...)."""
        lists = {k: settings.get(k) or v for k, v in LIST_DEFAULTS.items()}
        get = lambda key: states.get(entities.get(key) or "")  # noqa: E731

        running_st = get("running_state")
        running = _text(running_st)
        plugged = _in(running, lists["plugged_states"])
        active = _in(running, lists["active_states"])
        discharging = _in(running, lists["discharging_states"])

        if self.active is None:  # first look: when did the running state last change?
            changed = (running_st or {}).get("last_changed")
            self.active_since = changed if isinstance(changed, (int, float)) else now
        elif active != self.active:
            self.active_since = now
            logger.info("Charger %s (%s)", "running" if active else "stopped", running or "unknown")
        self.active = active

        if plugged and self.plugged is False:
            self.soc_before_plug_in = self.soc is not None  # until a new reading arrives
            logger.info("Car plugged in")
        elif not plugged and self.plugged:
            logger.info("Car unplugged")
        self.plugged = plugged

        soc = _float(get("vehicle_soc"))
        if soc is not None and 0 < soc <= 100:
            if soc != self.soc or self.soc_before_plug_in:
                self.soc, self.soc_at, self.soc_before_plug_in = soc, now, False
                self._save()
            else:
                self.soc_at = now

        mode_st = get("v2x_mode")
        mode = _text(mode_st)
        mode_on = None if mode is None else _in(mode, lists["mode_states"])

        export = power_kw(get("export_power"))
        level = float(settings.get("export_kw", 0.5))
        if export is not None and export > level:
            self.export_since = self.export_since or now
        else:
            self.export_since = None

        signal_st = get("charge_signal")
        signal = None if not entities.get("charge_signal") else _in(_text(signal_st), ("on", "true", "charging"))
        ems = _text(get("ems_mode"))

        self.inputs = Inputs(
            plugged_in=plugged, mode_on=mode_on, running_state=running, active=active, discharging=discharging,
            inactive_for=None if active else max(0.0, now - (now if self.active_since is None else self.active_since)),
            soc=self.soc, high=_float(get("soc_high")), low=_float(get("soc_low")),
            battery_kw=power_kw(get("battery_power")), grid_kw=power_kw(get("grid_power")),
            export_kw=export, export_held_s=0.0 if self.export_since is None else now - self.export_since,
            ems_mode=ems, charge_signal=signal, ems_blocked=_in(ems, lists["blocked_ems_modes"]),
        )
        self.readings = {"capacity_kwh": _float(get("capacity")), "mode": mode}
        return self.inputs

    # --- acting -----------------------------------------------------------------

    async def step(self, states: dict, entities: dict, settings: dict, now: Optional[float] = None) -> Decision:
        """Look, decide and (unless only watching) press a button. Returns the decision."""
        now = time.time() if now is None else now
        self._new_day(now)
        inputs = self.observe(states, entities, settings, now)
        decision = decide(inputs, settings)
        if decision.action:
            gap = float(settings.get("press_gap_s", 60))
            if self.last_press_at is not None and now - self.last_press_at < gap:
                left = round(gap - (now - self.last_press_at))
                decision = Decision(None, "press_gap", "Waiting to retry",
                                    f"{RULES.get(decision.rule, decision.rule)}, but a button was pressed "
                                    f"{round(now - self.last_press_at)} s ago; trying again in {left} s.")
            else:
                await self.act(decision.action, decision.rule, decision.reason, entities, settings, now)
        self.decision = decision
        return decision

    async def act(self, action: str, rule: str, reason: str, entities: dict, settings: dict,
                  now: Optional[float] = None) -> dict:
        """Press Start or Stop (rule "manual" from the web page). Returns the log entry."""
        now = time.time() if now is None else now
        button = entities.get("start_button" if action == "start" else "stop_button")
        watching = bool(settings.get("observe_only")) and rule != "manual"
        entry = {"at": _iso(now), "action": action, "rule": rule, "reason": reason,
                 "soc": self.soc, "pressed": False, "observe_only": watching, "error": None}
        self.last_press_at = now
        if not button:
            entry["error"] = f"No {action} button set on the Settings tab"
        elif watching:
            logger.info("Would %s the charger (watching only): %s", action, reason)
        elif self.press is None:
            entry["error"] = "Not connected to Home Assistant"
        else:
            try:
                await self.press(button)
                entry["pressed"] = True
                self.presses_today += 1
                logger.info("%s the charger: %s", "Started" if action == "start" else "Stopped", reason)
            except Exception as err:
                entry["error"] = str(err) or type(err).__name__
        if entry["error"]:
            logger.warning("Couldn't %s the charger: %s", action, entry["error"])
        self.log.append(entry)
        self._save()
        if entry["pressed"] and settings.get("notify_service") and self.notify is not None:
            title = "V2X: charger " + ("started" if action == "start" else "stopped")
            try:
                await self.notify(title, f"{RULES.get(rule, 'Pressed on the add-on page')}. {reason}")
            except Exception as err:
                logger.warning("Couldn't send the notification: %s", err)
        return entry

    def _new_day(self, now: float) -> None:
        day = datetime.datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        if day != self.day:
            self.day, self.presses_today = day, 0

    # --- for the web page and the sensors ------------------------------------------

    def energy(self) -> dict:
        """kWh the car can give before the low limit, kWh between the limits, and how
        full that window is (%): like the V2X SoC template sensors, 0.01 when not in use."""
        i, cap = self.inputs, self.readings.get("capacity_kwh")
        out = {"available_kwh": 0.01, "window_kwh": 0.01, "window_pct": 0.0}
        if not i or not i.plugged_in or not i.mode_on or not cap or i.low is None or i.high is None:
            return out
        if i.soc is not None:
            out["available_kwh"] = round(max(cap * (i.soc - i.low) / 100, 0.01), 2)
        out["window_kwh"] = round(max(cap * (i.high - i.low) / 100, 0.01), 2)
        if out["window_kwh"] > 0.01:
            out["window_pct"] = round(min(100.0, out["available_kwh"] / out["window_kwh"] * 100), 1)
        return out

    def snapshot(self, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        i, d = self.inputs, self.decision
        return {
            "status": d.status if d else "Starting",
            "rule": d.rule if d else None,
            "reason": d.reason if d else "",
            "inputs": None if i is None else {**i.__dict__},
            "soc_at": _iso(self.soc_at),
            "soc_age_s": None if self.soc_at is None else round(now - self.soc_at),
            "soc_before_plug_in": self.soc_before_plug_in,
            "active_since": _iso(self.active_since),
            "presses_today": self.presses_today,
            "last_action": self.log[-1] if self.log else None,
            "log": list(self.log)[-30:][::-1],
            "energy": self.energy(),
            "readings": dict(self.readings),
        }
