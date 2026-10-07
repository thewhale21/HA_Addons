"""Integration test: full OCPP client flow with a mock server."""

from __future__ import annotations

import asyncio
import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock

from ocpp.routing import on
from ocpp.v16 import ChargePoint as BaseChargePoint
from ocpp.v16 import call, call_result
from ocpp.v16.enums import (
    Action,
    ChargePointErrorCode,
    ChargePointStatus,
    RegistrationStatus,
    RemoteStartStopStatus,
)

from src.client import ChargePoint
from src.persistence import Persistence


# ---------------------------------------------------------------------------
# Fake WebSocket connection using two asyncio queues
# ---------------------------------------------------------------------------

class _FakeSide:
    def __init__(self, send_q: asyncio.Queue, recv_q: asyncio.Queue):
        self._send_q = send_q
        self._recv_q = recv_q

    async def send(self, msg):
        await self._send_q.put(msg)

    async def recv(self):
        return await self._recv_q.get()


class FakeConnection:
    def __init__(self):
        self.client_to_server: asyncio.Queue = asyncio.Queue()
        self.server_to_client: asyncio.Queue = asyncio.Queue()

    def client_side(self) -> _FakeSide:
        return _FakeSide(self.client_to_server, self.server_to_client)

    def server_side(self) -> _FakeSide:
        return _FakeSide(self.server_to_client, self.client_to_server)


# ---------------------------------------------------------------------------
# Mock OCPP server
# ---------------------------------------------------------------------------

class MockServer(BaseChargePoint):
    """A minimal CSMS that records incoming calls and responds."""

    def __init__(self, id: str, connection):
        super().__init__(id, connection)
        self.boot_received = asyncio.Event()
        self.start_tx_received = asyncio.Event()
        self.stop_tx_received = asyncio.Event()
        self.last_start_tx: call.StartTransactionPayload | None = None
        self.last_stop_tx: call.StopTransactionPayload | None = None

    @on(Action.BootNotification)
    async def on_boot_notification(self, charge_point_model, charge_point_vendor, **kw):
        self.boot_received.set()
        return call_result.BootNotificationPayload(
            current_time=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            interval=30,
            status=RegistrationStatus.accepted,
        )

    @on(Action.StatusNotification)
    async def on_status_notification(self, connector_id, error_code, status, **kw):
        return call_result.StatusNotificationPayload()

    @on(Action.Heartbeat)
    async def on_heartbeat(self, **kw):
        return call_result.HeartbeatPayload(
            current_time=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

    @on(Action.MeterValues)
    async def on_meter_values(self, connector_id, meter_value=None, **kw):
        return call_result.MeterValuesPayload()

    @on(Action.StartTransaction)
    async def on_start_transaction(self, connector_id, id_tag, meter_start, timestamp, **kw):
        self.last_start_tx = {
            "connector_id": connector_id,
            "id_tag": id_tag,
            "meter_start": meter_start,
            "timestamp": timestamp,
        }
        self.start_tx_received.set()
        return call_result.StartTransactionPayload(
            transaction_id=42,
            id_tag_info={"status": "Accepted"},
        )

    @on(Action.StopTransaction)
    async def on_stop_transaction(self, transaction_id, meter_stop, timestamp, **kw):
        self.last_stop_tx = {
            "id_tag": kw.get("id_tag"),
            "transaction_id": transaction_id,
            "meter_stop": meter_stop,
            "timestamp": timestamp,
        }
        self.stop_tx_received.set()
        return call_result.StopTransactionPayload(
            id_tag_info={"status": "Accepted"},
        )


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_ocpp_flow(tmp_path):
    """Boot -> RemoteStart -> StartTransaction -> RemoteStop -> StopTransaction."""

    # --- Set up fake connection ---
    conn = FakeConnection()

    # --- Build client dependencies ---
    persistence = Persistence(data_dir=str(tmp_path))

    # --- Create client and server ---
    client = ChargePoint(
        id="CP_TEST",
        connection=conn.client_side(),
        persistence=persistence,
        current_amps=32,
    )

    server = MockServer(id="CP_TEST", connection=conn.server_side())

    # --- Run both start() loops as background tasks ---
    client_task = asyncio.create_task(client.start())
    server_task = asyncio.create_task(server.start())

    try:
        # 1. Boot notification
        interval = await asyncio.wait_for(
            client.send_boot_notification(model="TestModel", vendor="TestVendor"),
            timeout=5,
        )
        assert interval == 30
        assert server.boot_received.is_set()
        assert client.state == ChargePointStatus.available

        # 2. Simulate car plugged in (must be Preparing for RemoteStart)
        client.state = ChargePointStatus.preparing
        client._shared_state.state = client.state
        client._shared_state.plugged_in = True

        # 3. RemoteStartTransaction (server -> client)
        remote_start_resp = await asyncio.wait_for(
            server.call(call.RemoteStartTransactionPayload(id_tag="TEST_TAG")),
            timeout=5,
        )
        assert remote_start_resp.status == RemoteStartStopStatus.accepted

        # Wait for the background StartTransaction to arrive at the server
        # (state transitions: Preparing -> Charging)
        await asyncio.wait_for(server.start_tx_received.wait(), timeout=5)
        assert server.last_start_tx is not None
        assert server.last_start_tx["id_tag"] == "TEST_TAG"  # echoed from RemoteStart
        assert server.last_start_tx["meter_start"] == 0  # fresh persistence

        # The client sets _transaction_id after processing the response in a
        # background task, so yield control until it propagates.
        for _ in range(50):
            if client._transaction_id is not None:
                break
            await asyncio.sleep(0.01)
        assert client._transaction_id == 42

        # 3. RemoteStopTransaction (server -> client)
        remote_stop_resp = await asyncio.wait_for(
            server.call(
                call.RemoteStopTransactionPayload(transaction_id=42),
            ),
            timeout=5,
        )
        assert remote_stop_resp.status == RemoteStartStopStatus.accepted

        # Wait for the background StopTransaction to arrive at the server
        await asyncio.wait_for(server.stop_tx_received.wait(), timeout=5)
        assert server.last_stop_tx is not None
        assert server.last_stop_tx["transaction_id"] == 42
        assert server.last_stop_tx["id_tag"] == "TEST_TAG"
        assert server.last_stop_tx["meter_stop"] == 0  # no time elapsed, no energy added

    finally:
        client_task.cancel()
        server_task.cancel()
        # Suppress CancelledError from the background tasks
        for task in (client_task, server_task):
            try:
                await task
            except asyncio.CancelledError:
                pass
