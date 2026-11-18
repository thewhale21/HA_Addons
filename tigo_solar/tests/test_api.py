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
    return SharedState(status="Running", panels=[{"id": 1, "label": "A1"}, {"id": 2, "label": "A2"}])


@pytest_asyncio.fixture
async def client(aiohttp_client, state, tmp_path):
    settings = AppSettings(str(tmp_path))
    app = create_api_app(state, ha_link=HaLink(str(tmp_path), state, token=""), health=Health("1.2.3"),
                         debug=DebugTools(settings=settings), app_settings=settings)
    return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_page_and_state(client):
    resp = await client.get("/")
    assert resp.status == 200 and "Tigo Solar" in await resp.text()
    data = await (await client.get("/api/state")).json()
    assert data["status"] == "Running" and len(data["panels"]) == 2


@pytest.mark.asyncio
async def test_health(client):
    data = await (await client.get("/api/health")).json()
    assert data["version"] == "1.2.3" and data["home_assistant"]["available"] is False


@pytest.mark.asyncio
async def test_chart_and_layout(aiohttp_client, state, tmp_path):
    from src.layout import Layout
    from src.store import Store

    store = Store(None)
    store.put_panel_energy("2026-11-17", {1: 300, 2: 250})
    store.put_system_energy([("2026-11-17", 550, 500, 50)])
    layout = Layout(str(tmp_path))
    app = create_api_app(state, store=store, layout=layout)
    client = await aiohttp_client(app)
    data = await (await client.get("/api/chart?view=week&day=2026-11-17")).json()
    assert data["whole"] and data["total_wh"] == 550 and data["panels"] == {"1": 300.0, "2": 250.0}
    data = await (await client.get("/api/chart?view=week&day=2026-11-17&panels=2")).json()
    assert not data["whole"] and data["total_wh"] == 250
    assert (await client.get("/api/chart?view=decade&day=2026-11-17")).status == 400
    store.put_system_power([("2026-11-17 12:00", 400.0, 380.0, 20.0), ("2026-11-17 12:10", 600.0, 570.0, 30.0)])
    data = await (await client.get("/api/year?year=2026")).json()
    assert data["days"] == ["2026-11-17"] and data["made"] == [[500.0]] and data["reclaimed"] == [[25.0]]
    assert (await client.get("/api/year?year=abc")).status == 400
    data = await (await client.get("/api/year?year=2026&month=11")).json()
    assert data["step"] == 15 and data["days"] == ["2026-11-17"] and data["made"] == [[500.0]]
    resp = await client.post("/api/layout", json={"moved": {"1": {"left": 10, "top": 20}}})
    assert resp.status == 200 and layout.moved == {1: {"left": 10.0, "top": 20.0}}
    assert (await client.post("/api/layout", json={"moved": {"x": {}}})).status == 400


@pytest.mark.asyncio
async def test_settings_and_log_level(client):
    resp = await client.post("/api/settings", json={"log_level": "warning"})
    assert resp.status == 200 and (await resp.json())["log_level"] == "warning"
    assert (await client.post("/api/settings", json={"log_level": "loud"})).status == 400
    resp = await client.post("/api/debug/log_level", json={"level": "info"})
    assert resp.status == 200
    data = await (await client.get("/api/debug/info?lines=5")).json()
    assert data["log_level"] == "info"
