import pytest
import pytest_asyncio
from src.api import create_api_app
from src.shared_state import SharedState


@pytest.fixture
def shared_state():
    return SharedState()


@pytest.fixture
def mock_commands():
    calls = []

    async def plug():
        calls.append("plug")

    async def unplug():
        calls.append("unplug")

    async def set_current(amps: int):
        calls.append(("set_current", amps))

    return {"plug": plug, "unplug": unplug, "set_current": set_current, "calls": calls}


@pytest.fixture
def app(shared_state, mock_commands):
    return create_api_app(
        shared_state,
        on_plug=mock_commands["plug"],
        on_unplug=mock_commands["unplug"],
        on_set_current=mock_commands["set_current"],
    )


@pytest_asyncio.fixture
async def client(aiohttp_client, app):
    return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_get_state(client, shared_state):
    shared_state.state = "Charging"
    shared_state.connected_to_server = True
    resp = await client.get("/api/state")
    assert resp.status == 200
    data = await resp.json()
    assert data["state"] == "Charging"
    assert data["connected_to_server"] is True


@pytest.mark.asyncio
async def test_post_plug(client, mock_commands):
    resp = await client.post("/api/plug")
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "ok"
    assert "plug" in mock_commands["calls"]


@pytest.mark.asyncio
async def test_post_unplug(client, mock_commands):
    resp = await client.post("/api/unplug")
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "ok"
    assert "unplug" in mock_commands["calls"]


@pytest.mark.asyncio
async def test_post_current_valid(client, mock_commands):
    resp = await client.post("/api/current", json={"amps": 16})
    assert resp.status == 200
    assert ("set_current", 16) in mock_commands["calls"]


@pytest.mark.asyncio
async def test_post_current_invalid(client):
    resp = await client.post("/api/current", json={"amps": 15})
    assert resp.status == 400
    data = await resp.json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_post_current_missing_body(client):
    resp = await client.post("/api/current")
    assert resp.status == 400


@pytest.mark.asyncio
async def test_get_state_refreshes_live_power(aiohttp_client, shared_state, mock_commands):
    """Each poll asks the charger for live power before answering."""
    def refresh():
        shared_state.power_kw = 3.6

    app = create_api_app(
        shared_state,
        on_plug=mock_commands["plug"],
        on_unplug=mock_commands["unplug"],
        on_set_current=mock_commands["set_current"],
        on_refresh=refresh,
    )
    client = await aiohttp_client(app)
    resp = await client.get("/api/state")
    assert resp.status == 200
    assert (await resp.json())["power_kw"] == 3.6


# --- 0.9.4: SoC and push updates ---


@pytest.mark.asyncio
async def test_post_soc(aiohttp_client, shared_state, mock_commands):
    received = []

    async def set_soc(soc):
        received.append(soc)

    app = create_api_app(
        shared_state,
        on_plug=mock_commands["plug"],
        on_unplug=mock_commands["unplug"],
        on_set_current=mock_commands["set_current"],
        on_set_soc=set_soc,
    )
    client = await aiohttp_client(app)
    assert (await client.post("/api/soc", json={"soc": 81})).status == 200
    assert (await client.post("/api/soc", json={"soc": None})).status == 200
    assert (await client.post("/api/soc", json={"soc": 150})).status == 400
    assert (await client.post("/api/soc", data="nope")).status == 400
    assert received == [81.0, None]


@pytest.mark.asyncio
async def test_events_stream_sends_state(client, shared_state):
    shared_state.state = "Charging"
    resp = await client.get("/api/events")
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("text/event-stream")
    line = b""
    while not line.startswith(b"data:"):
        line = await resp.content.readline()
    import json as _json
    assert _json.loads(line[5:])["state"] == "Charging"
    resp.close()


# --- 1.1.0: web GUI endpoints ---


def _gui_app(shared_state, mock_commands):
    from src.gui_data import GuiSources, MessageLog, PowerHistory
    from src.ha_history import ChartHistory
    log = MessageLog()
    log.record('[2,"a","Heartbeat",{}]', incoming=False)
    log.record('[3,"a",{"currentTime":"2026-10-02T15:00:00Z"}]', incoming=True)
    recent = PowerHistory()
    recent.sample(shared_state)
    gui = GuiSources(
        message_log=log, history=ChartHistory(None, soc_entity=lambda: None, recent=recent),
        sessions=lambda: {"current": None, "history": [{"transaction_id": 1}]},
        provider=lambda: {"configuration": [], "charging_profiles": []},
        health=lambda: {"version": "1.1.0", "uptime_s": 5},
    )
    return create_api_app(
        shared_state, on_plug=mock_commands["plug"], on_unplug=mock_commands["unplug"],
        on_set_current=mock_commands["set_current"], gui=gui,
    )


@pytest.mark.asyncio
async def test_gui_endpoints(aiohttp_client, shared_state, mock_commands):
    client = await aiohttp_client(_gui_app(shared_state, mock_commands))
    data = await (await client.get("/api/messages")).json()
    assert [m["type"] for m in data["messages"]] == ["call", "result"] and data["last_seq"] == 2
    data = await (await client.get("/api/messages?after=1")).json()
    assert [m["seq"] for m in data["messages"]] == [2]
    data = await (await client.get("/api/messages?after=99")).json()  # add-on restarted
    assert len(data["messages"]) == 2
    assert (await (await client.get("/api/sessions")).json())["history"][0]["transaction_id"] == 1
    assert len((await (await client.get("/api/history?since=0")).json())["samples"]) == 1
    assert (await (await client.get("/api/history?since=9999999999")).json())["samples"] == []
    assert (await (await client.get("/api/history?since=0&resolution=long")).json())["samples"] == []  # no HA here
    assert (await (await client.get("/api/provider")).json())["configuration"] == []
    days = (await (await client.get("/api/energy/daily?days=3")).json())["days"]
    assert [d["kwh"] for d in days] == [0.0, 0.0, 0.0]  # no HA, no sessions with energy
    health = await (await client.get("/api/health")).json()
    assert health["version"] == "1.1.0"
    assert health["event_streams"] == {"gui": 0}


@pytest.mark.asyncio
async def test_gui_endpoints_without_gui(client):
    assert (await client.get("/api/messages")).status == 501
    assert (await client.get("/api/health")).status == 501


@pytest.mark.asyncio
async def test_event_streams_counted_by_client(aiohttp_client, shared_state, mock_commands):
    app = _gui_app(shared_state, mock_commands)
    client = await aiohttp_client(app)
    resp = await client.get("/api/events?client=gui")
    line = b""
    while not line.startswith(b"data:"):
        line = await resp.content.readline()
    assert app["event_clients"] == {"gui": 1}
    resp.close()


# --- 2.0.0: schedule and auto re-plug ---


@pytest.mark.asyncio
async def test_automation_endpoints(aiohttp_client, shared_state, mock_commands, tmp_path):
    from src.automation import Automation
    automation = Automation(str(tmp_path))
    app = create_api_app(
        shared_state, on_plug=mock_commands["plug"], on_unplug=mock_commands["unplug"],
        on_set_current=mock_commands["set_current"], automation=automation,
    )
    client = await aiohttp_client(app)
    data = await (await client.get("/api/automation")).json()
    assert data["schedule"]["enabled"] is False and data["replug"]["after_min"] == 10
    resp = await client.post("/api/automation/schedule", json={
        "enabled": True, "entries": [{"time": "23:30", "action": "plug", "days": [0, 1]}],
    })
    assert resp.status == 200
    assert shared_state.schedule_enabled is True
    assert shared_state.schedule_next["action"] == "plug"
    resp = await client.post("/api/automation/schedule", json={"entries": [{"time": "25:00", "action": "plug"}]})
    assert resp.status == 400
    assert len(automation.entries) == 1
    resp = await client.post("/api/automation/replug", json={"after_min": 15, "attempts": 2})
    assert (await resp.json())["replug"]["after_min"] == 15
    assert shared_state.replug["attempts"] == 2
    assert (await client.post("/api/automation/replug", json={"after_min": 0})).status == 400
    assert (await client.post("/api/automation/replug", data="nope")).status == 400


# --- 2.0.0: your HA sensors ---


@pytest.mark.asyncio
async def test_sensor_settings_endpoints(aiohttp_client, shared_state, mock_commands, tmp_path):
    from src.ha_link import HaLink
    calls = []

    async def set_soc(soc):
        calls.append(("soc", soc))

    link = HaLink(str(tmp_path), shared_state, lambda kw: calls.append(("power", kw)), set_soc,
                  mock_commands["plug"], token="")
    app = create_api_app(
        shared_state, on_plug=mock_commands["plug"], on_unplug=mock_commands["unplug"],
        on_set_current=mock_commands["set_current"], ha_link=link,
    )
    client = await aiohttp_client(app)
    data = await (await client.get("/api/sensors")).json()
    assert data["configured"] is False and data["available"] is False
    resp = await client.post("/api/sensors", json={"soc_entity": "sensor.soc"})
    assert (await resp.json())["settings"]["soc_entity"] == "sensor.soc"
    # The Simulation tab
    resp = await client.post("/api/sensors", json={"auto_plug": True, "auto_plug_soc": 25})
    assert (await resp.json())["monitored_soc"]["threshold"] == 25
    assert (await client.post("/api/sensors", json={"plug_entity": "sensor.x"})).status == 400
    data = await (await client.get("/api/sensors/entities")).json()
    assert data == {"entities": [], "available": False}

@pytest.mark.asyncio
async def test_post_ramp(aiohttp_client, shared_state, mock_commands):
    calls = []

    def set_ramp(delay, ramp):
        if delay > 60:
            raise ValueError("Start delay and ramp-up must be 0 to 60 seconds")
        calls.append((delay, ramp))

    app = create_api_app(
        shared_state, on_plug=mock_commands["plug"], on_unplug=mock_commands["unplug"],
        on_set_current=mock_commands["set_current"], on_set_ramp=set_ramp,
    )
    client = await aiohttp_client(app)
    assert (await client.post("/api/ramp", json={"start_delay_s": 2, "ramp_up_s": 8})).status == 200
    assert calls == [(2.0, 8.0)]
    assert (await client.post("/api/ramp", json={"start_delay_s": 99, "ramp_up_s": 0})).status == 400
    assert (await client.post("/api/ramp", json={"start_delay_s": 1})).status == 400


@pytest.mark.asyncio
async def test_index_is_never_cached(client):
    resp = await client.get("/")
    assert resp.status == 200
    assert "no-store" in resp.headers["Cache-Control"]
    assert "Last-Modified" not in resp.headers and "ETag" not in resp.headers
    assert "OCPP Charge Proxy" in await resp.text()
