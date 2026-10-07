"""The web page's API (needs aiohttp and pytest-aiohttp: requirements-dev.txt)."""

import pytest
import pytest_asyncio

from src.api import create_api_app
from src.app_settings import AppSettings
from src.debug_tools import DebugTools
from src.ha_link import HaLink
from src.health import Health
from src.shared_state import SharedState


@pytest.fixture
def state():
    return SharedState(status="Running", ticks=3)


@pytest_asyncio.fixture
async def client(aiohttp_client, state, tmp_path):
    settings = AppSettings(str(tmp_path))
    app = create_api_app(state, ha_link=HaLink(str(tmp_path), state, token=""), health=Health("1.2.3"),
                         debug=DebugTools(settings=settings), app_settings=settings)
    return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_page_and_state(client):
    resp = await client.get("/")
    assert resp.status == 200 and "Add-on Template" in await resp.text()
    data = await (await client.get("/api/state")).json()
    assert data["status"] == "Running" and data["ticks"] == 3


@pytest.mark.asyncio
async def test_health(client):
    data = await (await client.get("/api/health")).json()
    assert data["version"] == "1.2.3" and data["home_assistant"]["available"] is False


@pytest.mark.asyncio
async def test_entity_settings(client):
    resp = await client.post("/api/sensors", json={"example_entity": "sensor.temp"})
    assert resp.status == 200 and (await resp.json())["settings"]["example_entity"] == "sensor.temp"
    resp = await client.post("/api/sensors", json={"example_entity": "automation.x"})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_settings_and_log_level(client):
    resp = await client.post("/api/settings", json={"log_level": "warning"})
    assert resp.status == 200 and (await resp.json())["log_level"] == "warning"
    assert (await client.post("/api/settings", json={"log_level": "loud"})).status == 400
    resp = await client.post("/api/debug/log_level", json={"level": "info"})
    assert resp.status == 200
    data = await (await client.get("/api/debug/info?lines=5")).json()
    assert data["log_level"] == "info"
