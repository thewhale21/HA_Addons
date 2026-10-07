from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Callable, Awaitable

from aiohttp import web

from src.charger_sim import VALID_CURRENT_SETTINGS
from src.shared_state import SharedState

logger = logging.getLogger(__name__)


def create_api_app(
    shared_state: SharedState,
    on_plug: Callable[[], Awaitable[None]],
    on_unplug: Callable[[], Awaitable[None]],
    on_set_current: Callable[[int], Awaitable[None]],
    on_set_power: Callable[[float | None], Awaitable[None]] | None = None,
    on_refresh: Callable[[], None] | None = None,
    on_set_soc: Callable[[float | None], Awaitable[None]] | None = None,
    gui=None,
    automation=None,
    on_set_ramp: Callable[[float, float], None] | None = None,
    ha_link=None,
    on_charge_now: Callable[[float, bool], Awaitable[dict]] | None = None,
    debug=None,
    app_settings=None,
) -> web.Application:
    app = web.Application()
    app["shared_state"] = shared_state
    app["on_plug"] = on_plug
    app["on_unplug"] = on_unplug
    app["on_set_current"] = on_set_current
    app["on_set_power"] = on_set_power
    app["on_refresh"] = on_refresh
    app["on_set_soc"] = on_set_soc
    app["events_stop"] = asyncio.Event()
    app["gui"] = gui  # src.gui_data.GuiSources, or None (GUI tabs then empty)
    app["automation"] = automation  # src.automation.Automation, or None
    app["ha_link"] = ha_link  # src.ha_link.HaLink, or None
    app["on_set_ramp"] = on_set_ramp
    app["on_charge_now"] = on_charge_now
    app["debug"] = debug  # src.debug_tools.DebugTools, or None
    app["app_settings"] = app_settings  # src.app_settings.AppSettings, or None
    # Open /api/events streams (web pages)
    app["event_clients"] = {"gui": 0}
    app.on_shutdown.append(_close_event_streams)

    # Ingress serves the status page — use relative path for API calls
    static_dir = Path(__file__).parent / "static"
    app.router.add_get("/", handle_index)
    app["static_dir"] = static_dir
    app.router.add_get("/api/state", handle_get_state)
    app.router.add_post("/api/plug", handle_plug)
    app.router.add_post("/api/unplug", handle_unplug)
    app.router.add_post("/api/charge_now", handle_charge_now)
    app.router.add_post("/api/current", handle_current)
    app.router.add_post("/api/power", handle_power)
    app.router.add_post("/api/soc", handle_soc)
    app.router.add_post("/api/ramp", handle_ramp)
    app.router.add_get("/api/events", handle_events)
    # The web page's tabs
    app.router.add_get("/api/messages", handle_messages)
    app.router.add_get("/api/sessions", handle_sessions)
    app.router.add_get("/api/history", handle_history)
    app.router.add_get("/api/energy/daily", handle_energy_daily)
    app.router.add_get("/api/provider", handle_provider)
    app.router.add_get("/api/health", handle_health)
    # Schedule and auto re-plug
    app.router.add_get("/api/automation", handle_automation)
    app.router.add_post("/api/automation/schedule", handle_schedule)
    app.router.add_post("/api/automation/replug", handle_replug)
    app.router.add_post("/api/automation/skip", handle_skip)
    # Your HA sensors (Settings tab)
    app.router.add_get("/api/sensors", handle_get_sensors)
    app.router.add_post("/api/sensors", handle_set_sensors)
    app.router.add_get("/api/sensors/entities", handle_sensor_entities)
    app.router.add_get("/api/smart_charging", handle_smart_charging)
    # Settings made on the web page (log level, continue session)
    app.router.add_get("/api/settings", handle_get_settings)
    app.router.add_post("/api/settings", handle_set_settings)
    # Diagnostics › Debug
    app.router.add_get("/api/debug/info", handle_debug_info)
    app.router.add_post("/api/debug/send", handle_debug_send)
    app.router.add_post("/api/debug/drop", handle_debug_drop)
    app.router.add_post("/api/debug/restart", handle_debug_restart)
    app.router.add_post("/api/debug/log_level", handle_debug_log_level)
    app.router.add_post("/api/debug/clear", handle_debug_clear)

    return app


async def handle_index(request: web.Request) -> web.Response:
    static_dir: Path = request.app["static_dir"]
    index = static_dir / "index.html"
    # Never cached: after an update the browser (or HA's ingress) must not
    # keep showing the old page. It's small and only loaded when opened.
    return web.Response(
        body=index.read_bytes(),
        content_type="text/html",
        charset="utf-8",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


async def handle_get_state(request: web.Request) -> web.Response:
    state: SharedState = request.app["shared_state"]
    on_refresh = request.app["on_refresh"]
    if on_refresh is not None:
        try:
            on_refresh()  # live power, not just the last meter reading
        except Exception:
            logger.debug("Live power refresh failed", exc_info=True)
    return web.json_response(state.to_dict())


async def handle_plug(request: web.Request) -> web.Response:
    await request.app["on_plug"]()
    return web.json_response({"status": "ok"})


async def handle_unplug(request: web.Request) -> web.Response:
    await request.app["on_unplug"]()
    return web.json_response({"status": "ok"})


async def handle_charge_now(request: web.Request) -> web.Response:
    """{"hours": 0.5..12 in half hours, "confirm": bool}: plug in now and add
    the charge to the schedule as a one-off, as auto plug-in does (see
    src/automation.py). If it would go over Octopus's 6 hours a day, the
    answer is {"needs_confirm": true, "plan": ...} and nothing is done until
    it's sent again with "confirm": true."""
    on_charge_now = request.app["on_charge_now"]
    if on_charge_now is None:
        return web.json_response({"status": "error", "message": "Not available"}, status=503)
    try:
        body = await request.json()
        hours = float(body["hours"])
        if not 0.5 <= hours <= 12 or hours * 2 != int(hours * 2):
            raise ValueError
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return web.json_response({"status": "error", "message": "hours must be 0.5 to 12, in half hours"}, status=400)
    try:
        out = await on_charge_now(hours, bool(body.get("confirm")))
    except ValueError as err:
        return web.json_response({"status": "error", "message": str(err)}, status=400)
    return web.json_response({"status": "ok", **out}, dumps=_dumps)


async def handle_current(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        amps = int(body["amps"])
    except Exception:
        return web.json_response(
            {"status": "error", "message": "Invalid request. Send JSON: {\"amps\": N}"},
            status=400,
        )
    if amps not in VALID_CURRENT_SETTINGS:
        return web.json_response(
            {"status": "error", "message": f"Invalid current. Valid: {VALID_CURRENT_SETTINGS}"},
            status=400,
        )
    await request.app["on_set_current"](amps)
    return web.json_response({"status": "ok"})


async def handle_power(request: web.Request) -> web.Response:
    on_set_power = request.app["on_set_power"]
    if on_set_power is None:
        return web.json_response(
            {"status": "error", "message": "Power override not supported"},
            status=501,
        )
    try:
        body = await request.json()
        power_kw = body.get("power_kw")
        if power_kw is not None:
            power_kw = float(power_kw)
    except (ValueError, Exception):
        return web.json_response(
            {"status": "error", "message": "Invalid request. Send JSON: {\"power_kw\": N} or {\"power_kw\": null}"},
            status=400,
        )
    await on_set_power(power_kw)
    return web.json_response({"status": "ok"})


async def handle_soc(request: web.Request) -> web.Response:
    """Car state of charge (%) set on the web page; null = unknown / not set."""
    on_set_soc = request.app["on_set_soc"]
    if on_set_soc is None:
        return web.json_response(
            {"status": "error", "message": "SoC not supported"}, status=501,
        )
    try:
        body = await request.json()
        soc = body.get("soc")
        if soc is not None:
            soc = float(soc)
            if not 0 <= soc <= 100:
                raise ValueError("soc must be 0-100")
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return web.json_response(
            {"status": "error", "message": "Invalid request. Send JSON: {\"soc\": 0-100} or {\"soc\": null}"},
            status=400,
        )
    await on_set_soc(soc)
    return web.json_response({"status": "ok"})


async def handle_ramp(request: web.Request) -> web.Response:
    """Simulated car start-up: {"start_delay_s": 0-60, "ramp_up_s": 0-60}."""
    on_set_ramp = request.app["on_set_ramp"]
    if on_set_ramp is None:
        return web.json_response({"status": "error", "message": "Not supported"}, status=501)
    try:
        body = await request.json()
        on_set_ramp(float(body["start_delay_s"]), float(body["ramp_up_s"]))
    except (KeyError, TypeError, ValueError, AttributeError, json.JSONDecodeError) as err:
        message = str(err) if isinstance(err, ValueError) and "60" in str(err) else (
            "Send JSON: {\"start_delay_s\": 0-60, \"ramp_up_s\": 0-60}")
        return web.json_response({"status": "error", "message": message}, status=400)
    return web.json_response({"status": "ok"})


# --- Push updates (Server-Sent Events) -------------------------------------

# Fields that change on every live-power refresh: pushed at most every
# EVENTS_LIVE_INTERVAL seconds, so the page isn't flooded. Any other
# change (state, plug, connection, energy, commands...) is pushed at once.
_LIVE_FIELDS = {
    "power_kw", "voltage", "current_a", "frequency_hz", "power_offered_kw",
    "power_entity_value",
}
EVENTS_CHECK_INTERVAL = 1.0
EVENTS_LIVE_INTERVAL = 10.0


def _significant(data: dict) -> dict:
    return {k: v for k, v in data.items() if k not in _LIVE_FIELDS}


def _state_snapshot(app: web.Application) -> dict:
    on_refresh = app["on_refresh"]
    if on_refresh is not None:
        try:
            on_refresh()
        except Exception:
            logger.debug("Live power refresh failed", exc_info=True)
    return app["shared_state"].to_dict()


async def handle_events(request: web.Request) -> web.StreamResponse:
    """Stream the state to the web page as Server-Sent Events.

    One event straight away, then on every significant change (within ~1s),
    and at least every EVENTS_LIVE_INTERVAL seconds with live power (which
    also keeps the connection alive).
    """
    app = request.app
    stop: asyncio.Event = app["events_stop"]
    resp = web.StreamResponse(headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
    await resp.prepare(request)
    last_sig = None
    last_sent = 0.0
    app["event_clients"]["gui"] += 1
    try:
        while not stop.is_set():
            sig = _significant(app["shared_state"].to_dict())
            now = time.monotonic()
            if sig != last_sig or now - last_sent >= EVENTS_LIVE_INTERVAL:
                data = _state_snapshot(app)
                await resp.write(f"data: {json.dumps(data, default=str)}\n\n".encode())
                last_sig = _significant(data)
                last_sent = now
            try:
                await asyncio.wait_for(stop.wait(), EVENTS_CHECK_INTERVAL)
            except asyncio.TimeoutError:
                pass
    except (ConnectionResetError, ConnectionError):
        pass  # page closed
    finally:
        app["event_clients"]["gui"] -= 1
    return resp


async def _close_event_streams(app: web.Application) -> None:
    """End open event streams so add-on shutdown isn't held up by them."""
    app["events_stop"].set()


# --- Web GUI -----------------------------------------------------------------


def _gui_unavailable() -> web.Response:
    return web.json_response({"status": "error", "message": "Not available"}, status=501)


def _number_param(request: web.Request, name: str, default: float = 0) -> float:
    try:
        return float(request.query.get(name, default))
    except ValueError:
        return default


async def handle_messages(request: web.Request) -> web.Response:
    """OCPP frames after ?after=<seq> (all kept ones without it)."""
    gui = request.app["gui"]
    if gui is None:
        return _gui_unavailable()
    log = gui.message_log
    after = int(_number_param(request, "after", 0))
    if after > log.last_seq:
        after = 0  # the add-on restarted: send everything again
    return web.json_response(
        {"messages": log.since(after), "last_seq": log.last_seq}, dumps=_dumps,
    )


async def handle_sessions(request: web.Request) -> web.Response:
    gui = request.app["gui"]
    if gui is None:
        return _gui_unavailable()
    return web.json_response(gui.sessions(), dumps=_dumps)


async def handle_history(request: web.Request) -> web.Response:
    """Chart samples newer than ?since=<unix time>: 10-second ones for up to
    24 hours, or with ?resolution=long 5-minute / hourly ones for up to 14
    days (read from Home Assistant's history, see src/ha_history.py)."""
    gui = request.app["gui"]
    if gui is None:
        return _gui_unavailable()
    since = _number_param(request, "since", 0)
    if request.query.get("resolution") == "long":
        samples = await gui.history.long_samples(since)
    else:
        samples = await gui.history.samples(since)
    return web.json_response(
        {"samples": samples, "now": time.time(), "error": getattr(gui.history, "error", None)}, dumps=_dumps)


async def handle_energy_daily(request: web.Request) -> web.Response:
    """kWh per day for the last ?days=N days (default 14, max 62)."""
    gui = request.app["gui"]
    if gui is None:
        return _gui_unavailable()
    days = int(min(62, max(1, _number_param(request, "days", 14))))
    try:
        sessions = gui.sessions()
        kept = list(sessions.get("history") or []) + ([sessions["current"]] if sessions.get("current") else [])
    except Exception:
        kept = []
    return web.json_response({"days": await gui.history.daily(days, kept)}, dumps=_dumps)


async def handle_provider(request: web.Request) -> web.Response:
    gui = request.app["gui"]
    if gui is None:
        return _gui_unavailable()
    return web.json_response(gui.provider(), dumps=_dumps)


async def handle_health(request: web.Request) -> web.Response:
    gui = request.app["gui"]
    if gui is None:
        return _gui_unavailable()
    info = dict(gui.health())
    info["event_streams"] = dict(request.app["event_clients"])
    return web.json_response(info, dumps=_dumps)


def _dumps(data) -> str:
    return json.dumps(data, default=str, separators=(",", ":"))


# --- Schedule and auto re-plug ----------------------------------------------


async def handle_automation(request: web.Request) -> web.Response:
    automation = request.app["automation"]
    if automation is None:
        return _gui_unavailable()
    return web.json_response(automation.snapshot(), dumps=_dumps)


async def _automation_change(request: web.Request, apply) -> web.Response:
    automation = request.app["automation"]
    if automation is None:
        return _gui_unavailable()
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Send a JSON object")
        apply(automation, body)
    except (ValueError, TypeError, json.JSONDecodeError) as err:
        return web.json_response({"status": "error", "message": str(err)}, status=400)
    automation.publish(request.app["shared_state"])
    return web.json_response({"status": "ok", **automation.snapshot()}, dumps=_dumps)


async def handle_schedule(request: web.Request) -> web.Response:
    """{"enabled": bool}, {"ready_time": bool}, {"unplug_wait_s": N} and/or
    {"entries": [{time, days, action, enabled}, ...]}."""
    link = request.app["ha_link"]
    sc = link.smart_charging() if link is not None else {}
    if request.app["automation"] is not None:
        request.app["automation"].limit_reset = sc.get("limit_reset")  # e.g. Octopus: 12:00
    return await _automation_change(
        request, lambda a, b: a.set_schedule(
            enabled=b.get("enabled"), entries=b.get("entries"), ready_time=b.get("ready_time"),
            ready_times=sc.get("ready_times"), provider=sc.get("provider") or "your supplier",
            # e.g. Octopus schedules at most 6 hours of smart charging a day
            daily_cap_min=sc.get("limit_min"),
            unplug_wait_s=b.get("unplug_wait_s"),
            override_guards=b.get("override_guards"),
            blocks=b.get("blocks"),
        ),
    )


async def handle_skip(request: web.Request) -> web.Response:
    """{"times": [{"entry_id", "date": "YYYY-MM-DD"}, ...], "skip": bool}: skip
    upcoming times once (a slot: its plug-in and unplug), or undo. A single
    {"entry_id", "date"} works too."""
    link = request.app["ha_link"]
    sc = link.smart_charging() if link is not None else {}
    if request.app["automation"] is not None:
        request.app["automation"].limit_reset = sc.get("limit_reset")  # e.g. Octopus: 12:00
    return await _automation_change(
        request, lambda a, b: a.set_skips(
            b.get("times") if "times" in b else [{"entry_id": b.get("entry_id"), "date": b.get("date")}],
            bool(b.get("skip", True)),
            # e.g. Octopus schedules at most 6 hours of smart charging a day
            daily_cap_min=sc.get("limit_min"),
            provider=sc.get("provider") or "your supplier",
        ),
    )


async def handle_replug(request: web.Request) -> web.Response:
    """Any of {"enabled": bool, "after_min": N, "attempts": N, "off_s": N}."""
    return await _automation_change(
        request, lambda a, b: a.set_replug(
            enabled=b.get("enabled"), after_min=b.get("after_min"), attempts=b.get("attempts"),
            off_s=b.get("off_s"),
        ),
    )


# --- Your HA sensors ----------------------------------------------------------


async def handle_get_sensors(request: web.Request) -> web.Response:
    """Settings, live values and the add-on's own HA entities.
    "configured": false until saved once."""
    link = request.app["ha_link"]
    if link is None:
        return _gui_unavailable()
    return web.json_response(link.snapshot(), dumps=_dumps)


async def handle_set_sensors(request: web.Request) -> web.Response:
    """Any of power_entity, soc_entity, plug_entity, auto_plug, auto_plug_entity,
    auto_plug_soc, auto_plug_ready, auto_plug_hours (only those sent change)."""
    link = request.app["ha_link"]
    if link is None:
        return _gui_unavailable()
    try:
        body = await request.json()
        await link.update_settings(body)
    except (ValueError, TypeError, json.JSONDecodeError) as err:
        return web.json_response({"status": "error", "message": str(err)}, status=400)
    return web.json_response({"status": "ok", **link.snapshot()}, dumps=_dumps)


async def handle_smart_charging(request: web.Request) -> web.Response:
    """Your supplier's smart charging plan (src/smart_charging.py)."""
    link = request.app["ha_link"]
    if link is None or not link.available:
        return web.json_response({"found": False, "error": "Not connected to Home Assistant"})
    try:
        return web.json_response(link.smart_charging(), dumps=_dumps)
    except Exception as err:
        return web.json_response({"found": False, "error": f"Couldn't read Home Assistant's states: {err}"})


async def handle_sensor_entities(request: web.Request) -> web.Response:
    link = request.app["ha_link"]
    if link is None:
        return _gui_unavailable()
    try:
        entities = await link.list_entities()
    except Exception as err:
        return web.json_response({"status": "error", "message": f"Couldn't list entities: {err}"}, status=502)
    return web.json_response({"entities": entities, "available": link.available}, dumps=_dumps)


# --- Settings made on the web page (src/app_settings.py) ----------------------


async def handle_get_settings(request: web.Request) -> web.Response:
    settings = request.app["app_settings"]
    if settings is None:
        return _gui_unavailable()
    return web.json_response(dict(settings.data))


async def handle_set_settings(request: web.Request) -> web.Response:
    """Any of {"log_level": "debug"|"info"|"warning"|"error", "continue_session": bool}."""
    settings = request.app["app_settings"]
    if settings is None:
        return _gui_unavailable()
    try:
        out = settings.update(await request.json())
    except (ValueError, TypeError, json.JSONDecodeError) as err:
        return web.json_response({"status": "error", "message": str(err)}, status=400)
    return web.json_response({"status": "ok", **out})


# --- Diagnostics › Debug (src/debug_tools.py) ---------------------------------


async def handle_debug_info(request: web.Request) -> web.Response:
    """The log level, the add-on's settings (redacted) and the last ?lines= log lines."""
    debug = request.app["debug"]
    if debug is None:
        return _gui_unavailable()
    return web.json_response(debug.info(int(_number_param(request, "lines", 200))), dumps=_dumps)


async def _debug_call(request: web.Request, apply) -> web.Response:
    debug = request.app["debug"]
    if debug is None:
        return _gui_unavailable()
    try:
        body = await request.json() if request.can_read_body else {}
        if not isinstance(body, dict):
            raise ValueError("Send a JSON object")
        out = apply(debug, body)
        if asyncio.iscoroutine(out):
            out = await out
    except (ValueError, TypeError, json.JSONDecodeError) as err:
        return web.json_response({"status": "error", "message": str(err)}, status=400)
    return web.json_response({"status": "ok", **(out or {})}, dumps=_dumps)


async def handle_debug_send(request: web.Request) -> web.Response:
    """{"message": "StatusNotification"|"MeterValues"|"Heartbeat"|"BootNotification", "status": ...}"""
    return await _debug_call(request, lambda d, b: d.send(b.get("message"), b.get("status")))


async def handle_debug_drop(request: web.Request) -> web.Response:
    """{"seconds": 0..600}: close the connection, reconnect after that long (at least 5 s)."""
    return await _debug_call(request, lambda d, b: d.drop(b.get("seconds", 0)))


async def handle_debug_restart(request: web.Request) -> web.Response:
    return await _debug_call(request, lambda d, b: d.restart())


async def handle_debug_log_level(request: web.Request) -> web.Response:
    """{"level": "debug"|"info"|"warning"|"error"}, saved (src/app_settings.py)."""
    return await _debug_call(request, lambda d, b: d.set_log_level(b.get("level")))


async def handle_debug_clear(request: web.Request) -> web.Response:
    """{"what": "sessions"|"messages"}"""
    return await _debug_call(request, lambda d, b: d.clear(b.get("what")))
