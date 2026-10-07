import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from ocpp.v16.enums import (
    ChargePointStatus, RegistrationStatus, RemoteStartStopStatus, Action,
)
from ocpp.v16 import call, call_result

from src.client import ChargePoint


@pytest.fixture
def mock_connection():
    conn = AsyncMock()
    conn.send = AsyncMock()
    conn.recv = AsyncMock()
    return conn


@pytest.fixture
def mock_persistence():
    p = MagicMock()
    p.load_energy_register_wh.return_value = 5000
    p.save_energy_register_wh = MagicMock()
    return p


async def _settle(rounds: int = 20) -> None:
    """Let tasks started by a handler (asyncio.create_task) run to completion."""
    for _ in range(rounds):
        await asyncio.sleep(0)


def make_cp(connection, persistence):
    cp = ChargePoint(
        id="CP001",
        connection=connection,
        persistence=persistence,
        current_amps=32,
    )
    return cp


def test_initial_state(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    assert cp.state == ChargePointStatus.available


def test_remote_start_when_available_rejected(mock_connection, mock_persistence):
    """RemoteStart rejected when no car plugged in (Available state)."""
    cp = make_cp(mock_connection, mock_persistence)
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(
        cp.on_remote_start_transaction(id_tag="TAG001", connector_id=1)
    )
    loop.close()
    assert result.status == RemoteStartStopStatus.rejected


def test_remote_start_when_preparing(mock_connection, mock_persistence):
    """RemoteStart accepted when car is plugged in (Preparing state)."""
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _call_recorder()
    cp.state = ChargePointStatus.preparing

    async def scenario():
        result = await cp.on_remote_start_transaction(id_tag="TAG001", connector_id=1)
        await _settle()  # let the background StartTransaction finish
        return result

    result = _run(scenario())
    assert result.status == RemoteStartStopStatus.accepted
    assert any(isinstance(r, _call.StartTransactionPayload) for r in sent)
    assert cp.state == ChargePointStatus.charging


def test_remote_start_when_already_charging(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.state = ChargePointStatus.charging
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(
        cp.on_remote_start_transaction(id_tag="TAG001", connector_id=1)
    )
    loop.close()
    assert result.status == RemoteStartStopStatus.rejected


def test_remote_stop_mismatched_transaction_id_accepted(mock_connection, mock_persistence):
    """Octopus workaround: RemoteStop with a different tx id still stops the only active tx."""
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _call_recorder()
    cp._transaction_id = 1790607644
    cp.state = ChargePointStatus.charging

    async def scenario():
        result = await cp.on_remote_stop_transaction(transaction_id=1)
        await _settle()  # let the background StopTransaction finish
        return result

    result = _run(scenario())
    assert result.status == RemoteStartStopStatus.accepted
    stop = [r for r in sent if isinstance(r, _call.StopTransactionPayload)][0]
    assert stop.transaction_id == 1790607644  # the active one, not the server's 1


def test_remote_stop_no_transaction_rejected(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(
        cp.on_remote_stop_transaction(transaction_id=1)
    )
    loop.close()
    assert result.status == RemoteStartStopStatus.rejected


def _config_value(cp, key):
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(cp.on_get_configuration(key=[key]))
    loop.close()
    return result.configuration_key[0]["value"]


def test_heartbeat_interval_reported_after_set(mock_connection, mock_persistence):
    """Interval from BootNotification is what GetConfiguration reports."""
    cp = make_cp(mock_connection, mock_persistence)
    assert _config_value(cp, "HeartbeatInterval") == "30"
    cp._set_heartbeat_interval(10)
    assert cp._heartbeat_interval == 10
    assert _config_value(cp, "HeartbeatInterval") == "10"


def test_change_configuration_heartbeat_interval(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(
        cp.on_change_configuration(key="HeartbeatInterval", value="120")
    )
    loop.close()
    assert result.status == "Accepted"
    assert cp._heartbeat_interval == 120
    assert _config_value(cp, "HeartbeatInterval") == "120"


def test_change_configuration_heartbeat_interval_invalid(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    loop = asyncio.new_event_loop()
    for bad in ("0", "-5", "abc"):
        result = loop.run_until_complete(
            cp.on_change_configuration(key="HeartbeatInterval", value=bad)
        )
        assert result.status == "Rejected"
    loop.close()
    assert cp._heartbeat_interval == 30
    assert _config_value(cp, "HeartbeatInterval") == "30"


def test_heartbeat_loop_picks_up_new_interval(mock_connection, mock_persistence):
    """Changing the interval mid-sleep takes effect without waiting out the old one."""
    cp = make_cp(mock_connection, mock_persistence)
    cp.call = AsyncMock()

    async def scenario():
        task = asyncio.create_task(cp.heartbeat_loop(300))
        await asyncio.sleep(0.05)
        cp._set_heartbeat_interval(0.1)
        await asyncio.sleep(0.35)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    loop = asyncio.new_event_loop()
    loop.run_until_complete(scenario())
    loop.close()
    assert cp.call.await_count >= 2


# --- Clock-aligned meter values ---

import datetime as _dt
from src.client import _next_aligned


def _utc(h, m, sec=0):
    return _dt.datetime(2026, 10, 1, h, m, sec, tzinfo=_dt.timezone.utc)


def test_next_aligned_mid_slot():
    delay, boundary = _next_aligned(_utc(15, 7, 30), 900)
    assert delay == 450
    assert boundary == _utc(15, 15)


def test_next_aligned_exactly_on_boundary_is_full_interval():
    delay, boundary = _next_aligned(_utc(15, 15), 900)
    assert delay == 900
    assert boundary == _utc(15, 30)


def test_next_aligned_rolls_to_midnight():
    delay, boundary = _next_aligned(_utc(23, 50), 900)
    assert delay == 600
    assert boundary == _dt.datetime(2026, 10, 2, tzinfo=_dt.timezone.utc)


def test_next_aligned_uneven_interval_caps_at_midnight():
    # 700s doesn't divide 86400; last slot of the day ends at midnight
    delay, boundary = _next_aligned(_utc(23, 59, 50), 700)
    assert delay == 10
    assert boundary == _dt.datetime(2026, 10, 2, tzinfo=_dt.timezone.utc)


def test_change_configuration_clock_aligned(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    assert _config_value(cp, "ClockAlignedDataInterval") == "0"
    loop = asyncio.new_event_loop()
    r1 = loop.run_until_complete(
        cp.on_change_configuration(key="ClockAlignedDataInterval", value="900"))
    r2 = loop.run_until_complete(cp.on_change_configuration(
        key="MeterValuesAlignedData",
        value="Energy.Active.Import.Register, Power.Active.Import"))
    r3 = loop.run_until_complete(
        cp.on_change_configuration(key="ClockAlignedDataInterval", value="-1"))
    loop.close()
    assert r1.status == "Accepted" and r2.status == "Accepted"
    assert r3.status == "Rejected"
    assert cp._clock_aligned_interval == 900
    assert _config_value(cp, "ClockAlignedDataInterval") == "900"
    assert cp._aligned_measurands == [
        "Energy.Active.Import.Register", "Power.Active.Import",
    ]


def _sent_payload(cp):
    return cp.call.await_args.args[0]


def test_clock_aligned_idle_payload(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call = AsyncMock()
    cp._aligned_measurands = ["Energy.Active.Import.Register", "Power.Active.Import"]
    loop = asyncio.new_event_loop()
    loop.run_until_complete(cp.send_clock_aligned_meter_values(_utc(15, 15)))
    loop.close()
    payload = _sent_payload(cp)
    assert payload.transaction_id is None
    mv = payload.meter_value[0]
    assert mv["timestamp"] == "2026-10-01T15:15:00Z"
    assert {sv["measurand"]: sv["value"] for sv in mv["sampledValue"]} == {
        "Energy.Active.Import.Register": "5000.0",
        "Power.Active.Import": "0.0",
    }
    assert all(sv["context"] == "Sample.Clock" for sv in mv["sampledValue"])


def test_clock_aligned_charging_includes_transaction(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call = AsyncMock()
    cp._aligned_measurands = ["Energy.Active.Import.Register", "Power.Active.Import"]
    cp._transaction_id = 1790866844
    cp.state = ChargePointStatus.charging
    cp._charger_sim.start_charging()
    loop = asyncio.new_event_loop()
    loop.run_until_complete(cp.send_clock_aligned_meter_values(_utc(15, 15)))
    loop.close()
    payload = _sent_payload(cp)
    assert payload.transaction_id == 1790866844
    values = {sv["measurand"]: float(sv["value"]) for sv in payload.meter_value[0]["sampledValue"]}
    assert values["Power.Active.Import"] > 0


def test_aligned_and_periodic_share_energy_register(mock_connection, mock_persistence):
    """Two readings over the same span add the same energy as one."""
    cp = make_cp(mock_connection, mock_persistence)
    cp.state = ChargePointStatus.charging
    cp._charger_sim.start_charging()
    cp._power_override = 7.0  # fixed power for a deterministic result
    cp._last_meter_time -= 3600  # one hour ago
    cp._take_reading()
    after_one = cp._energy_register_wh
    cp._take_reading()  # immediately again: ~no extra time elapsed
    assert after_one - 5000 > 0
    assert cp._energy_register_wh - after_one <= 1


# --- Energy accounting at charging state changes ---

from ocpp.v16 import call as _call


def _call_recorder(transaction_id=4242):
    """AsyncMock for cp.call that records requests and answers StartTransaction."""
    sent = []

    async def fake_call(request):
        sent.append(request)
        if isinstance(request, _call.StartTransactionPayload):
            return MagicMock(transaction_id=transaction_id)
        return MagicMock()

    return AsyncMock(side_effect=fake_call), sent


def test_start_transaction_does_not_add_phantom_energy(mock_connection, mock_persistence):
    """Idle time before a start must not be billed at charging power."""
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _call_recorder()
    cp.state = ChargePointStatus.preparing
    cp._power_override = 5.0
    cp._last_meter_time -= 3600  # last reading was an hour ago, while idle

    loop = asyncio.new_event_loop()
    loop.run_until_complete(cp._do_start_transaction())
    start = [r for r in sent if isinstance(r, _call.StartTransactionPayload)][0]
    assert start.meter_start == 5000
    loop.run_until_complete(cp.send_meter_values())  # immediately after start
    loop.close()

    assert cp.state == ChargePointStatus.charging
    assert cp._energy_register_wh - 5000 <= 1  # previously ~+5000 Wh phantom


def test_stop_transaction_counts_energy_since_last_reading(mock_connection, mock_persistence):
    """meterStop includes energy delivered after the last periodic reading."""
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _call_recorder()
    cp.state = ChargePointStatus.charging
    cp._charger_sim.start_charging()
    cp._transaction_id = 4242
    cp._transaction_start_energy_wh = 5000
    cp._power_override = 5.0
    cp._last_meter_time -= 1800  # 30 min charging since the last reading

    loop = asyncio.new_event_loop()
    loop.run_until_complete(cp._do_stop_transaction())
    loop.close()

    stop = [r for r in sent if isinstance(r, _call.StopTransactionPayload)][0]
    assert 7400 <= stop.meter_stop <= 7600  # 5000 + 5 kW x 0.5 h = 7500


def test_unlock_connector_captures_energy_before_state_change(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _call_recorder()
    cp.state = ChargePointStatus.charging
    cp._charger_sim.start_charging()
    cp._transaction_id = 4242
    cp._power_override = 5.0
    cp._last_meter_time -= 1800

    async def scenario():
        await cp.on_unlock_connector(connector_id=1)
        await asyncio.sleep(0)  # let the stop task run
        await asyncio.sleep(0)

    loop = asyncio.new_event_loop()
    loop.run_until_complete(scenario())
    loop.close()

    stop = [r for r in sent if isinstance(r, _call.StopTransactionPayload)][0]
    assert 7400 <= stop.meter_stop <= 7600


# --- StopTransaction reasons ---

from ocpp.v16.enums import Reason as _Reason


def _stop_reason_after(cp, coro_factory):
    cp.call, sent = _call_recorder()
    cp.state = ChargePointStatus.charging
    cp._charger_sim.start_charging()
    cp._transaction_id = 4242

    async def scenario():
        await coro_factory()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    loop = asyncio.new_event_loop()
    loop.run_until_complete(scenario())
    loop.close()
    return [r for r in sent if isinstance(r, _call.StopTransactionPayload)][0].reason


def test_remote_stop_reason_is_remote(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    assert _stop_reason_after(
        cp, lambda: cp.on_remote_stop_transaction(transaction_id=4242)
    ) == _Reason.remote


def test_unlock_connector_reason(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    assert _stop_reason_after(
        cp, lambda: cp.on_unlock_connector(connector_id=1)
    ) == _Reason.unlock_command


def test_soft_reset_reason(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    assert _stop_reason_after(cp, lambda: cp.on_reset(type="Soft")) == _Reason.soft_reset


def test_unplug_reason_is_ev_disconnected(mock_connection, mock_persistence):
    """What do_unplug in __main__ passes when HA unplugs the car."""
    cp = make_cp(mock_connection, mock_persistence)
    assert _stop_reason_after(
        cp, lambda: cp._do_stop_transaction(
            final_state=ChargePointStatus.available,
            reason=_Reason.ev_disconnected,
        )
    ) == _Reason.ev_disconnected


# --- 0.7.0: OCPP conformance fixes ---

from ocpp.v16.enums import RegistrationStatus as _RegStatus

OCTOPUS_TAG = "ffffffffffffff7f"
OCTOPUS_SAMPLED = (
    "Energy.Active.Import.Register,Power.Active.Import,Frequency,Power.Offered,"
    "Current.Offered,SoC,Energy.Active.Export.Register,Power.Active.Export"
)


def _boot_recorder(interval=10):
    """cp.call fake: accepts BootNotification, records everything."""
    sent = []

    async def fake_call(request):
        sent.append(request)
        if isinstance(request, _call.BootNotificationPayload):
            return MagicMock(status=_RegStatus.accepted, interval=interval)
        if isinstance(request, _call.StartTransactionPayload):
            return MagicMock(transaction_id=4242)
        return MagicMock()

    return AsyncMock(side_effect=fake_call), sent


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_id_tag_echoed_in_start_and_stop(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _call_recorder()
    cp.state = ChargePointStatus.preparing

    async def scenario():
        await cp.on_remote_start_transaction(id_tag=OCTOPUS_TAG, connector_id=1)
        for _ in range(5):
            await asyncio.sleep(0)
        await cp._do_stop_transaction()

    _run(scenario())
    start = [r for r in sent if isinstance(r, _call.StartTransactionPayload)][0]
    stop = [r for r in sent if isinstance(r, _call.StopTransactionPayload)][0]
    assert start.id_tag == OCTOPUS_TAG
    assert stop.id_tag == OCTOPUS_TAG
    assert stop.transaction_data is None  # no empty list sent


def test_start_sequence_is_preparing_to_charging(mock_connection, mock_persistence):
    """No Available / SuspendedEV / connector-0 statuses during a start."""
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _call_recorder()
    cp.state = ChargePointStatus.preparing
    cp._pending_id_tag = OCTOPUS_TAG

    _run(cp._do_start_transaction())
    statuses = [
        (r.connector_id, r.status) for r in sent
        if isinstance(r, _call.StatusNotificationPayload)
    ]
    assert statuses == [(1, ChargePointStatus.charging)]
    # StartTransaction comes before the Charging status
    kinds = [type(r).__name__ for r in sent]
    assert kinds.index("StartTransactionPayload") < kinds.index("StatusNotificationPayload")


def test_status_notification_has_no_empty_optional_fields(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _call_recorder()
    _run(cp.send_status())
    status = sent[0]
    assert status.info is None and status.vendor_id is None and status.vendor_error_code is None


def test_boot_notification_omits_empty_optional_fields(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _boot_recorder()
    _run(cp.send_boot_notification(model="PLP2-0-2-2", vendor="Wall Box Chargers"))
    boot = sent[0]
    assert boot.charge_point_model == "PLP2-0-2-2"
    assert boot.iccid is None and boot.imsi is None and boot.meter_serial_number is None
    assert boot.charge_point_serial_number is None  # no serial given -> omitted
    assert boot.firmware_version is None


def test_triggered_boot_notification_resends_real_identity(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _boot_recorder(interval=10)
    _run(cp.send_boot_notification(
        model="PLP2-0-2-2", vendor="Wall Box Chargers",
        serial_number="426759", firmware_version="6.13.6",
    ))
    sent.clear()
    cp.call, sent = _boot_recorder(interval=20)

    _run(cp._handle_triggered_message("BootNotification", 0))
    assert len(sent) == 1  # just the BootNotification — no boot status sequence
    boot = sent[0]
    assert isinstance(boot, _call.BootNotificationPayload)
    assert boot.charge_point_model == "PLP2-0-2-2"
    assert boot.charge_point_vendor == "Wall Box Chargers"
    assert boot.charge_point_serial_number == "426759"
    assert boot.firmware_version == "6.13.6"
    assert cp._heartbeat_interval == 20  # interval from the reply adopted


def test_periodic_meter_values_follow_sampled_data(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _call_recorder()
    _run(cp.on_change_configuration(key="MeterValuesSampledData", value=OCTOPUS_SAMPLED))

    # Charging: everything requested that we can supply, in request order, no SoC
    cp.state = ChargePointStatus.charging
    cp._charger_sim.start_charging()
    cp._transaction_id = 4242
    _run(cp.send_meter_values())
    mv = [r for r in sent if isinstance(r, _call.MeterValuesPayload)][-1]
    assert mv.transaction_id == 4242
    assert [sv["measurand"] for sv in mv.meter_value[0]["sampledValue"]] == [
        "Energy.Active.Import.Register", "Power.Active.Import", "Frequency",
        "Power.Offered", "Current.Offered",
        "Energy.Active.Export.Register", "Power.Active.Export",
    ]
    assert all(sv["context"] == "Sample.Periodic" for sv in mv.meter_value[0]["sampledValue"])

    # Idle: no Frequency/Offered values, no transactionId
    cp.state = ChargePointStatus.available
    cp._charger_sim.stop_charging()
    cp._transaction_id = None
    _run(cp.send_meter_values())
    mv = [r for r in sent if isinstance(r, _call.MeterValuesPayload)][-1]
    assert mv.transaction_id is None
    assert [sv["measurand"] for sv in mv.meter_value[0]["sampledValue"]] == [
        "Energy.Active.Import.Register", "Power.Active.Import",
        "Energy.Active.Export.Register", "Power.Active.Export",
    ]


def test_vendor_keys_are_stored_and_reported(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    for key, value in (("minSoC", "25"), ("maxSoC", "97"), ("AuthEnabledOffline", "False")):
        result = _run(cp.on_change_configuration(key=key, value=value))
        assert result.status == "Accepted"
    assert _config_value(cp, "minSoC") == "25"
    assert _config_value(cp, "maxSoC") == "97"
    assert _config_value(cp, "AuthEnabledOffline") == "False"
    # And included in a full GetConfiguration
    full = _run(cp.on_get_configuration())
    keys = {k["key"] for k in full.configuration_key}
    assert {"minSoC", "maxSoC", "AuthEnabledOffline"} <= keys


def test_shared_state_energy_set_from_register_at_startup(mock_connection, mock_persistence):
    """API must report the stored register immediately, not 0 until the first reading."""
    from src.shared_state import SharedState
    shared = SharedState()
    assert shared.energy_kwh == 0.0
    ChargePoint(
        id="CP001", connection=mock_connection, persistence=mock_persistence,
        current_amps=32, shared_state=shared,
    )
    assert shared.energy_kwh == 5.0  # mock_persistence register is 5000 Wh


# --- Start delay / ramp-up ---


def test_energy_over_start_ramp_is_integrated(mock_connection, mock_persistence):
    """A 60s interval spanning a 3s delay + 5s ramp bills 54.5s of full power."""
    cp = ChargePoint(
        id="CP001", connection=mock_connection, persistence=mock_persistence,
        current_amps=32, start_delay_s=3, ramp_up_s=5,
    )
    cp.state = ChargePointStatus.charging
    start_wh = cp._energy_register_wh
    cp._checkpoint_energy()
    cp._charger_sim.start_charging(now=cp._last_meter_time)
    cp._charger_sim._charging_started_at -= 60
    cp._last_meter_time -= 60
    cp._take_reading()
    added = cp._energy_register_wh - start_wh
    # 7.27 kW * 54.5s ~= 110 Wh (vs ~121 Wh with no ramp); allow sim noise
    assert 100 <= added <= 116


def test_no_power_reported_during_start_delay(mock_connection, mock_persistence):
    cp = ChargePoint(
        id="CP001", connection=mock_connection, persistence=mock_persistence,
        current_amps=32, start_delay_s=3, ramp_up_s=5,
    )
    cp.state = ChargePointStatus.charging
    cp._checkpoint_energy()
    cp._charger_sim.start_charging()
    reading = cp._take_reading()
    assert reading.power_kw == 0.0
    assert cp._shared_state.power_kw == 0.0


def test_power_override_ignores_simulated_ramp(mock_connection, mock_persistence):
    cp = ChargePoint(
        id="CP001", connection=mock_connection, persistence=mock_persistence,
        current_amps=32, start_delay_s=3, ramp_up_s=5,
    )
    cp.state = ChargePointStatus.charging
    cp._charger_sim.start_charging()
    cp._power_override = 7.0
    reading = cp._take_reading()
    assert reading.power_kw == 7.0


# --- 0.9.0: holding messages while offline ---


def _queue_persistence():
    """MagicMock persistence that remembers the saved offline queue."""
    p = MagicMock()
    p.load_energy_register_wh.return_value = 5000
    store = {"queue": []}
    p.load_offline_queue.side_effect = lambda: list(store["queue"])
    p.save_offline_queue.side_effect = lambda q: store.__setitem__("queue", q)
    return p, store


def _started_cp(mock_connection, persistence):
    """Online ChargePoint with transaction 4242 charging."""
    cp = make_cp(mock_connection, persistence)
    cp.call, sent = _boot_recorder()
    cp.state = ChargePointStatus.preparing
    cp._pending_id_tag = OCTOPUS_TAG
    _run(cp._do_start_transaction())
    assert cp._transaction_id == 4242
    return cp, sent


def test_offline_messages_held_and_sent_in_order_after_boot(mock_connection):
    persistence, store = _queue_persistence()
    cp, sent = _started_cp(mock_connection, persistence)
    cp.detach()
    assert not cp.is_online
    sent.clear()

    _run(cp.send_meter_values())
    _run(cp.send_meter_values())
    _run(cp._do_stop_transaction())
    assert sent == []  # nothing went out while offline
    assert [e["action"] for e in store["queue"]] == [
        "MeterValuesPayload", "MeterValuesPayload", "StopTransactionPayload",
    ]  # persisted in case the add-on restarts before reconnecting

    cp.attach(mock_connection)
    _run(cp.send_boot_notification(model="M", vendor="V"))
    kinds = [type(r).__name__ for r in sent]
    assert kinds[:4] == [
        "BootNotificationPayload",
        "MeterValuesPayload", "MeterValuesPayload", "StopTransactionPayload",
    ]  # held messages first, then statuses
    assert all(getattr(r, "transaction_id", 4242) == 4242 for r in sent[1:4])
    assert cp._offline_queue == []
    assert store["queue"] == []


def test_statuses_not_sent_or_held_while_offline(mock_connection):
    persistence, store = _queue_persistence()
    cp, sent = _started_cp(mock_connection, persistence)
    cp.detach()
    sent.clear()
    _run(cp.send_status())
    assert sent == [] and store["queue"] == []


def test_idle_meter_values_not_held(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _call_recorder()
    cp.detach()
    _run(cp.send_meter_values())
    assert sent == [] and cp._offline_queue == []


def test_connection_drop_mid_send_holds_message(mock_connection):
    from src.client import ChargePointOffline
    persistence, store = _queue_persistence()
    cp, sent = _started_cp(mock_connection, persistence)

    async def dropped(request):
        raise ChargePointOffline("connection lost")

    cp.call = AsyncMock(side_effect=dropped)
    _run(cp._do_stop_transaction())
    assert [e["action"] for e in store["queue"]] == ["StopTransactionPayload"]


def test_start_offline_gets_renumbered_when_accepted(mock_connection):
    persistence, store = _queue_persistence()
    cp = make_cp(mock_connection, persistence)
    cp.call, sent = _boot_recorder()
    cp.detach()
    cp.state = ChargePointStatus.preparing
    cp._pending_id_tag = OCTOPUS_TAG
    _run(cp._do_start_transaction())
    local_id = cp._transaction_id
    assert local_id < 0  # provisional until the server answers
    assert cp.state == ChargePointStatus.charging  # still charges offline
    _run(cp.send_meter_values())
    assert store["queue"][1]["payload"]["transaction_id"] == local_id

    cp.attach(mock_connection)
    _run(cp.send_boot_notification(model="M", vendor="V"))
    mv = [r for r in sent if isinstance(r, _call.MeterValuesPayload)][0]
    assert mv.transaction_id == 4242
    assert cp._transaction_id == 4242


def test_held_messages_survive_restart(mock_connection, tmp_path):
    from src.persistence import Persistence
    persistence = Persistence(data_dir=str(tmp_path))
    cp, _ = _started_cp(mock_connection, persistence)
    cp.detach()
    _run(cp._do_stop_transaction(reason=_Reason.reboot))

    # New process: queue loaded from disk and sent after boot
    cp2 = make_cp(None, persistence)
    cp2.call, sent = _boot_recorder()
    assert len(cp2._offline_queue) == 1
    cp2.attach(mock_connection)
    _run(cp2.send_boot_notification(model="M", vendor="V"))
    stop = [r for r in sent if isinstance(r, _call.StopTransactionPayload)][0]
    assert stop.transaction_id == 4242
    assert stop.reason == "Reboot"
    assert stop.id_tag == OCTOPUS_TAG
    assert Persistence(data_dir=str(tmp_path)).load_offline_queue() == []


def test_offline_queue_cap_drops_meter_values_not_start_stop(mock_connection, monkeypatch):
    import src.client as client_mod
    monkeypatch.setattr(client_mod, "OFFLINE_QUEUE_MAX", 3)
    persistence, store = _queue_persistence()
    cp, _ = _started_cp(mock_connection, persistence)
    cp.detach()
    for _ in range(5):
        _run(cp.send_meter_values())
    _run(cp._do_stop_transaction())
    kinds = [e["action"] for e in cp._offline_queue]
    assert len(kinds) == 3
    assert kinds[-1] == "StopTransactionPayload"


# --- 0.9.0: StopTransaction transactionData ---


def test_stop_txn_data_empty_by_default_like_wallbox(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    assert _config_value(cp, "StopTxnSampledData") == ""
    assert _config_value(cp, "StopTxnAlignedData") == ""


def test_stop_transaction_includes_transaction_data(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _boot_recorder()
    _run(cp.on_change_configuration(key="StopTxnSampledData", value="Energy.Active.Import.Register"))
    cp.state = ChargePointStatus.preparing
    cp._pending_id_tag = OCTOPUS_TAG
    _run(cp._do_start_transaction())
    _run(cp.send_meter_values())
    _run(cp.send_meter_values())
    _run(cp._do_stop_transaction())
    stop = [r for r in sent if isinstance(r, _call.StopTransactionPayload)][0]
    contexts = [mv["sampledValue"][0]["context"] for mv in stop.transaction_data]
    assert contexts == [
        "Transaction.Begin", "Sample.Periodic", "Sample.Periodic", "Transaction.End",
    ]
    measurands = {sv["measurand"] for mv in stop.transaction_data for sv in mv["sampledValue"]}
    assert measurands == {"Energy.Active.Import.Register"}
    begin = float(stop.transaction_data[0]["sampledValue"][0]["value"])
    end = float(stop.transaction_data[-1]["sampledValue"][0]["value"])
    assert end == stop.meter_stop and begin <= end


def test_stop_txn_sampled_and_aligned_data_follow_configuration(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _boot_recorder()
    _run(cp.on_change_configuration(
        key="StopTxnSampledData", value="Energy.Active.Import.Register,Power.Active.Import",
    ))
    _run(cp.on_change_configuration(key="StopTxnAlignedData", value="Energy.Active.Import.Register"))
    assert _config_value(cp, "StopTxnSampledData") == "Energy.Active.Import.Register,Power.Active.Import"
    cp.state = ChargePointStatus.preparing
    _run(cp._do_start_transaction())
    _run(cp.send_meter_values())
    _run(cp.send_clock_aligned_meter_values(_utc(15, 15)))
    _run(cp._do_stop_transaction())
    stop = [r for r in sent if isinstance(r, _call.StopTransactionPayload)][0]
    periodic = [mv for mv in stop.transaction_data if mv["sampledValue"][0]["context"] == "Sample.Periodic"][0]
    assert [sv["measurand"] for sv in periodic["sampledValue"]] == [
        "Energy.Active.Import.Register", "Power.Active.Import",
    ]
    clock = [mv for mv in stop.transaction_data if mv["sampledValue"][0]["context"] == "Sample.Clock"][0]
    assert clock["timestamp"] == "2026-10-01T15:15:00Z"


def test_transaction_data_thinned_but_keeps_begin_and_end(mock_connection, mock_persistence, monkeypatch):
    import src.client as client_mod
    monkeypatch.setattr(client_mod, "STOP_TXN_MAX_READINGS", 10)
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _boot_recorder()
    _run(cp.on_change_configuration(key="StopTxnSampledData", value="Energy.Active.Import.Register"))
    cp.state = ChargePointStatus.preparing
    _run(cp._do_start_transaction())
    for _ in range(40):
        _run(cp.send_meter_values())
    _run(cp._do_stop_transaction())
    stop = [r for r in sent if isinstance(r, _call.StopTransactionPayload)][0]
    data = stop.transaction_data
    assert len(data) <= 10
    assert data[0]["sampledValue"][0]["context"] == "Transaction.Begin"
    assert data[-1]["sampledValue"][0]["context"] == "Transaction.End"


# --- 0.9.1: closing a transaction interrupted by power loss ---


def test_power_loss_closes_transaction_on_next_start(mock_connection, tmp_path):
    from src.persistence import Persistence
    persistence = Persistence(data_dir=str(tmp_path))
    cp, _ = _started_cp(mock_connection, persistence)
    cp._power_override = 7.0
    cp._last_meter_time -= 3600
    _run(cp.send_meter_values())  # an hour of charging, then the power goes
    last_wh = cp._energy_register_wh
    saved = persistence.load_active_transaction()
    assert saved["transaction_id"] == 4242 and saved["energy_wh"] == last_wh
    del cp  # no clean stop

    cp2 = make_cp(None, persistence)
    assert persistence.load_active_transaction() is None
    cp2.call, sent = _boot_recorder()
    cp2.attach(mock_connection)
    _run(cp2.send_boot_notification(model="M", vendor="V"))
    kinds = [type(r).__name__ for r in sent]
    assert kinds[:2] == ["BootNotificationPayload", "StopTransactionPayload"]
    stop = sent[1]
    assert stop.reason == "PowerLoss"
    assert stop.transaction_id == 4242
    assert stop.meter_stop == last_wh
    assert stop.id_tag == OCTOPUS_TAG
    assert stop.timestamp == saved["timestamp"]  # time of the last reading
    assert stop.transaction_data is None  # StopTxnSampledData empty (Wallbox)


def test_power_loss_stop_includes_transaction_data_when_configured(mock_connection, tmp_path):
    from src.persistence import Persistence
    persistence = Persistence(data_dir=str(tmp_path))
    cp = make_cp(mock_connection, persistence)
    cp.call, _ = _boot_recorder()
    _run(cp.on_change_configuration(key="StopTxnSampledData", value="Energy.Active.Import.Register"))
    cp.state = ChargePointStatus.preparing
    _run(cp._do_start_transaction())
    _run(cp.send_meter_values())

    cp2 = make_cp(None, persistence)
    stop = cp2._request_from_entry(cp2._offline_queue[0])
    contexts = [mv["sampledValue"][0]["context"] for mv in stop.transaction_data]
    assert contexts == ["Transaction.Begin", "Sample.Periodic", "Transaction.End"]


def test_clean_stop_leaves_nothing_to_recover(mock_connection, tmp_path):
    from src.persistence import Persistence
    persistence = Persistence(data_dir=str(tmp_path))
    cp, _ = _started_cp(mock_connection, persistence)
    _run(cp._do_stop_transaction())
    assert persistence.load_active_transaction() is None
    assert make_cp(None, persistence)._offline_queue == []


def test_power_loss_after_offline_stop_not_stopped_twice(mock_connection, tmp_path):
    """Stop already held on disk, but the open-transaction file wasn't cleared."""
    from src.persistence import Persistence
    persistence = Persistence(data_dir=str(tmp_path))
    cp, _ = _started_cp(mock_connection, persistence)
    saved = persistence.load_active_transaction()
    cp.detach()
    _run(cp._do_stop_transaction(reason=_Reason.reboot))
    persistence.save_active_transaction(saved)  # simulate dying before the clear
    cp2 = make_cp(None, persistence)
    assert [e["payload"]["reason"] for e in cp2._offline_queue] == ["Reboot"]


def test_power_loss_with_unconfirmed_start_is_renumbered(mock_connection, tmp_path):
    from src.persistence import Persistence
    persistence = Persistence(data_dir=str(tmp_path))
    cp = make_cp(mock_connection, persistence)
    cp.call, _ = _boot_recorder()
    cp.detach()
    cp.state = ChargePointStatus.preparing
    cp._pending_id_tag = OCTOPUS_TAG
    _run(cp._do_start_transaction())  # StartTransaction held, provisional id

    cp2 = make_cp(None, persistence)
    assert [e["action"] for e in cp2._offline_queue] == [
        "StartTransactionPayload", "StopTransactionPayload",
    ]
    cp2.call, sent = _boot_recorder()
    cp2.attach(mock_connection)
    _run(cp2.send_boot_notification(model="M", vendor="V"))
    stop = [r for r in sent if isinstance(r, _call.StopTransactionPayload)][0]
    assert stop.transaction_id == 4242 and stop.reason == "PowerLoss"


def test_stop_cut_off_before_queued_is_recovered(mock_connection, tmp_path):
    """Shutdown timeout hits during the Finishing status, before StopTransaction."""
    from src.persistence import Persistence
    persistence = Persistence(data_dir=str(tmp_path))
    cp, _ = _started_cp(mock_connection, persistence)

    async def hang(request):
        await asyncio.Future()

    cp.call = AsyncMock(side_effect=hang)

    async def shutdown():
        try:
            await asyncio.wait_for(cp._do_stop_transaction(reason=_Reason.reboot), 0.05)
        except asyncio.TimeoutError:
            pass

    _run(shutdown())
    assert persistence.load_active_transaction()["transaction_id"] == 4242
    cp2 = make_cp(None, persistence)
    assert [e["payload"]["reason"] for e in cp2._offline_queue] == ["PowerLoss"]


# --- 0.9.2: last command received / sent sensors ---

import json as _json


def test_last_command_received_with_our_reply(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp._record_traffic(_json.dumps(
        [2, "abc", "RemoteStartTransaction", {"idTag": OCTOPUS_TAG, "connectorId": 1}]
    ), incoming=True)
    rec = cp._shared_state.last_command_received
    assert rec["action"] == "RemoteStartTransaction"
    assert rec["payload"] == {"idTag": OCTOPUS_TAG, "connectorId": 1}
    assert rec["status"] is None and rec["timestamp"].endswith("Z")

    cp._record_traffic(_json.dumps([3, "abc", {"status": "Accepted"}]), incoming=False)
    assert cp._shared_state.last_command_received["status"] == "Accepted"
    # A reply to some other id doesn't touch it
    cp._record_traffic(_json.dumps([3, "zzz", {"status": "Rejected"}]), incoming=False)
    assert cp._shared_state.last_command_received["status"] == "Accepted"


def test_last_command_sent_skips_heartbeat_and_meter_values(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp._record_traffic(_json.dumps(
        [2, "s1", "StartTransaction", {"connectorId": 1, "idTag": "x", "meterStart": 5}]
    ), incoming=False)
    cp._record_traffic(_json.dumps([2, "s2", "Heartbeat", {}]), incoming=False)
    cp._record_traffic(_json.dumps([2, "s3", "MeterValues", {"connectorId": 1, "meterValue": []}]), incoming=False)
    assert cp._shared_state.last_command_sent["action"] == "StartTransaction"
    # Server's answer to StartTransaction: status from idTagInfo
    cp._record_traffic(_json.dumps(
        [3, "s1", {"transactionId": 4242, "idTagInfo": {"status": "Accepted"}}]
    ), incoming=True)
    rec = cp._shared_state.last_command_sent
    assert rec["status"] == "Accepted"
    assert rec["response"]["transactionId"] == 4242


def test_last_command_error_and_bulky_payloads(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp._record_traffic(_json.dumps([2, "s9", "StopTransaction", {
        "transactionId": 1, "meterStop": 9, "timestamp": "t",
        "transactionData": [{"timestamp": "t", "sampledValue": []}] * 3,
    }]), incoming=False)
    assert cp._shared_state.last_command_sent["payload"]["transactionData"] == "3 item(s)"
    cp._record_traffic(_json.dumps([4, "s9", "FormationViolation", "bad", {}]), incoming=True)
    assert cp._shared_state.last_command_sent["status"] == "Error: FormationViolation"
    cp._record_traffic("not json", incoming=True)  # never raises


def test_online_start_never_exposes_provisional_id(mock_connection, mock_persistence):
    """While StartTransaction is in flight there's no transactionId yet, then the server's."""
    cp = make_cp(mock_connection, mock_persistence)
    seen = []

    async def slow_call(request):
        if isinstance(request, _call.StartTransactionPayload):
            seen.append(cp._transaction_id)  # what HA / RemoteStop would see now
            await asyncio.sleep(0.01)
            return MagicMock(transaction_id=42)
        return MagicMock()

    cp.call = AsyncMock(side_effect=slow_call)
    cp.state = ChargePointStatus.preparing
    _run(cp._do_start_transaction())
    assert seen == [None]
    assert cp._transaction_id == 42
    assert cp._shared_state.transaction_id == 42


# --- 0.9.3: live power for the API between meter readings ---


def test_live_power_follows_ramp_without_counting_energy(mock_connection, mock_persistence):
    cp = ChargePoint(
        id="CP001", connection=mock_connection, persistence=mock_persistence,
        current_amps=32, start_delay_s=3, ramp_up_s=5,
    )
    cp.state = ChargePointStatus.charging
    cp._charger_sim.start_charging()
    start_wh = cp._energy_register_wh
    last_meter_time = cp._last_meter_time

    cp.refresh_live_power()
    assert cp._shared_state.power_kw == 0.0  # still in the start delay

    cp._charger_sim._charging_started_at -= 5.5  # halfway up the ramp
    cp.refresh_live_power()
    assert 3.2 <= cp._shared_state.power_kw <= 4.1

    cp._charger_sim._charging_started_at -= 60  # fully ramped
    cp.refresh_live_power()
    assert cp._shared_state.power_kw > 6.5
    assert cp._shared_state.current_a > 25

    # Display only: energy and the integration interval are untouched
    assert cp._energy_register_wh == start_wh
    assert cp._last_meter_time == last_meter_time
    mock_persistence.save_energy_register_wh.assert_not_called()


def test_live_power_zero_when_not_charging(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp._shared_state.power_kw = 7.2  # stale value from the last reading
    cp.state = ChargePointStatus.suspended_evse  # paused by a charging profile
    cp.refresh_live_power()
    assert cp._shared_state.power_kw == 0.0


def test_live_power_uses_power_entity(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.state = ChargePointStatus.charging
    cp._charger_sim.start_charging()
    cp._power_override = 3.3
    cp.refresh_live_power()
    assert cp._shared_state.power_kw == 3.3
    assert cp._shared_state.power_source == "entity"


# --- 0.9.4: SoC entity and car full ---


def _charging_cp(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _boot_recorder()
    cp.state = ChargePointStatus.preparing
    _run(cp._do_start_transaction())
    sent.clear()
    return cp, sent


def _statuses(sent):
    return [r.status for r in sent if isinstance(r, _call.StatusNotificationPayload)]


def test_soc_reported_only_while_car_connected(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _call_recorder()
    _run(cp.on_change_configuration(key="MeterValuesSampledData", value=OCTOPUS_SAMPLED))
    cp.set_soc(55)
    _run(cp.send_meter_values())  # Available: no car, no SoC
    mv = [r for r in sent if isinstance(r, _call.MeterValuesPayload)][-1]
    assert "SoC" not in [sv["measurand"] for sv in mv.meter_value[0]["sampledValue"]]

    cp.state = ChargePointStatus.preparing  # car plugged in
    _run(cp.send_meter_values())
    mv = [r for r in sent if isinstance(r, _call.MeterValuesPayload)][-1]
    socs = [sv["value"] for sv in mv.meter_value[0]["sampledValue"] if sv["measurand"] == "SoC"]
    assert socs == ["55"]


def test_no_soc_entity_reports_nothing_and_never_full(mock_connection, mock_persistence):
    cp, sent = _charging_cp(mock_connection, mock_persistence)
    _run(cp.on_change_configuration(key="MeterValuesSampledData", value=OCTOPUS_SAMPLED))
    cp.set_soc(None)
    assert not cp.car_full
    _run(cp.send_meter_values())
    mv = [r for r in sent if isinstance(r, _call.MeterValuesPayload)][-1]
    assert "SoC" not in [sv["measurand"] for sv in mv.meter_value[0]["sampledValue"]]
    assert cp.state == ChargePointStatus.charging


def test_car_full_suspends_ev_and_resumes_below_100(mock_connection, mock_persistence):
    cp, sent = _charging_cp(mock_connection, mock_persistence)
    cp.set_soc(99)
    _run(cp._apply_profile_state())
    assert cp.state == ChargePointStatus.charging

    cp.set_soc(100)
    _run(cp._apply_profile_state())
    assert cp.state == ChargePointStatus.suspended_ev
    assert not cp._charger_sim.is_charging
    assert _statuses(sent) == [ChargePointStatus.suspended_ev]
    cp.refresh_live_power()
    assert cp._shared_state.power_kw == 0.0
    assert cp._transaction_id == 4242  # session stays open

    # No energy while full, even over a long time
    before = cp._energy_register_wh
    cp._last_meter_time -= 3600
    _run(cp.send_meter_values())
    assert cp._energy_register_wh == before

    cp.set_soc(98)
    _run(cp._apply_profile_state())
    assert cp.state == ChargePointStatus.charging
    assert cp._charger_sim.is_charging
    assert _statuses(sent)[-1] == ChargePointStatus.charging


def test_profile_pause_wins_over_car_full(mock_connection, mock_persistence):
    cp, sent = _charging_cp(mock_connection, mock_persistence)
    cp._profile_scheduler.get_current_limit_kw = lambda: 0.0
    cp._profile_scheduler.set_profile({
        "chargingProfileId": 1, "stackLevel": 0, "chargingProfilePurpose": "TxProfile",
        "chargingProfileKind": "Relative",
        "chargingSchedule": {"chargingRateUnit": "A", "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 0}]},
    })
    cp.set_soc(100)
    _run(cp._apply_profile_state())
    assert cp.state == ChargePointStatus.suspended_evse


def test_plugged_in_already_full_goes_suspended_ev(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _boot_recorder()
    cp.set_soc(100)
    cp.state = ChargePointStatus.preparing
    _run(cp._do_start_transaction())
    assert _statuses(sent) == [ChargePointStatus.charging, ChargePointStatus.suspended_ev]
    assert cp.state == ChargePointStatus.suspended_ev


def test_soc_clamped_and_shared(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.set_soc(104)
    assert cp._shared_state.soc_percent == 100.0
    cp.set_soc(None)
    assert cp._shared_state.soc_percent is None


def test_held_messages_count_in_shared_state(mock_connection):
    persistence, store = _queue_persistence()
    cp, _ = _started_cp(mock_connection, persistence)
    cp.detach()
    _run(cp.send_meter_values())
    _run(cp.send_meter_values())
    assert cp._shared_state.held_messages == 2


# --- 0.9.5: HA current is the max, provider can only lower it ---


def _limit(cp, value):
    return _run(cp.on_change_configuration(key="chargingALimitConn1", value=value))


def test_provider_limit_cannot_raise_ha_max(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.set_max_current(16)
    result = _limit(cp, "32")  # what Octopus sends at boot, start and stop
    assert result.status == "Accepted"
    assert _config_value(cp, "chargingALimitConn1") == "32"  # reported back as set
    assert cp._charger_sim.current_amps == 16
    assert cp._shared_state.current_amps_setting == 16
    assert cp._shared_state.current_amps_effective == 16
    assert cp._shared_state.current_amps_provider_limit == 32


def test_provider_limit_can_lower_and_release(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.set_max_current(25)
    _limit(cp, "10")
    assert cp._charger_sim.current_amps == 10
    assert cp._shared_state.current_amps_setting == 25  # the select keeps the HA value
    _limit(cp, "32")
    assert cp._charger_sim.current_amps == 25


def test_provider_limit_snaps_down_to_supported_setting(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    _limit(cp, "18.5")
    assert cp._charger_sim.current_amps == 16
    _limit(cp, "3")  # below the 6A minimum
    assert cp._charger_sim.current_amps == 6
    _limit(cp, "abc")  # ignored, still accepted
    assert cp._charger_sim.current_amps == 6


def test_ha_max_change_respects_provider_limit(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    _limit(cp, "13")
    cp.set_max_current(32)
    assert cp._charger_sim.current_amps == 13
    cp.set_max_current(10)
    assert cp._charger_sim.current_amps == 10


def test_invalid_ha_current_rejected(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    with pytest.raises(ValueError):
        cp.set_max_current(15)


def test_ha_max_current_remembered_across_restart(tmp_path):
    from src.persistence import Persistence
    from src.config import starting_current_amps as _starting_current
    persistence = Persistence(data_dir=str(tmp_path))
    assert _starting_current(persistence) == 32  # fresh install

    cp = ChargePoint(id="CP", connection=None, persistence=persistence, current_amps=32)
    cp.set_max_current(16)
    assert _starting_current(persistence) == 16  # restart: the setting is kept


# --- 0.9.7: Power Source reflects the configuration, charging or not ---


def test_power_source_shows_entity_while_idle(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, _ = _call_recorder()  # no real server to answer the idle reading
    cp.set_power_override(0.0)  # a power entity reading 0 W while not charging
    cp.refresh_live_power()
    _run(cp.send_meter_values())  # idle reading zeroes power...
    assert cp._shared_state.power_kw == 0.0
    assert cp._shared_state.power_source == "entity"  # ...but not the source
    assert cp._shared_state.power_entity_value == 0.0
    cp.set_power_override(None)  # entity unset / unavailable
    assert cp._shared_state.power_source == "simulated"


# --- 0.10.0: charging taper ---


def test_taper_reduces_power_and_energy_near_full(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, _ = _call_recorder()
    cp.state = ChargePointStatus.charging
    cp._charger_sim.start_charging()

    cp.set_soc(50)
    cp.refresh_live_power()
    full_power = cp._shared_state.power_kw
    assert full_power > 6.5  # no taper below 90%

    cp.set_soc(95)  # halfway through the taper: 65% of full power
    samples = []
    for _ in range(50):
        cp.refresh_live_power()
        samples.append(cp._shared_state.power_kw)
    assert 4.4 <= sum(samples) / len(samples) <= 5.1

    before = cp._energy_register_wh
    cp._last_meter_time -= 3600
    cp._take_reading()
    assert 4400 <= cp._energy_register_wh - before <= 5100  # energy tapers too


def test_no_taper_without_soc_or_with_power_entity(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.state = ChargePointStatus.charging
    cp._charger_sim.start_charging()
    assert cp._taper_factor() == 1.0  # no SoC entity
    cp.set_soc(99)
    cp.set_power_override(7.0)  # a real power reading already includes the taper
    cp.refresh_live_power()
    assert cp._shared_state.power_kw == 7.0


def test_plugged_in_survives_restart(tmp_path, mock_connection):
    """The cable stays in across a restart: boot as Preparing, connector 0 Available."""
    from src.persistence import Persistence
    persistence = Persistence(data_dir=str(tmp_path))
    first = make_cp(mock_connection, persistence)
    first.set_plugged_in(True)

    cp = make_cp(mock_connection, Persistence(data_dir=str(tmp_path)))
    assert cp.state == ChargePointStatus.preparing
    assert cp._shared_state.plugged_in is True
    cp.call, sent = _boot_recorder()
    _run(cp.send_boot_notification(model="M", vendor="V"))
    statuses = [(r.connector_id, r.status) for r in sent if isinstance(r, _call.StatusNotificationPayload)]
    assert statuses == [(0, ChargePointStatus.available), (1, ChargePointStatus.preparing)]

    cp.set_plugged_in(False)
    assert make_cp(mock_connection, Persistence(data_dir=str(tmp_path))).state == ChargePointStatus.available


def test_connector_zero_never_reports_charging(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp.call, sent = _boot_recorder()
    cp._registered = True
    cp.state = ChargePointStatus.charging
    _run(cp._send_status_for_connector(0))
    assert _statuses(sent) == [ChargePointStatus.available]


# --- 1.1.0: web GUI data ---


def test_session_history_records_start_and_stop(mock_connection, tmp_path):
    from src.persistence import Persistence
    from ocpp.v16.enums import Reason
    persistence = Persistence(data_dir=str(tmp_path))
    cp, _ = _started_cp(mock_connection, persistence)
    assert cp.sessions.current["transaction_id"] == 4242
    assert cp.sessions.current["id_tag"] == OCTOPUS_TAG
    cp._energy_register_wh += 1500
    _run(cp._do_stop_transaction(final_state=ChargePointStatus.available, reason=Reason.remote))
    assert cp.sessions.current is None
    last = make_cp(mock_connection, Persistence(data_dir=str(tmp_path))).sessions.history[0]
    assert last["transaction_id"] == 4242 and last["reason"] == "Remote"
    assert last["energy_kwh"] >= 1.5


def test_power_loss_closes_session_in_history(mock_connection, tmp_path):
    from src.persistence import Persistence
    persistence = Persistence(data_dir=str(tmp_path))
    cp, _ = _started_cp(mock_connection, persistence)
    del cp  # power cut
    cp2 = make_cp(None, Persistence(data_dir=str(tmp_path)))
    assert cp2.sessions.current is None
    assert cp2.sessions.history[0]["reason"] == "PowerLoss"
    assert cp2.sessions.history[0]["transaction_id"] == 4242


def test_message_log_sees_every_frame(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    cp._record_traffic('[2,"x","TriggerMessage",{"requestedMessage":"StatusNotification"}]', incoming=True)
    cp._record_traffic('[3,"x",{"status":"Accepted"}]', incoming=False)
    entries = cp.message_log.since(0)
    assert [(e["direction"], e["action"]) for e in entries] == [("received", "TriggerMessage"), ("sent", "TriggerMessage")]


def test_provider_info(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    _run(cp.on_change_configuration(key="chargingALimitConn1", value="16"))
    info = cp.provider_info()
    keys = {c["key"]: c for c in info["configuration"]}
    assert keys["chargingALimitConn1"]["set_by_server"] is True
    assert keys["NumberOfConnectors"]["set_by_server"] is False
    assert info["provider_limit_amps"] == 16 and info["effective_amps"] == 16
    assert info["charging_profiles"] == []


def test_held_messages_info(mock_connection):
    persistence, _ = _queue_persistence()
    cp, _ = _started_cp(mock_connection, persistence)
    cp.detach()
    from ocpp.v16.enums import Reason
    _run(cp._do_stop_transaction(final_state=ChargePointStatus.available, reason=Reason.remote))
    held = cp.held_messages_info()
    assert held and held[-1]["action"] == "StopTransaction"
    assert "transaction 4242" in held[-1]["summary"]

def test_start_delay_and_ramp_set_and_saved(mock_connection, tmp_path):
    from src.persistence import Persistence
    cp = ChargePoint(id="CP001", connection=mock_connection, persistence=Persistence(data_dir=str(tmp_path)),
                     start_delay_s=3, ramp_up_s=5)
    assert (cp._shared_state.start_delay_s, cp._shared_state.ramp_up_s) == (3, 5)
    cp.set_ramp(0, 10)
    assert (cp._charger_sim.start_delay_s, cp._charger_sim.ramp_up_s) == (0, 10)
    again = ChargePoint(id="CP001", connection=mock_connection, persistence=Persistence(data_dir=str(tmp_path)),
                        start_delay_s=3, ramp_up_s=5)
    assert (again._charger_sim.start_delay_s, again._charger_sim.ramp_up_s) == (0, 10)
    with pytest.raises(ValueError):
        cp.set_ramp(61, 0)


def test_unplugged_without_session_shows_in_history(mock_connection, tmp_path):
    from src.persistence import Persistence
    cp = make_cp(mock_connection, Persistence(data_dir=str(tmp_path)))
    cp.set_plugged_in(True, "schedule")
    cp.set_plugged_in(True, "provider")  # no change: ignored
    cp.set_plugged_in(False, "web page")
    entry = cp.sessions.history[0]
    assert entry["type"] == "no_session"
    assert (entry["plugged_by"], entry["unplugged_by"]) == ("schedule", "web page")


# --- 2.1.5: status after a stop from the server ---


def _statuses_after(cp, coro_factory):
    cp._registered = True
    cp.call, sent = _call_recorder()
    cp.state = ChargePointStatus.charging
    cp._charger_sim.start_charging()
    cp._transaction_id = 4242

    async def scenario():
        await coro_factory()
        for _ in range(5):
            await asyncio.sleep(0)

    loop = asyncio.new_event_loop()
    loop.run_until_complete(scenario())
    loop.close()
    return [
        "Stop" if isinstance(r, _call.StopTransactionPayload) else r.status
        for r in sent
        if isinstance(r, (_call.StatusNotificationPayload, _call.StopTransactionPayload))
    ]


def test_remote_stop_ends_in_preparing(mock_connection, mock_persistence):
    """After RemoteStop the server is told the car is still plugged in."""
    cp = make_cp(mock_connection, mock_persistence)
    seq = _statuses_after(cp, lambda: cp.on_remote_stop_transaction(transaction_id=4242))
    assert seq == [ChargePointStatus.finishing, "Stop", ChargePointStatus.preparing]
    assert cp.state == ChargePointStatus.preparing


def test_unlock_ends_in_available(mock_connection, mock_persistence):
    cp = make_cp(mock_connection, mock_persistence)
    seq = _statuses_after(cp, lambda: cp.on_unlock_connector(connector_id=1))
    assert seq[-2:] == ["Stop", ChargePointStatus.available]


def test_plain_stop_sends_no_extra_status(mock_connection, mock_persistence):
    """Unplug and reset send their own status afterwards."""
    cp = make_cp(mock_connection, mock_persistence)
    seq = _statuses_after(cp, lambda: cp._do_stop_transaction(final_state=ChargePointStatus.available))
    assert seq == [ChargePointStatus.finishing, "Stop"]


# --- 2.11.0: continuing a session across an add-on restart ---


def _resume_cp(connection, persistence):
    return ChargePoint(id="CP001", connection=connection, persistence=persistence,
                       current_amps=32, resume_on_restart=True)


def _suspended(mock_connection, tmp_path, profile=None):
    """A session (transaction 4242) left open by a restart."""
    from src.persistence import Persistence
    tmp_path.mkdir(parents=True, exist_ok=True)
    persistence = Persistence(data_dir=str(tmp_path))
    cp = _resume_cp(mock_connection, persistence)
    cp.call, sent = _boot_recorder()
    cp.set_plugged_in(True)
    cp.state = ChargePointStatus.preparing
    cp._pending_id_tag = OCTOPUS_TAG
    cp._tx_profile = profile
    _run(cp._do_start_transaction())
    cp._tx_profile = profile
    cp._power_override = 7.0
    cp._last_meter_time -= 600
    assert cp.suspend_for_restart() is True
    assert not any(isinstance(r, _call.StopTransactionPayload) for r in sent)
    return persistence, cp._energy_register_wh


def test_restart_continues_the_session(mock_connection, tmp_path):
    from src.persistence import Persistence
    profile = {"chargingProfileId": 0, "stackLevel": 0, "chargingProfilePurpose": "TxProfile",
               "chargingProfileKind": "Relative",
               "chargingSchedule": {"chargingRateUnit": "A", "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 32.0}]}}
    persistence, wh = _suspended(mock_connection, tmp_path, profile)
    assert persistence.load_active_transaction()["resume"] is True
    cp2 = _resume_cp(None, Persistence(data_dir=str(tmp_path)))
    assert cp2._transaction_id == 4242 and cp2.state == ChargePointStatus.charging and cp2._resumed
    assert cp2._transaction_id_tag == OCTOPUS_TAG and cp2._profile_scheduler.has_profile
    assert cp2.sessions.current is not None and cp2.sessions.current["transaction_id"] == 4242
    assert persistence.load_active_transaction()["resume"] is False  # open, being continued
    cp2.call, sent = _boot_recorder()
    cp2.attach(mock_connection)
    _run(cp2.send_boot_notification(model="M", vendor="V"))
    assert not any(isinstance(r, _call.StopTransactionPayload) for r in sent)
    statuses = [r.status for r in sent if isinstance(r, _call.StatusNotificationPayload) and r.connector_id == 1]
    assert statuses == [ChargePointStatus.charging]
    # Later stopped as usual, meterStop counted from the original start
    _run(cp2._do_stop_transaction())
    stop = next(r for r in sent if isinstance(r, _call.StopTransactionPayload))
    assert stop.transaction_id == 4242 and stop.meter_stop >= wh


def test_server_starts_a_new_session_instead(mock_connection, tmp_path):
    from src.persistence import Persistence
    persistence, _ = _suspended(mock_connection, tmp_path)
    cp2 = _resume_cp(mock_connection, Persistence(data_dir=str(tmp_path)))
    cp2.call, sent = _boot_recorder()

    async def scenario():
        res = await cp2.on_remote_start_transaction(id_tag=OCTOPUS_TAG)
        await _settle(40)
        return res

    res = _run(scenario())
    assert res.status == RemoteStartStopStatus.accepted
    kinds = [type(r).__name__ for r in sent if not isinstance(r, _call.StatusNotificationPayload)]
    assert kinds == ["StopTransactionPayload", "StartTransactionPayload"]
    assert sent[[type(r).__name__ for r in sent].index("StopTransactionPayload")].reason == "Reboot"
    assert cp2._transaction_id == 4242 and not cp2._resumed and cp2.state == ChargePointStatus.charging


def test_not_continued_when_too_old_unplugged_or_off(mock_connection, tmp_path):
    from src.persistence import Persistence
    import src.client as client_mod
    # Too long ago: stopped (Reboot) with the time it was left
    persistence, _ = _suspended(mock_connection, tmp_path / "a")
    saved = persistence.load_active_transaction()
    old = client_mod.RESUME_MAX_S
    client_mod.RESUME_MAX_S = -1
    try:
        cp2 = _resume_cp(None, Persistence(data_dir=str(tmp_path / "a")))
    finally:
        client_mod.RESUME_MAX_S = old
    assert cp2._transaction_id is None and not cp2._resumed
    stop = cp2._offline_queue[-1]["payload"]
    assert stop["reason"] == "Reboot" and stop["timestamp"] == saved["timestamp"]
    # Option off
    _suspended(mock_connection, tmp_path / "b")
    cp3 = make_cp(None, Persistence(data_dir=str(tmp_path / "b")))
    assert cp3._transaction_id is None and cp3._offline_queue[-1]["payload"]["reason"] == "Reboot"
    # Unplugged while stopped
    p4, _ = _suspended(mock_connection, tmp_path / "c")
    p4.save_plugged_in(False)
    cp4 = _resume_cp(None, Persistence(data_dir=str(tmp_path / "c")))
    assert cp4._transaction_id is None and cp4._offline_queue[-1]["payload"]["reason"] == "Reboot"


def test_suspend_needs_option_session_and_plug(mock_connection, tmp_path):
    from src.persistence import Persistence
    cp = make_cp(mock_connection, Persistence(data_dir=str(tmp_path)))
    assert cp.suspend_for_restart() is False  # option off, no session
    cp.resume_on_restart = True
    assert cp.suspend_for_restart() is False  # no session


def test_restart_restores_a_decimal_profile(mock_connection, tmp_path):
    # The ocpp library gives Decimals; saved to disk they became text ("32.0")
    from decimal import Decimal
    from src.persistence import Persistence
    profile = {"charging_profile_id": 0, "stack_level": 0, "charging_profile_purpose": "TxProfile",
               "charging_profile_kind": "Relative",
               "charging_schedule": {"charging_rate_unit": "A", "min_charging_rate": Decimal("32.0"),
                                     "charging_schedule_period": [{"start_period": 0, "limit": Decimal("32.0")}]}}
    _suspended(mock_connection, tmp_path, profile)
    cp2 = _resume_cp(None, Persistence(data_dir=str(tmp_path)))
    assert cp2._profile_scheduler.has_profile
    assert cp2._profile_scheduler.get_current_limit_kw() == 32 * 230 / 1000
    # A file saved by 2.11.x (numbers as text) is read too
    import json
    path = tmp_path / "active_transaction.json"
    data = json.loads(path.read_text())
    from src.charging_profile import normalise_profile
    old = {"limit": "32.0", "start_period": "0", "stack_level": "0"}
    assert normalise_profile(old) == {"limit": 32.0, "start_period": 0, "stack_level": 0}
