"""Reads your Home Assistant sensors directly and acts on them.

Set up on the web page: the sensors on the Settings tab, auto plug-in on
the Automations tab (saved in /data/sensors.json):

- power_entity:  real power (W or kW) reported instead of the simulation
- soc_entity:    the car's SoC, reported to the supplier (and car full / taper)
- plug_entity:   a car-connected binary sensor: off -> on switches Plugged In on
- auto_plug:     switch Plugged In on when the watched SoC drops below
                 auto_plug_soc; it watches auto_plug_entity if set, else
                 soc_entity (the monitor sensor is never reported)

The add-on talks to HA's websocket API through the Supervisor
(homeassistant_api: true gives it SUPERVISOR_TOKEN) and follows just these
entities with subscribe_entities, so changes arrive at once.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Awaitable, Callable, Optional

from src.autoplug import DEFAULT_AUTO_PLUG_SOC, AutoPlug, CarConnected
from src import suppliers
from src.ready_time import ALL_DAY_TIMES, allowed_times, pick_ready_time, service_call, target_time_entity
from src.smart_charging import find_dispatch_sensors, provider_name, smart_charging
from src.ha_entities import (
    ALL_SENSORS, HELPER_ICON, HELPER_ID, HELPER_NAME, PluggedInSync, SensorPublisher,
    helper_entity_id, integration_entities,
)

logger = logging.getLogger(__name__)

SUPERVISOR_WS = "ws://supervisor/core/websocket"
SUPERVISOR_API = "http://supervisor/core/api"
RECONNECT_DELAYS = (2, 5, 10, 20, 30, 60)
DISPATCH_SEARCH_S = 600  # look for a supplier's dispatching sensor again this often
ENTITY_LIST_TTL_S = 30
_UNKNOWN_STATES = ("unavailable", "unknown", "none", "")
DEFAULT_AUTO_PLUG_HOURS = 3.0


def validate_settings(raw: dict, current: Optional[dict] = None) -> dict:
    """Merge `raw` into `current` and check it. Empty entity = not used."""
    if not isinstance(raw, dict):
        raise ValueError("Send a JSON object")
    out = dict(current or default_settings())
    for key in ("power_entity", "soc_entity", "plug_entity", "auto_plug_entity", "voltage_entity"):
        if key in raw:
            value = (raw[key] or "").strip() if isinstance(raw[key], (str, type(None))) else None
            if value is None:
                raise ValueError(f"{key} must be an entity ID or empty")
            domain = "binary_sensor" if key == "plug_entity" else "sensor"
            if value and not value.startswith(domain + "."):
                raise ValueError(f"{key} must be a {domain} entity")
            out[key] = value
    if "auto_plug" in raw:
        out["auto_plug"] = bool(raw["auto_plug"])
    if "auto_plug_soc" in raw:
        try:
            soc = int(float(raw["auto_plug_soc"]))
        except (TypeError, ValueError):
            raise ValueError("auto_plug_soc must be a number") from None
        if not 1 <= soc <= 99:
            raise ValueError("auto_plug_soc must be 1 to 99")
        out["auto_plug_soc"] = soc
    if "auto_plug_ready" in raw:
        out["auto_plug_ready"] = bool(raw["auto_plug_ready"])
    if "plug_ready" in raw:  # the car plugged in sensor adds a charge to the schedule
        out["plug_ready"] = bool(raw["plug_ready"])
    if "plug_hours" in raw:
        try:
            hours = float(raw["plug_hours"])
        except (TypeError, ValueError):
            raise ValueError("plug_hours must be a number") from None
        if not 0.5 <= hours <= 12 or hours * 2 != int(hours * 2):
            raise ValueError("plug_hours must be 0.5 to 12, in half hours")
        out["plug_hours"] = hours
    if "auto_plug_hours" in raw:
        try:
            hours = float(raw["auto_plug_hours"])
        except (TypeError, ValueError):
            raise ValueError("auto_plug_hours must be a number") from None
        if not 0.5 <= hours <= 12 or hours * 2 != int(hours * 2):
            raise ValueError("auto_plug_hours must be 0.5 to 12, in half hours")
        out["auto_plug_hours"] = hours
    # Your supplier (Settings tab): override what's found automatically
    if "supplier_entity" in raw:
        value = str(raw["supplier_entity"] or "").strip()
        if value and not value.startswith(("binary_sensor.", "sensor.")):
            raise ValueError("supplier_entity must be a binary_sensor or sensor entity")
        out["supplier_entity"] = value
    if "ready_entity" in raw:
        value = str(raw["ready_entity"] or "").strip()
        if value and not value.startswith(("time.", "select.")):
            raise ValueError("ready_entity must be a time or select entity")
        out["ready_entity"] = value
    if "daily_limit_h" in raw:
        value = raw["daily_limit_h"]
        if value in (None, ""):
            out["daily_limit_h"] = None
        else:
            try:
                hours = float(value)
            except (TypeError, ValueError):
                raise ValueError("daily_limit_h must be a number of hours") from None
            if not 0 <= hours <= 24 or hours * 2 != int(hours * 2):
                raise ValueError("The daily limit must be 0 to 24 hours, in half hours (0: no limit)")
            out["daily_limit_h"] = hours
    if "voltage_v" in raw:
        value = raw["voltage_v"]
        if value in (None, ""):
            out["voltage_v"] = None
        else:
            try:
                volts = float(value)
            except (TypeError, ValueError):
                raise ValueError("voltage_v must be a number of volts") from None
            if not 100 <= volts <= 300:
                raise ValueError("The supply voltage must be 100 to 300 V")
            out["voltage_v"] = round(volts, 1)
    if "limit_reset" in raw:
        value = str(raw["limit_reset"] or "").strip()
        if value == "48h":  # 2.31.0
            value, out["limit_hours"] = "rolling", 48
        if value and value != "rolling" and value not in ALL_DAY_TIMES:
            raise ValueError("limit_reset must be empty (automatic), rolling, or a time on the hour or half hour, e.g. 12:00")
        out["limit_reset"] = value
    if "limit_hours" in raw:
        value = raw["limit_hours"]
        if value in (None, ""):
            out["limit_hours"] = None
        else:
            try:
                hours = float(value)
            except (TypeError, ValueError):
                raise ValueError("limit_hours must be a number of hours") from None
            if hours != int(hours) or not 1 <= hours <= 168:
                raise ValueError("The reset frequency must be 1 to 168 whole hours")
            out["limit_hours"] = int(hours)
    limit_h = out.get("daily_limit_h")
    if limit_h is None:  # automatic: the longest in src/suppliers.json (Octopus: 6)
        limit_h = max((s["daily_limit_h"] for s in suppliers.all_suppliers() if s["daily_limit_h"]), default=None)
    if out.get("limit_hours") and limit_h and out["limit_hours"] < limit_h:
        raise ValueError(f"The reset frequency ({out['limit_hours']} hours) can't be shorter than the daily "
                         f"limit ({limit_h:g} hours): nothing would ever be over it")
    for key in ("ready_from", "ready_to"):
        if key in raw:
            value = str(raw[key] or "").strip()
            if value and value not in ALL_DAY_TIMES:
                raise ValueError(f"{key} must be a time on the hour or half hour, e.g. 04:00")
            out[key] = value
    if out.get("ready_from") and out.get("ready_to") and out["ready_from"] > out["ready_to"]:
        raise ValueError("Ready times: the first time must be before the last")
    return out


def default_settings() -> dict:
    return {
        "power_entity": "", "soc_entity": "", "plug_entity": "",
        "voltage_entity": "", "voltage_v": None,  # supply voltage: a sensor, else this, else 230 V
        "auto_plug": False, "auto_plug_entity": "", "auto_plug_soc": DEFAULT_AUTO_PLUG_SOC,
        "auto_plug_ready": False, "auto_plug_hours": DEFAULT_AUTO_PLUG_HOURS,
        "plug_ready": False, "plug_hours": DEFAULT_AUTO_PLUG_HOURS,
        # Your supplier: empty / None = found automatically
        "supplier_entity": "", "ready_entity": "", "daily_limit_h": None, "ready_from": "", "ready_to": "",
        "limit_reset": "",  # "": automatic, "rolling": any limit_hours hours, "HH:MM": resets every day then
        "limit_hours": None,  # the rolling period, hours (None: 24)
    }


# Each supplier's daily limit and when it resets, unless set on the Settings
# tab: src/suppliers.json (edit it and rebuild the add-on to change them)


def _number(state: Optional[dict]) -> Optional[float]:
    if not state or str(state.get("state", "")).lower() in _UNKNOWN_STATES:
        return None
    try:
        return float(state["state"])
    except (TypeError, ValueError):
        return None


def power_kw(state: Optional[dict]) -> Optional[float]:
    """A power sensor's value in kW (W unless its unit says kW / MW)."""
    value = _number(state)
    if value is None:
        return None
    unit = str((state.get("attributes") or {}).get("unit_of_measurement") or "W").strip().lower()
    scale = {"kw": 1.0, "mw": 1000.0}.get(unit, 0.001)
    return value * scale


def soc_value(state: Optional[dict]) -> Optional[float]:
    value = _number(state)
    return value if value is not None and 0 <= value <= 100 else None


class HaLink:
    def __init__(
        self,
        data_dir: Optional[str],
        shared_state,
        set_power: Callable[[Optional[float]], None],
        set_soc: Callable[[Optional[float]], Awaitable[None]],
        plug: Callable[[], Awaitable[None]],
        token: Optional[str] = None,
        unplug: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        self._path = os.path.join(data_dir, "sensors.json") if data_dir else None
        self._shared = shared_state
        self._set_power = set_power
        self._set_soc = set_soc
        self._plug = plug
        self._unplug = unplug
        # Called (hours, source, plug source) instead of plugging in, for auto
        # plug-in or the car plugged in sensor with "adjust the schedule" on:
        # it plugs in and plans the charge (set by __main__)
        self.on_auto_plug = None
        self._session = None
        # The add-on's own HA entities (src/ha_entities.py)
        self.plug_sync = PluggedInSync()
        self.publisher = SensorPublisher()
        self.integration_conflict: list[str] = []
        self.entities_error: Optional[str] = None
        self._token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        self.settings = default_settings()
        self.configured = False  # settings saved at least once
        self.states: dict[str, dict] = {}  # entity_id -> {"state", "attributes"}
        self.connected = False
        self.error: Optional[str] = None
        self._changed = asyncio.Event()
        self._states_cache: tuple[float, list] = (0.0, [])  # all of HA's states, briefly
        # Your supplier's smart charging sensor(s) (src/smart_charging.py); the
        # first is followed live with the other entities
        self.dispatch_entities: list[str] = []
        self.ready_entity: Optional[str] = None  # its ready (target) time entity, if any
        self.ready_times: Optional[list[str]] = None  # the times that accepts
        self._dispatch_searched = 0.0
        self.dispatch_searched_at: Optional[float] = None  # wall clock, for Diagnostics › Health
        self._call = None  # websocket request function while connected
        self._reset_logic()
        self._load()

    # --- settings ------------------------------------------------------------

    def _load(self) -> None:
        if not self._path:
            return
        for path in (self._path, self._path + ".bak"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                self.settings = validate_settings(data, default_settings())
                self.configured = True
                break
            except FileNotFoundError:
                continue
            except Exception:
                logger.warning("Sensor settings %s are unreadable", path)
        self._reset_logic()

    def _save(self) -> None:
        if not self._path:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=1)
                f.flush()
                os.fsync(f.fileno())
            if os.path.exists(self._path):
                os.replace(self._path, self._path + ".bak")
            os.replace(tmp, self._path)
        except Exception:
            logger.warning("Could not save sensor settings", exc_info=True)

    def _reset_logic(self) -> None:
        s = self.settings
        self.monitor_entity = s["auto_plug_entity"] or s["soc_entity"]
        self.auto_plug = AutoPlug(bool(s["auto_plug"] and self.monitor_entity), s["auto_plug_soc"])
        self.car_connected = CarConnected()

    async def update_settings(self, raw: dict) -> dict:
        new = validate_settings(raw, self.settings)
        supplier_keys = ("supplier_entity", "ready_entity", "ready_from", "ready_to")
        supplier_changed = any(new.get(k) != self.settings.get(k) for k in supplier_keys)
        self.settings = new
        if supplier_changed:
            self._dispatch_searched = 0.0  # look again straight away, with these
            if self.ready_entity:
                self.ready_times = self._allowed_times(self.states.get(self.ready_entity))
        self.configured = True
        self._save()
        self._reset_logic()
        logger.info(
            "Sensors: power %s, SoC %s, car plugged in %s, auto plug-in %s",
            new["power_entity"] or "-", new["soc_entity"] or "-", new["plug_entity"] or "-",
            f"below {new['auto_plug_soc']}% on {self.monitor_entity}" if self.auto_plug.enabled else "off",
        )
        # Apply what we already know; the resubscribe brings fresh states
        await self._apply_all(initial=True)
        self._changed.set()
        return new

    @property
    def watched(self) -> list[str]:
        s = self.settings
        ids = [s["power_entity"], s["soc_entity"], s["plug_entity"], s.get("voltage_entity") or ""]
        if self.auto_plug.enabled:
            ids.append(self.monitor_entity)
        return sorted({e for e in ids if e})

    # --- reacting to states ----------------------------------------------------

    async def _apply_all(self, initial: bool) -> None:
        for entity_id in self.watched or [""]:
            await self._entity_changed(entity_id, initial=initial)
        if not self.settings["power_entity"]:
            self._set_power(None)
        if not self.settings["soc_entity"]:
            await self._set_soc(None)

    async def _entity_changed(self, entity_id: str, initial: bool = False) -> None:
        s = self.settings
        state = self.states.get(entity_id)
        if entity_id and entity_id == self.plug_sync.entity_id:
            action = self.plug_sync.from_ha(state.get("state") if state else None, bool(self._shared.plugged_in))
            if action == "plug":
                logger.info("%s turned on in Home Assistant: plugging in", entity_id)
                await self._safe_plug("Home Assistant")
            elif action == "unplug" and self._unplug is not None:
                logger.info("%s turned off in Home Assistant: unplugging", entity_id)
                try:
                    await self._unplug(source="Home Assistant")
                except Exception:
                    logger.warning("Couldn't unplug", exc_info=True)
        if entity_id and entity_id == s["power_entity"]:
            self._set_power(power_kw(state))
        if entity_id and entity_id == s["soc_entity"]:
            await self._set_soc(soc_value(state))
        plugged_in = bool(self._shared.plugged_in)
        if entity_id and entity_id == s["plug_entity"]:
            if self.car_connected.should_plug(state.get("state") if state else None, plugged_in):
                if s.get("plug_ready") and self.on_auto_plug is not None:
                    logger.info("%s turned on: adding a %g-hour charge to the schedule", entity_id,
                                s.get("plug_hours") or DEFAULT_AUTO_PLUG_HOURS)
                    try:
                        await self.on_auto_plug(s.get("plug_hours") or DEFAULT_AUTO_PLUG_HOURS, "car_plugged",
                                                "car plugged in sensor")
                    except Exception as err:
                        logger.warning("Car plugged in charge not planned (%s): plugging in", err)
                        await self._safe_plug("car plugged in sensor")
                else:
                    logger.info("%s turned on: switching Plugged In on", entity_id)
                    await self._safe_plug("car plugged in sensor")
                plugged_in = bool(self._shared.plugged_in)
        if entity_id and self.auto_plug.enabled and entity_id == self.monitor_entity:
            soc = soc_value(state)
            if self.auto_plug.should_plug(soc, plugged_in):
                logger.info("Car SoC %.0f%% dropped below %d%%: switching Plugged In on", soc, s["auto_plug_soc"])
                if s.get("auto_plug_ready") and self.on_auto_plug is not None:
                    try:
                        await self.on_auto_plug(s.get("auto_plug_hours") or DEFAULT_AUTO_PLUG_HOURS, "auto_plug",
                                                "auto plug-in (low SoC)")
                    except Exception as err:
                        logger.warning("Auto plug-in charge not planned (%s): plugging in", err)
                        if not await self._safe_plug("auto plug-in (low SoC)"):
                            self.auto_plug.armed = True
                elif not await self._safe_plug("auto plug-in (low SoC)"):
                    self.auto_plug.armed = True  # try again on the next reading

    async def _safe_plug(self, source: str) -> bool:
        try:
            await self._plug(source=source)
            return True
        except Exception:
            logger.warning("Couldn't plug in", exc_info=True)
            return False

    async def handle_entities_event(self, event: dict) -> None:
        """A subscribe_entities event: a = added (full), c = changed (diff), r = removed."""
        changed: list[str] = []
        for entity_id, full in (event.get("a") or {}).items():
            self.states[entity_id] = {"state": full.get("s"), "attributes": full.get("a") or {}}
            changed.append(entity_id)
        for entity_id, diff in (event.get("c") or {}).items():
            current = self.states.setdefault(entity_id, {"state": None, "attributes": {}})
            plus = diff.get("+") or {}
            if "s" in plus:
                current["state"] = plus["s"]
            if "a" in plus:
                current["attributes"] = {**current["attributes"], **plus["a"]}
            for key in (diff.get("-") or {}).get("a") or []:
                current["attributes"].pop(key, None)
            changed.append(entity_id)
        for entity_id in event.get("r") or []:
            self.states.pop(entity_id, None)
            changed.append(entity_id)
        for entity_id in changed:
            await self._entity_changed(entity_id)

    # --- connection --------------------------------------------------------------

    @property
    def available(self) -> bool:
        return bool(self._token)

    async def run(self) -> None:
        """Stay connected to HA for the life of the add-on."""
        await self._apply_all(initial=True)
        if not self.available:
            self.error = "Not running under the Home Assistant Supervisor"
            logger.info("Home Assistant link off: %s", self.error)
            return
        import aiohttp

        attempt = 0
        async with aiohttp.ClientSession() as session:
            self._session = session
            try:
                while True:
                    try:
                        await self._connection(session)
                        attempt = 0
                    except asyncio.CancelledError:
                        raise
                    except Exception as err:
                        self.error = str(err) or type(err).__name__
                        logger.warning("Home Assistant link lost (%s); reconnecting", self.error)
                    self.connected = False
                    await asyncio.sleep(RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)])
                    attempt += 1
            finally:
                self._session = None

    async def _connection(self, session) -> None:
        import aiohttp

        async with session.ws_connect(SUPERVISOR_WS, heartbeat=30, max_msg_size=64 * 1024 * 1024) as ws:
            msg = await ws.receive_json(timeout=10)
            if msg.get("type") != "auth_required":
                raise RuntimeError(f"Unexpected greeting {msg.get('type')}")
            await ws.send_json({"type": "auth", "access_token": self._token})
            msg = await ws.receive_json(timeout=10)
            if msg.get("type") != "auth_ok":
                raise RuntimeError("Home Assistant refused the add-on's token")
            self.connected, self.error = True, None
            logger.info("Connected to Home Assistant")

            pending: dict[int, asyncio.Future] = {}
            events: asyncio.Queue = asyncio.Queue()
            counter = {"id": 0, "sub": None}

            async def call(payload: dict, timeout: float = 15):
                counter["id"] += 1
                msg_id = counter["id"]
                fut = asyncio.get_running_loop().create_future()
                pending[msg_id] = fut
                await ws.send_json({**payload, "id": msg_id})
                try:
                    reply = await asyncio.wait_for(fut, timeout)
                finally:
                    pending.pop(msg_id, None)
                if not reply.get("success", True):
                    raise RuntimeError((reply.get("error") or {}).get("message") or "request failed")
                return reply.get("result")

            async def reader() -> None:
                async for raw in ws:
                    if raw.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                    if raw.type != aiohttp.WSMsgType.TEXT:
                        continue
                    data = json.loads(raw.data)
                    for message in data if isinstance(data, list) else [data]:
                        if message.get("type") == "result" and message.get("id") in pending:
                            pending[message["id"]].set_result(message)
                        elif message.get("type") == "event" and message.get("id") == counter["sub"]:
                            events.put_nowait(message.get("event") or {})
                raise ConnectionError("Home Assistant closed the connection")

            async def subscribe() -> None:
                if counter["sub"] is not None:
                    try:
                        await call({"type": "unsubscribe_events", "subscription": counter["sub"]})
                    except Exception:
                        pass
                    counter["sub"] = None
                # Fresh start: the subscription sends current states first
                self.states = {}
                self.car_connected = CarConnected()
                self.auto_plug.armed = False
                self.plug_sync.reset()
                ids = self.watched + ([self.plug_sync.entity_id] if self.plug_sync.entity_id else [])
                ids += self.dispatch_entities[:1]
                ids += [self.ready_entity] if self.ready_entity else []
                if ids:
                    counter["id"] += 1
                    counter["sub"] = counter["id"]
                    await ws.send_json({"id": counter["sub"], "type": "subscribe_entities", "entity_ids": sorted(set(ids))})

            reader_task = asyncio.ensure_future(reader())
            self._call = call
            try:
                await self._setup_entities(call)
                await self._find_dispatch_sensor(call)
                self._changed.clear()
                await subscribe()
                self.publisher.reset()
                while True:
                    if reader_task.done():
                        reader_task.result()  # raises why it ended
                    try:
                        event = await asyncio.wait_for(events.get(), 1.0)
                    except asyncio.TimeoutError:
                        event = None
                    if event is not None:
                        await self.handle_entities_event(event)
                    if time.monotonic() - self._dispatch_searched >= DISPATCH_SEARCH_S:
                        if await self._find_dispatch_sensor(call):
                            self._changed.set()  # follow the new sensor
                    if self._changed.is_set():
                        self._changed.clear()
                        await subscribe()
                    await self._sync_entities(call)
            finally:
                self._call = None
                reader_task.cancel()
                for fut in pending.values():
                    fut.cancel()

    # --- the add-on's own entities ----------------------------------------------

    async def _setup_entities(self, call) -> None:
        """Make sure the Plugged In helper exists; check for the old integration."""
        self.entities_error = None
        try:
            registry = await call({"type": "config/entity_registry/list"}, timeout=30) or []
        except Exception as err:
            registry = []
            logger.debug("Entity registry not readable: %s", err)
        self.integration_conflict = integration_entities(registry)
        if self.integration_conflict:
            logger.warning(
                "The OCPP Charge Proxy integration is still installed: remove it in Settings > "
                "Devices & services so the add-on can provide its entities (%s)",
                ", ".join(self.integration_conflict),
            )
        try:
            helpers = await call({"type": "input_boolean/list"}) or []
            if not any(h.get("id") == HELPER_ID for h in helpers):
                created = await call({"type": "input_boolean/create", "name": HELPER_NAME, "icon": HELPER_ICON})
                logger.info("Created the Plugged In helper (%s)", (created or {}).get("id"))
                registry = await call({"type": "config/entity_registry/list"}, timeout=30) or registry
            self.plug_sync.entity_id = helper_entity_id(registry)
        except Exception as err:
            self.plug_sync.entity_id = None
            self.entities_error = f"Couldn't set up the Plugged In helper: {err}"
            logger.warning("%s", self.entities_error)

    async def _sync_entities(self, call) -> None:
        # Plugged In: add-on -> HA
        entity_id = self.plug_sync.entity_id
        if entity_id:
            ha_state = (self.states.get(entity_id) or {}).get("state")
            target = self.plug_sync.to_ha(ha_state, bool(self._shared.plugged_in))
            if target is not None:
                try:
                    await call({
                        "type": "call_service", "domain": "input_boolean",
                        "service": "turn_on" if target else "turn_off",
                        "target": {"entity_id": entity_id},
                    })
                except Exception as err:
                    logger.warning("Couldn't update %s: %s", entity_id, err)
        # Sensors
        if not self.integration_conflict:
            for sensor_id, value, attrs in self.publisher.due(self._shared, time.time()):
                await self._post_state(sensor_id, value, attrs)

    async def _post_state(self, entity_id: str, state: str, attrs: dict) -> None:
        if self._session is None:
            return
        import aiohttp

        try:
            async with self._session.post(
                f"{SUPERVISOR_API}/states/{entity_id}",
                headers={"Authorization": f"Bearer {self._token}"},
                json={"state": state, "attributes": attrs},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
        except Exception as err:
            self.publisher.forget(entity_id)
            logger.debug("Couldn't post %s: %s", entity_id, err)

    async def query(self, payload: dict, timeout: float = 30):
        """A websocket request to HA (history, statistics...). Raises if not connected."""
        if self._call is None:
            raise ConnectionError("Not connected to Home Assistant")
        return await self._call(payload, timeout=timeout)

    @property
    def publishing(self) -> bool:
        """The add-on's sensors are being posted (so HA is recording them)."""
        return self.connected and not self.integration_conflict

    async def shutdown(self) -> None:
        """Mark the sensors unavailable while the add-on is stopped."""
        if not self.connected or self.integration_conflict:
            return
        for entity_id, state, attrs in SensorPublisher.unavailable():
            await self._post_state(entity_id, state, attrs)


    async def all_states(self) -> list[dict]:
        """Every entity's state in HA (cached briefly)."""
        cached_at, cached = self._states_cache
        if cached and time.monotonic() - cached_at < ENTITY_LIST_TTL_S:
            return cached
        if not self.available:
            return []
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SUPERVISOR_API}/states",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                states = await resp.json()
        self._states_cache = (time.monotonic(), states)
        return states

    async def _find_dispatch_sensor(self, call) -> bool:
        """Look for a supplier's dispatching sensor. True if what's found changed."""
        self._dispatch_searched = time.monotonic()
        self.dispatch_searched_at = time.time()
        try:
            states = await call({"type": "get_states"}, timeout=30) or []
        except Exception as err:
            logger.debug("Couldn't list states for smart charging: %s", err)
            return False
        by_id = {st.get("entity_id"): st for st in states}
        ids = [st["entity_id"] for st in find_dispatch_sensors(states)]
        chosen = self.settings.get("supplier_entity")  # picked on the Settings tab
        if chosen:
            ids = [chosen] + [i for i in ids if i != chosen]
        first = by_id.get(ids[0]) if ids else None
        if first:  # until the subscription brings it
            self.states[first["entity_id"]] = {"state": first.get("state"), "attributes": first.get("attributes") or {}}
        ready_id = self._ready_entity_id(states, ids[0] if ids else None)
        ready = by_id.get(ready_id) if ready_id else None
        ready_changed = ready_id != self.ready_entity
        self.ready_entity = ready_id
        self.ready_times = self._allowed_times(ready) if ready_id else None
        if ready:  # until the subscription brings it
            self.states[ready_id] = {"state": ready.get("state"), "attributes": ready.get("attributes") or {}}
        if ids == self.dispatch_entities:
            return ready_changed  # follow the ready time entity too
        if ids[:1] != self.dispatch_entities[:1]:
            logger.info("Smart charging: %s", f"following {ids[0]}" if ids else "no supplier sensor found")
        self.dispatch_entities = ids
        return True

    def _ready_entity_id(self, states: list, dispatch: Optional[str]) -> Optional[str]:
        """The ready (target) time entity: picked on the Settings tab, else the
        one next to the dispatching sensor."""
        if self.settings.get("ready_entity"):
            return self.settings["ready_entity"]
        found = target_time_entity(states, dispatch) if dispatch else None
        return found["entity_id"] if found else None

    def _allowed_times(self, entity: Optional[dict]) -> list:
        """The ready times your supplier accepts: set on the Settings tab, else
        what the entity says (src/ready_time.py)."""
        lo, hi = self.settings.get("ready_from"), self.settings.get("ready_to")
        if lo or hi:
            lo, hi = lo or ALL_DAY_TIMES[0], hi or ALL_DAY_TIMES[-1]
            return [t for t in ALL_DAY_TIMES if lo <= t <= hi]
        return allowed_times(entity)

    def voltage(self) -> Optional[float]:
        """The supply voltage: the voltage sensor's reading (100-300 V), else
        the one set on the Settings tab, else None (230 V is used)."""
        entity_id = self.settings.get("voltage_entity")
        if entity_id:
            v = _number(self.states.get(entity_id))
            if v is not None and 100 <= v <= 300:
                return v
        return self.settings.get("voltage_v")

    def daily_limit_min(self, provider: Optional[str]) -> Optional[int]:
        """Minutes of smart charging a day your supplier schedules at most
        (None: no limit): set on the Settings tab, else src/suppliers.json
        (Octopus: 6 hours)."""
        hours = self.settings.get("daily_limit_h")
        if hours is None:
            return suppliers.daily_limit_min(provider)
        return int(round(hours * 60)) or None

    def limit_reset(self, provider: Optional[str]) -> Optional[str]:
        """When your supplier's daily limit resets: "HH:MM" every day, None for
        any 24 hours (rolling), or "Nh" for any N hours (the reset frequency).
        Set on the Settings tab, else src/suppliers.json (Octopus: 12:00)."""
        value = self.settings.get("limit_reset") or ""
        if value == "48h":  # saved by 2.31.0
            value = "rolling"
        if not value:
            value = suppliers.limit_reset(provider)
        if value != "rolling":
            return value
        hours = self.settings.get("limit_hours") or (48 if self.settings.get("limit_reset") == "48h" else 24)
        return None if hours == 24 else f"{hours}h"

    def smart_charging(self) -> dict:
        """Your supplier's planned charge slots, if its integration is installed."""
        if not self.dispatch_entities:
            return {"found": False}
        entity_id = self.dispatch_entities[0]
        st = self.states.get(entity_id) or {}
        info = smart_charging([{"entity_id": entity_id, **st}], time.time())
        if info.get("found"):
            info["others"] = self.dispatch_entities[1:]
            info["ready_time_entity"] = self.ready_entity
            info["ready_times"] = self.ready_times
            info["limit_min"] = self.daily_limit_min(info.get("provider"))
            info["limit_reset"] = self.limit_reset(info.get("provider"))
            info["chosen"] = {k: self.settings.get(k) for k in
                              ("supplier_entity", "ready_entity", "daily_limit_h", "limit_reset", "limit_hours",
                               "ready_from", "ready_to")}
        return info

    async def set_ready_time(self, unplug) -> dict:
        """Set your supplier's ready-by time for an unplug at `unplug` (aware
        datetime), src/ready_time.py. Returns what was done, for the page."""
        import datetime as _dt
        out: dict = {"unplug": unplug.isoformat(timespec="minutes")}
        if self._call is None:
            return {**out, "error": "Not connected to Home Assistant"}
        dispatch = self.dispatch_entities[0] if self.dispatch_entities else None
        if not dispatch:
            return {**out, "error": "Your supplier's smart charging integration wasn't found"}
        try:
            states = await self._call({"type": "get_states"}, timeout=30) or []
        except Exception as err:
            return {**out, "error": f"Couldn't read Home Assistant's states: {err}"}
        ready_id = self._ready_entity_id(states, dispatch)
        entity = next((st for st in states if st.get("entity_id") == ready_id), None) if ready_id else None
        if entity is None:
            return {**out, "error": f"{provider_name(dispatch)}'s integration has no ready time (target time) setting"
                                    + (f" ({ready_id} wasn't found)" if ready_id else "")}
        out["entity_id"] = entity["entity_id"]
        allowed = self._allowed_times(entity)
        ready = pick_ready_time(_dt.datetime.now(unplug.tzinfo), unplug, allowed)
        if ready is None:
            return {**out, "error": f"{provider_name(dispatch)} only accepts ready times from {allowed[0]} to {allowed[-1]}, "
                                    f"and there's none before the unplug at {unplug.strftime('%H:%M')}"}
        try:
            await self._call(service_call(entity, ready))
        except Exception as err:
            return {**out, "error": f"Home Assistant refused the ready time: {err}"}
        out["ready"] = ready.strftime("%H:%M")
        out["ready_at"] = ready.isoformat(timespec="minutes")
        logger.info("Ready time set to %s on %s (schedule unplugs at %s)",
                    out["ready"], entity["entity_id"], unplug.strftime("%a %H:%M"))
        return out

    def smart_charging_health(self) -> dict:
        """For Diagnostics › Health: which supplier integration was found, and when it was looked for."""
        info = self.smart_charging()
        return {
            "found": bool(info.get("found")),
            "provider": info.get("provider"),
            "entity_id": info.get("entity_id"),
            "others": self.dispatch_entities[1:],
            "searched": None if self.dispatch_searched_at is None else time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.dispatch_searched_at)),
            "search_every_s": DISPATCH_SEARCH_S,
        }

    def supplier_plan(self) -> dict:
        """For the plan check (src/plan_check.py): the supplier's running and
        planned slots, and its ready time setting as it is now."""
        info = self.smart_charging()
        if not info.get("found"):
            return {"found": False}
        slots = ([info["current"]] if info.get("current") else []) + list(info.get("planned") or [])
        ready = (self.states.get(self.ready_entity) or {}).get("state") if self.ready_entity else None
        return {"found": True, "provider": info.get("provider"), "slots": slots, "supplier_ready": ready}

    def scheduled(self) -> Optional[bool]:
        """True if your supplier has a charge slot planned for later; None if
        there's no supplier sensor to tell."""
        info = self.smart_charging()
        if not info.get("found"):
            return None
        return bool(info.get("planned"))

    def slot_now(self) -> Optional[bool]:
        """True if one of your supplier's charge slots is running now (it
        should be charging); None if there's no supplier sensor to tell."""
        info = self.smart_charging()
        if not info.get("found"):
            return None
        return bool(info.get("current"))

    async def list_entities(self) -> list[dict]:
        """Sensors and binary sensors for the pickers."""
        states = await self.all_states()
        out = []
        for st in states:
            entity_id = st.get("entity_id", "")
            domain = entity_id.split(".", 1)[0]
            if domain not in ("sensor", "binary_sensor", "time", "select"):
                continue
            attrs = st.get("attributes") or {}
            out.append({
                "entity_id": entity_id,
                "name": attrs.get("friendly_name") or entity_id,
                "device_class": attrs.get("device_class"),
                "unit": attrs.get("unit_of_measurement"),
                "state": st.get("state"),
                # for the Your supplier pickers (Settings tab)
                "dispatch": bool(find_dispatch_sensors([st])),
                "ready": domain in ("time", "select") and "target_time" in entity_id,
            })
        out.sort(key=lambda e: (e["name"] or "").lower())
        return out

    # --- status ------------------------------------------------------------------

    def snapshot(self) -> dict:
        s = self.settings

        def entity(entity_id: str) -> Optional[dict]:
            if not entity_id:
                return None
            st = self.states.get(entity_id)
            attrs = (st or {}).get("attributes") or {}
            return {
                "entity_id": entity_id,
                "name": attrs.get("friendly_name") or entity_id,
                "state": (st or {}).get("state"),
                "unit": attrs.get("unit_of_measurement"),
            }

        monitor = entity(self.monitor_entity) if self.monitor_entity else None
        return {
            "settings": s,
            "configured": self.configured,
            "ha_entities": {
                "plugged_in": self.plug_sync.entity_id,
                "sensors": list(ALL_SENSORS),
                "publishing": self.publishing,
                "integration_conflict": self.integration_conflict,
                "error": self.entities_error,
            },
            "available": self.available,
            "connected": self.connected,
            "error": self.error,
            "power": {
                "entity": entity(s["power_entity"]),
                "kw": power_kw(self.states.get(s["power_entity"])) if s["power_entity"] else None,
                "source": self._shared.power_source,
            },
            "voltage": {
                "entity": entity(s.get("voltage_entity") or ""),
                "v": self.voltage(),
                "source": ("sensor" if s.get("voltage_entity") and self.voltage() is not None
                           and self.voltage() != s.get("voltage_v") else "set" if s.get("voltage_v") else "default"),
            },
            "reporting_soc": {
                "entity": entity(s["soc_entity"]),
                "soc": self._shared.soc_percent,
            },
            "plug": {
                "entity": entity(s["plug_entity"]),
                "last": self.car_connected.last,
            },
            "monitored_soc": {
                "entity": monitor,
                "soc": soc_value(self.states.get(self.monitor_entity)) if self.monitor_entity else None,
                "source": None if not self.monitor_entity else (
                    "monitor sensor" if s["auto_plug_entity"] else "reporting SoC sensor"
                ),
                "auto_plug": self.auto_plug.enabled,
                "threshold": s["auto_plug_soc"],
                "armed": self.auto_plug.armed,
            },
        }
