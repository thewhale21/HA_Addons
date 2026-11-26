"""The web page (Home Assistant ingress) and its API.

The page (static/index.html) calls these with relative URLs ("./api/..."),
so it works behind ingress and on the add-on's own port (8099). Add an
endpoint: a handler below and a line in create_api_app().
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from aiohttp import web

logger = logging.getLogger(__name__)

EVENTS_CHECK_INTERVAL = 1.0  # how often the event stream looks for changes
EVENTS_KEEPALIVE = 10.0  # ...and sends the state at least this often anyway
# Fields that change all the time: a change in only these isn't pushed at once
LIVE_FIELDS: set = set()


def create_api_app(shared_state, *, ha_link=None, health=None, debug=None, app_settings=None,
                   store=None, wake=None, pstore=None) -> web.Application:
    app = web.Application()
    app["shared_state"] = shared_state  # src.shared_state.SharedState
    app["ha_link"] = ha_link  # src.ha_link.HaLink, or None
    app["health"] = health  # src.health.Health, or None
    app["debug"] = debug  # src.debug_tools.DebugTools, or None
    app["app_settings"] = app_settings  # src.app_settings.AppSettings, or None
    app["store"] = store  # src.places.SceneStore, or None
    app["pstore"] = pstore  # src.places.PlaceStore (the other places' maps), or None
    app["wake"] = wake  # asyncio.Event: the map maker looks again (src/__main__.py)
    app["events_stop"] = asyncio.Event()
    app["event_clients"] = {"gui": 0}
    app["static_dir"] = Path(__file__).parent / "static"
    app.on_shutdown.append(_close_event_streams)

    app.router.add_get("/", handle_index)
    app.router.add_get("/card.js", handle_card_js)
    # The map (Overview, and the dashboard card)
    app.router.add_get("/api/scene", handle_scene)
    app.router.add_post("/api/address", handle_address)
    app.router.add_post("/api/home", handle_home)
    app.router.add_post("/api/refresh", handle_refresh)
    app.router.add_post("/api/places", handle_places)
    app.router.add_get("/api/zones", handle_zones)
    app.router.add_get("/api/state", handle_get_state)
    app.router.add_get("/api/events", handle_events)
    app.router.add_get("/api/health", handle_health)
    # Your Home Assistant entities (Settings tab)
    app.router.add_get("/api/sensors", handle_get_sensors)
    app.router.add_post("/api/sensors", handle_set_sensors)
    app.router.add_get("/api/sensors/entities", handle_sensor_entities)
    # Settings made on the web page (src/app_settings.py)
    app.router.add_get("/api/settings", handle_get_settings)
    app.router.add_post("/api/settings", handle_set_settings)
    # Diagnostics › Debug
    app.router.add_get("/api/debug/info", handle_debug_info)
    app.router.add_post("/api/debug/log_level", handle_debug_log_level)
    app.router.add_post("/api/debug/restart", handle_debug_restart)
    return app


def _dumps(data) -> str:
    return json.dumps(data, default=str)


def _unavailable() -> web.Response:
    return web.json_response({"status": "error", "message": "Not available"}, status=501)


def _bad_request(err) -> web.Response:
    return web.json_response({"status": "error", "message": str(err)}, status=400)


async def handle_index(request: web.Request) -> web.Response:
    index = request.app["static_dir"] / "index.html"
    # Never cached: after an update the browser (or HA's ingress) must not
    # keep showing the old page
    return web.Response(body=index.read_bytes(), content_type="text/html", charset="utf-8",
                        headers={"Cache-Control": "no-store, max-age=0"})


async def handle_card_js(request: web.Request) -> web.Response:
    """The drawing and the dashboard card (static/neighbourhood-view-card.js), for this page."""
    from src.card_install import card_js
    health = request.app["health"]
    return web.Response(text=card_js(health.version if health is not None else "dev"), content_type="application/javascript",
                        charset="utf-8", headers={"Cache-Control": "no-store, max-age=0"})


# --- The map ------------------------------------------------------------------------


def _wake(app, force: bool = False) -> None:
    if force:
        app["shared_state"].extra["force"] = True
    if app["wake"] is not None:
        app["wake"].set()


async def handle_scene(request: web.Request) -> web.Response:
    """{"scene": the map (src/scene.py) or None, "message": why not}."""
    app = request.app
    store, settings, state = app["store"], app["app_settings"], app["shared_state"]
    sc = store.scene if store is not None else None
    if settings is not None and sc and sc.get("postcode") != settings.data["postcode"]:
        sc = None  # (the old address's)
    message = None
    if sc is None:
        message = state.error or ("Set your postcode and house number in the add-on's Settings."
                                  if not (settings and settings.data["postcode"]) else "Making the map…")
    link = app["ha_link"]
    from src.live import entities
    # (the entities the dashboard card follows itself, and what they are now, for this page)
    ents = entities(link.settings) if link is not None else None
    # the other places, in the order set, with their maps (once made)
    pls = []
    pstore = app["pstore"]
    for pl in (settings.data.get("places") or []) if settings is not None else []:
        psc = pstore.get(pl["zone"]) if pstore is not None else None
        if psc:
            pls.append({"zone": pl["zone"], "side": pl["side"], "name": psc.get("name") or pl["zone"], "scene": psc})
    return web.json_response({"scene": sc, "places": pls, "message": message, "status": state.status, "entities": ents, "live": state.live},
                             dumps=lambda d: json.dumps(d, separators=(",", ":")))


async def handle_address(request: web.Request) -> web.Response:
    """{"postcode", "house_number"}: saved, and the map made for it."""
    settings = request.app["app_settings"]
    if settings is None:
        return _unavailable()
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Send a JSON object")
        out = settings.update({k: body[k] for k in ("postcode", "house_number", "radius") if k in body})
    except (ValueError, TypeError, json.JSONDecodeError) as err:
        return _bad_request(err)
    request.app["shared_state"].error = None
    _wake(request.app)
    return web.json_response({"status": "ok", **out})


async def handle_home(request: web.Request) -> web.Response:
    """{"id": a building on the map}: that's your house (the map's made again around it);
    {"id": null}: back to the one found from your address."""
    from src.places import PlaceError, picked_home
    app = request.app
    settings, store = app["app_settings"], app["store"]
    if settings is None or store is None:
        return _unavailable()
    try:
        body = await request.json()
        bid = body.get("id") if isinstance(body, dict) else None
        picked = None if bid is None else picked_home(store.scene, int(bid))
        out = settings.update({"picked": picked})
    except (ValueError, TypeError, PlaceError, json.JSONDecodeError) as err:
        return _bad_request(err)
    _wake(app)
    return web.json_response({"status": "ok", **out})


async def handle_places(request: web.Request) -> web.Response:
    """{"places": [{"zone", "side", "radius"}]}: the other places beside your map; their maps made."""
    settings = request.app["app_settings"]
    if settings is None:
        return _unavailable()
    try:
        body = await request.json()
        out = settings.update({"places": (body or {}).get("places")} if isinstance(body, dict) else body)
    except (ValueError, TypeError, json.JSONDecodeError) as err:
        return _bad_request(err)
    _wake(request.app)
    return web.json_response({"status": "ok", **out})


async def handle_zones(request: web.Request) -> web.Response:
    """Home Assistant's zones, for Settings › Other places: [{"entity_id", "name"}]."""
    link = request.app["ha_link"]
    try:
        states = await link.all_states() if link is not None else []
    except Exception as err:
        return web.json_response({"zones": [], "message": f"Couldn't read the zones: {err}"})
    zones = [{"entity_id": st["entity_id"], "name": (st.get("attributes") or {}).get("friendly_name") or st["entity_id"]}
             for st in states if str(st.get("entity_id", "")).startswith("zone.")]
    return web.json_response({"zones": sorted(zones, key=lambda z: z["name"].lower())})


async def handle_refresh(request: web.Request) -> web.Response:
    """The map made again now (OpenStreetMap read again)."""
    _wake(request.app, force=True)
    return web.json_response({"status": "ok"})


async def handle_get_state(request: web.Request) -> web.Response:
    return web.json_response(request.app["shared_state"].to_dict(), dumps=_dumps)


async def handle_events(request: web.Request) -> web.StreamResponse:
    """The state as Server-Sent Events: once straight away, then on every
    change (within ~1 s), and at least every EVENTS_KEEPALIVE seconds."""
    app = request.app
    stop: asyncio.Event = app["events_stop"]
    resp = web.StreamResponse(headers={
        "Content-Type": "text/event-stream", "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })
    await resp.prepare(request)
    last_sig, last_sent = None, 0.0
    app["event_clients"]["gui"] += 1
    try:
        while not stop.is_set():
            data = app["shared_state"].to_dict()
            sig = {k: v for k, v in data.items() if k not in LIVE_FIELDS}
            now = time.monotonic()
            if sig != last_sig or now - last_sent >= EVENTS_KEEPALIVE:
                await resp.write(f"data: {_dumps(data)}\n\n".encode())
                last_sig, last_sent = sig, now
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
    """End open event streams so shutting down isn't held up by them."""
    app["events_stop"].set()


async def handle_health(request: web.Request) -> web.Response:
    app = request.app
    out = app["health"].snapshot() if app["health"] is not None else {}
    link = app["ha_link"]
    out["home_assistant"] = None if link is None else {
        "available": link.available, "connected": link.connected, "error": link.error,
    }
    out["event_streams"] = dict(app["event_clients"])
    return web.json_response(out, dumps=_dumps)


# --- Your Home Assistant entities (src/ha_link.py) -------------------------------


async def handle_get_sensors(request: web.Request) -> web.Response:
    link = request.app["ha_link"]
    if link is None:
        return _unavailable()
    return web.json_response(link.snapshot(), dumps=_dumps)


async def handle_set_sensors(request: web.Request) -> web.Response:
    link = request.app["ha_link"]
    if link is None:
        return _unavailable()
    try:
        await link.update_settings(await request.json())
    except (ValueError, TypeError, json.JSONDecodeError) as err:
        return _bad_request(err)
    return web.json_response({"status": "ok", **link.snapshot()}, dumps=_dumps)


async def handle_sensor_entities(request: web.Request) -> web.Response:
    link = request.app["ha_link"]
    if link is None:
        return _unavailable()
    try:
        entities = await link.list_entities()
    except Exception as err:
        return web.json_response({"status": "error", "message": f"Couldn't list entities: {err}"}, status=502)
    return web.json_response({"entities": entities, "available": link.available}, dumps=_dumps)


# --- Settings made on the web page (src/app_settings.py) --------------------------


async def handle_get_settings(request: web.Request) -> web.Response:
    settings = request.app["app_settings"]
    if settings is None:
        return _unavailable()
    return web.json_response(dict(settings.data))


async def handle_set_settings(request: web.Request) -> web.Response:
    settings = request.app["app_settings"]
    if settings is None:
        return _unavailable()
    try:
        out = settings.update(await request.json())
    except (ValueError, TypeError, json.JSONDecodeError) as err:
        return _bad_request(err)
    return web.json_response({"status": "ok", **out})


# --- Diagnostics › Debug (src/debug_tools.py) ---------------------------------------


async def handle_debug_info(request: web.Request) -> web.Response:
    """The log level, the add-on's options (secrets hidden) and the last ?lines= log lines."""
    debug = request.app["debug"]
    if debug is None:
        return _unavailable()
    try:
        lines = int(request.query.get("lines", 200))
    except ValueError:
        lines = 200
    return web.json_response(debug.info(lines), dumps=_dumps)


async def _debug_call(request: web.Request, apply) -> web.Response:
    debug = request.app["debug"]
    if debug is None:
        return _unavailable()
    try:
        body = await request.json() if request.can_read_body else {}
        if not isinstance(body, dict):
            raise ValueError("Send a JSON object")
        out = apply(debug, body)
        if asyncio.iscoroutine(out):
            out = await out
    except (ValueError, TypeError, json.JSONDecodeError) as err:
        return _bad_request(err)
    return web.json_response({"status": "ok", **(out or {})}, dumps=_dumps)


async def handle_debug_log_level(request: web.Request) -> web.Response:
    """{"level": "debug"|"info"|"warning"|"error"}, saved (src/app_settings.py)."""
    return await _debug_call(request, lambda d, b: d.set_log_level(b.get("level")))


async def handle_debug_restart(request: web.Request) -> web.Response:
    return await _debug_call(request, lambda d, b: d.restart())
