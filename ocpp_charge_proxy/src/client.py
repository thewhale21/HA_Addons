from __future__ import annotations

import asyncio
import dataclasses
import datetime
import json
import logging
import time
from typing import Optional

import websockets
import websockets.exceptions  # submodule is lazy-loaded; needed at import time below
from ocpp.routing import on
from ocpp.v16 import ChargePoint as BaseChargePoint
from ocpp.v16 import call, call_result
from ocpp.v16.enums import (
    Action,
    AvailabilityStatus,
    AvailabilityType,
    ChargePointErrorCode,
    ChargePointStatus,
    ClearCacheStatus,
    ConfigurationStatus,
    DataTransferStatus,
    Reason,
    RegistrationStatus,
    RemoteStartStopStatus,
    ResetStatus,
    ResetType,
    TriggerMessageStatus,
    UnlockStatus,
    UpdateStatus,
)

from src.charger_sim import VALID_CURRENT_SETTINGS, ChargerReading, ChargerSimulator
from src.charging_profile import ChargingProfileScheduler, normalise_profile
from src.gui_data import MessageLog, SessionLog
from src.meter_values import build_meter_values
from src.persistence import Persistence
from src.shared_state import SharedState
from src.traffic import TrafficRecorder

logger = logging.getLogger(__name__)

# Charging taper near full (with a SoC entity): full power up to this SoC...
TAPER_START_SOC = 90.0
# ...then down linearly to this fraction of full power at 100%
TAPER_MIN_FACTOR = 0.3

# Offline message queue: transaction-related messages (StartTransaction,
# StopTransaction, MeterValues with a transactionId) are held while the server
# is unreachable and sent in order once BootNotification is accepted again.
OFFLINE_QUEUE_MAX = 1000  # oldest MeterValues dropped beyond this; Start/Stop never
# StopTransaction transactionData: beyond this many readings, every other
# intermediate reading is dropped (keeps the whole session at lower resolution).
STOP_TXN_MAX_READINGS = 100


class ChargePointOffline(Exception):
    """Raised by ChargePoint.call when there is no live server connection."""


_CONNECTION_ERRORS = (
    ChargePointOffline,
    websockets.exceptions.ConnectionClosed,
    OSError,
    asyncio.TimeoutError,
)


def _payload_to_dict(payload) -> dict:
    if dataclasses.is_dataclass(payload):
        return dataclasses.asdict(payload)
    return dict(vars(payload))


RESUME_MAX_S = 600  # continue a session after a restart only if it was this recent


def _age_s(iso) -> Optional[float]:
    """Seconds since an ISO time (None if unreadable)."""
    try:
        t = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_aligned(
    now: datetime.datetime, interval: int,
) -> tuple[float, datetime.datetime]:
    """Seconds until the next clock-aligned boundary, and that boundary.

    Boundaries are multiples of `interval` seconds from UTC midnight. A day
    that doesn't divide evenly gets a short last slot ending at midnight.
    Exactly on a boundary returns the *next* one (never 0).
    """
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = (now - midnight).total_seconds()
    next_offset = (int(elapsed // interval) + 1) * interval
    next_offset = min(next_offset, 86400)
    boundary = midnight + datetime.timedelta(seconds=next_offset)
    return next_offset - elapsed, boundary


class ChargePoint(BaseChargePoint):
    def __init__(
        self,
        id: str,
        connection,
        persistence: Persistence,
        current_amps: int = 32,
        shared_state: SharedState | None = None,
        start_delay_s: float = 0.0,
        ramp_up_s: float = 0.0,
        resume_on_restart: bool = False,
    ):
        super().__init__(id, connection)
        # Continue a session across an add-on restart (see suspend_for_restart)
        self.resume_on_restart = resume_on_restart
        self._suspending = False  # shutting down with the session left open to continue
        self._resumed = False  # the session was continued after a restart
        self._tx_profile: Optional[dict] = None  # the session's TxProfile, kept for a restart
        self.connector_id = 1
        self.state = ChargePointStatus.available
        self._persistence = persistence
        self._power_override: Optional[float] = None  # kW, set via API
        self._soc: Optional[float] = None  # % from your SoC sensor (Settings tab), or the test value
        self._shared_state = shared_state or SharedState()
        self._energy_register_wh: int = persistence.load_energy_register_wh()
        self._shared_state.energy_kwh = self.energy_register_kwh  # never serve 0 before first reading
        self._transaction_id: Optional[int] = None
        self._transaction_start_energy_wh: int = 0
        # idTag the server authorised the session with (RemoteStart) — echoed
        # in StartTransaction and StopTransaction.
        self._pending_id_tag: Optional[str] = None
        self._transaction_id_tag: Optional[str] = None
        # The BootNotification sent at connect, re-sent verbatim if the server
        # requests one via TriggerMessage.
        self._boot_request: Optional[call.BootNotificationPayload] = None
        self._last_meter_time: float = time.monotonic()
        self._meter_value_interval: int = 60  # default, updated by ChangeConfiguration
        self._heartbeat_interval: int = 30  # default, set by BootNotification / ChangeConfiguration
        self._heartbeat_interval_changed = asyncio.Event()
        self._clock_aligned_interval: int = 0  # 0 = disabled; set by ChangeConfiguration
        self._aligned_measurands: list[str] = []
        self._sampled_measurands: list[str] = [
            "Energy.Active.Import.Register", "Power.Active.Import",
        ]  # MeterValuesSampledData, updated by ChangeConfiguration
        self._clock_aligned_changed = asyncio.Event()
        self._last_aligned_boundary: Optional[datetime.datetime] = None
        self._server_config: dict[str, str] = {}  # stores config sent by server
        self._local_list_version: int = 0
        self._local_auth_list: dict[str, dict] = {}
        self._config_store: dict[str, tuple[str, bool]] = {
            # key: (value, readonly)
            "MeterValueSampleInterval": ("60", False),
            "HeartbeatInterval": ("30", False),
            "NumberOfConnectors": ("1", True),
            "ChargeProfileMaxStackLevel": ("3", True),
            "ChargingScheduleAllowedChargingRateUnit": ("Current,Power", True),
            "ChargingScheduleMaxPeriods": ("24", True),
            "MaxChargingProfilesInstalled": ("5", True),
            "SupportedFeatureProfiles": (
                "Core,SmartCharging,LocalAuthListManagement,RemoteTrigger", True
            ),
            "AuthorizeRemoteTxRequests": ("true", False),
            "LocalAuthListEnabled": ("true", False),
            "LocalAuthListMaxLength": ("20", True),
            "SendLocalListMaxLength": ("20", True),
            "StopTransactionOnInvalidId": ("false", False),
            "StopTransactionOnEVSideDisconnect": ("true", True),
            "UnlockConnectorOnEVSideDisconnect": ("true", True),
            "WebSocketPingInterval": ("30", True),
            "MeterValuesAlignedData": ("", False),
            "ClockAlignedDataInterval": ("0", False),
            "MeterValuesSampledData": (
                "Energy.Active.Import.Register,Power.Active.Import", False
            ),
            "StopTxnSampledData": ("", False),
            "StopTxnAlignedData": ("", False),
            "ConnectorPhaseRotation": ("1.RST", True),
            "GetConfigurationMaxKeys": ("50", True),
        }
        # Start delay / ramp-up: set on the web page (saved), else the
        # values passed in (__main__'s defaults)
        saved_ramp = persistence.load_ramp_setting()
        if isinstance(saved_ramp, dict):
            try:
                start_delay_s = float(saved_ramp.get("start_delay_s", start_delay_s))
                ramp_up_s = float(saved_ramp.get("ramp_up_s", ramp_up_s))
            except (TypeError, ValueError):
                pass
        self._charger_sim = ChargerSimulator(
            current_amps=current_amps,
            start_delay_s=start_delay_s,
            ramp_up_s=ramp_up_s,
        )
        self._shared_state.start_delay_s = self._charger_sim.start_delay_s
        self._shared_state.ramp_up_s = self._charger_sim.ramp_up_s
        # Current: the HA setting is the charger's maximum (like a real
        # Wallbox's max-current setting). The supplier's chargingALimitConn1
        # can lower it but never raise it; the charger uses the lower of the two.
        self._max_current_amps: int = self._charger_sim.current_amps
        self._server_limit_amps: Optional[float] = None
        self._apply_current()

        # --- Offline message queue ---
        # Built with a live connection (tests, simple use) = already registered.
        # __main__ builds it with connection=None and calls attach() per socket;
        # it only counts as online once BootNotification is accepted.
        self._registered: bool = connection is not None
        self._traffic = TrafficRecorder(
            self._shared_state, lambda: self._heartbeat_interval,
        )
        # For the web GUI: every OCPP frame, and the charging sessions
        data_dir = getattr(persistence, "data_dir", None)
        data_dir = data_dir if isinstance(data_dir, str) else None
        self.message_log = MessageLog(data_dir=data_dir)
        self.sessions = SessionLog(data_dir)
        self._inflight_calls: set[asyncio.Future] = set()
        self._drain_lock = asyncio.Lock()
        loaded = persistence.load_offline_queue()
        self._offline_queue: list[dict] = [
            e for e in (loaded if isinstance(loaded, list) else [])
            if isinstance(e, dict) and "action" in e and "payload" in e
        ]
        for e in self._offline_queue:
            e["_held"] = True
        self._last_saved_queue: str = self._queue_json()
        self._shared_state.held_messages = len(self._offline_queue)
        self._queue_seq: int = max((e.get("seq", 0) for e in self._offline_queue), default=0) + 1
        self._last_local_tx_id: int = 0
        if self._offline_queue:
            logger.info(
                "Loaded %d held message(s) from a previous run; will send on connect",
                len(self._offline_queue),
            )

        # --- StopTransaction transactionData ---
        # Empty by default, as reported by Wallbox Pulsar Plus firmware
        # (StopTxnSampledData = StopTxnAlignedData = ""): no transactionData
        # unless the server asks for it via ChangeConfiguration.
        self._stop_txn_sampled: list[str] = []
        self._stop_txn_aligned: list[str] = []
        self._stop_txn_data: list[dict] = []

        # Plugged In survives a restart, like a cable left in a real charger:
        # it boots as Preparing so the server can start a new session.
        self._plugged_in = persistence.load_plugged_in() is True
        if self._plugged_in and self.sessions.plugged_open is None:
            # plugged in from before plugged-in stretches were recorded
            self.sessions.plugged_open = {"start": _now_iso(), "by": None}
        self._shared_state.plugged_in = self._plugged_in
        if self._plugged_in:
            self.state = ChargePointStatus.preparing
            self._shared_state.state = self.state
            logger.info("Car was plugged in when the add-on stopped: starting as Preparing")

        self._profile_scheduler = ChargingProfileScheduler(
            rated_power_w=self._charger_sim.rated_power_kw * 1000
        )
        # A transaction still saved as open means the last run never stopped
        # it (power cut, crash, SIGKILL): close it the way a real charger does.
        # Or the add-on restarted mid-session on purpose: continue it.
        self._recover_interrupted_transaction()
        self._close_orphan_session()

    def set_plugged_in(self, plugged_in: bool, source: Optional[str] = None) -> None:
        """Record the Plugged In switch, saved so it survives a restart.

        `source` (e.g. "schedule", "auto re-plug", "Home Assistant") is kept
        with plug-ins that never got a session, for the Sessions tab."""
        self._shared_state.plugged_in = plugged_in
        if plugged_in != self._plugged_in:
            self._plugged_in = plugged_in
            self._persistence.save_plugged_in(plugged_in)
            self.sessions.plugged(plugged_in, source)

    # --- For the web GUI -------------------------------------------------

    def provider_info(self) -> dict:
        """What the OCPP server has set: configuration, local list, profiles."""
        return {
            "configuration": [
                {"key": k, "value": v, "readonly": ro, "set_by_server": k in self._server_config}
                for k, (v, ro) in self._config_store.items()
            ],
            "local_list_version": self._local_list_version,
            "local_auth_list": list(self._local_auth_list.values()),
            "charging_profiles": self._profile_scheduler.profiles_info(),
            "profile_limit_kw": self._profile_scheduler.get_current_limit_kw(),
            "provider_limit_amps": self._server_limit_amps,
            "max_amps": self._max_current_amps,
            "effective_amps": self._effective_amps(),
        }

    def held_messages_info(self) -> list[dict]:
        """Transaction messages waiting to be sent, oldest first."""
        from src.traffic import summarise_command
        out = []
        for e in self._offline_queue:
            action = str(e.get("action", "")).removesuffix("Payload")
            payload = e.get("payload") or {}
            camel = {
                "".join(w if i == 0 else w.title() for i, w in enumerate(k.split("_"))): v
                for k, v in payload.items()
            }
            out.append({"seq": e.get("seq"), "action": action, "summary": summarise_command(action, camel)})
        return out

    def sessions_info(self) -> dict:
        return self.sessions.snapshot(
            self._energy_register_wh if self._transaction_id is not None else None,
        )

    # --- Connection lifecycle -------------------------------------------

    @property
    def is_online(self) -> bool:
        """Connected and BootNotification accepted."""
        return self._registered and self._connection is not None

    def attach(self, connection) -> None:
        """Use a new websocket. Not online until BootNotification is accepted."""
        self._connection = connection
        self._registered = False

    def detach(self) -> None:
        """The websocket is gone: go offline and fail any call still waiting."""
        self._registered = False
        self._connection = None
        self._shared_state.connected_to_server = False
        for task in list(self._inflight_calls):
            task.cancel()
        if self._transaction_id is not None:
            logger.info(
                "Offline mid-transaction: still charging, holding transaction "
                "messages until reconnected",
            )

    # --- Every OCPP frame: message log and last command (Overview) -----

    async def route_message(self, raw_msg):
        """Every message from the server passes through here."""
        self._record_traffic(raw_msg, incoming=True)
        return await super().route_message(raw_msg)

    async def _send(self, message):
        """Every message to the server (calls and our replies) passes through here."""
        self._record_traffic(message, incoming=False)
        return await super()._send(message)

    def _record_traffic(self, raw, incoming: bool) -> None:
        """Feed every frame to the diagnostics recorder (src/traffic.py)."""
        self._traffic.record(raw, incoming)
        self.message_log.record(raw, incoming)

    async def call(self, payload, *args, **kwargs):
        """BaseChargePoint.call that fails fast when the connection drops.

        Without this, a call in flight when the socket dies waits the full
        response timeout while holding the library's call lock, which also
        blocks the BootNotification on the next connection.
        """
        if self._connection is None:
            raise ChargePointOffline("not connected")
        task = asyncio.ensure_future(super().call(payload, *args, **kwargs))
        self._inflight_calls.add(task)
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError:
            task.cancel()
            raise
        finally:
            self._inflight_calls.discard(task)
        if task.cancelled():
            raise ChargePointOffline("connection lost")
        return task.result()

    # --- Offline message queue ------------------------------------------

    def _queue_json(self) -> str:
        data = [
            {k: v for k, v in e.items() if not k.startswith("_")}
            for e in self._offline_queue
        ]
        return json.dumps(data, default=str, sort_keys=True)

    def _save_queue(self) -> None:
        """Persist the queue if it changed (so held messages survive a restart)."""
        current = self._queue_json()
        if current == self._last_saved_queue:
            return
        self._persistence.save_offline_queue(json.loads(current))
        self._last_saved_queue = current
        self._shared_state.held_messages = len(self._offline_queue)

    def _trim_queue(self) -> None:
        dropped = 0
        while len(self._offline_queue) > OFFLINE_QUEUE_MAX:
            idx = next(
                (i for i, e in enumerate(self._offline_queue)
                 if e["action"] == "MeterValuesPayload"),
                None,
            )
            if idx is None:
                break
            self._offline_queue.pop(idx)
            dropped += 1
        if dropped:
            logger.warning("Offline queue full: dropped %d oldest MeterValues", dropped)

    def _new_local_tx_id(self) -> int:
        """Provisional (negative) transactionId until the server assigns one."""
        local = -int(time.time())
        if self._last_local_tx_id < 0 and local >= self._last_local_tx_id:
            local = self._last_local_tx_id - 1  # same second: keep ids unique
        self._last_local_tx_id = local
        return local

    def _enqueue(self, request, local_tx_id: Optional[int] = None) -> dict:
        """Add a transaction message to the end of the ordered queue."""
        entry = {
            "seq": self._queue_seq,
            "action": type(request).__name__,
            "payload": _payload_to_dict(request),
            "_request": request,
        }
        if local_tx_id is not None:
            entry["local_tx_id"] = local_tx_id
        self._queue_seq += 1
        self._offline_queue.append(entry)
        self._trim_queue()
        return entry

    async def _send_tx(self, request, local_tx_id: Optional[int] = None):
        """Send a transaction-related message through the ordered queue.

        Returns the server's response, or None if the message is being held
        until the connection comes back.
        """
        entry = self._enqueue(request, local_tx_id)
        try:
            if self._registered:
                await self._drain_queue()
        finally:
            self._save_queue()
        if any(e is entry for e in self._offline_queue):
            logger.info(
                "Offline: holding %s (%d message(s) queued)",
                entry["action"].removesuffix("Payload"), len(self._offline_queue),
            )
        return entry.get("_response")

    def _request_from_entry(self, entry: dict):
        request = entry.get("_request")
        if request is None:  # loaded from disk
            request = getattr(call, entry["action"])(**entry["payload"])
            entry["_request"] = request
        return request

    def _remap_transaction_id(self, old: int, new) -> None:
        for e in self._offline_queue:
            if e["payload"].get("transaction_id") == old:
                e["payload"]["transaction_id"] = new
                if e.get("_request") is not None:
                    e["_request"].transaction_id = new
        if self._transaction_id == old:
            self._transaction_id = new
            self._shared_state.transaction_id = new
            self._save_active_transaction()
        self.sessions.remap_transaction_id(old, new)

    def _drop_transaction(self, local_tx_id: int) -> None:
        before = len(self._offline_queue)
        self._offline_queue = [
            e for e in self._offline_queue
            if e["payload"].get("transaction_id") != local_tx_id
        ]
        if before != len(self._offline_queue):
            logger.warning(
                "Dropped %d held message(s) for a transaction the server never accepted",
                before - len(self._offline_queue),
            )

    async def _drain_queue(self) -> None:
        """Send held messages in order while online. Safe to call concurrently."""
        async with self._drain_lock:
            sent_held = 0
            try:
                while self._offline_queue and self._registered:
                    entry = self._offline_queue[0]
                    try:
                        response = await self.call(self._request_from_entry(entry))
                    except _CONNECTION_ERRORS as e:
                        for queued in self._offline_queue:
                            queued["_held"] = True
                        logger.info(
                            "Holding %d message(s) until reconnected (%s)",
                            len(self._offline_queue), e or type(e).__name__,
                        )
                        return
                    except Exception:
                        logger.warning(
                            "Server rejected held %s; dropping it",
                            entry["action"], exc_info=True,
                        )
                        self._offline_queue.pop(0)
                        if "local_tx_id" in entry:
                            self._drop_transaction(entry["local_tx_id"])
                        continue
                    self._offline_queue.pop(0)
                    entry["_response"] = response
                    if entry.get("_held"):
                        sent_held += 1
                    if "local_tx_id" in entry:
                        real_id = getattr(response, "transaction_id", None)
                        if real_id is None:
                            self._drop_transaction(entry["local_tx_id"])
                        else:
                            self._remap_transaction_id(entry["local_tx_id"], real_id)
            finally:
                if sent_held:
                    logger.info("Sent %d held message(s) after reconnecting", sent_held)
                self._save_queue()

    # --- Interrupted transactions (power loss) --------------------------

    def _save_active_transaction(self) -> None:
        """Save the open transaction (or clear it) so a restart can close it."""
        if self._transaction_id is None:
            self._persistence.save_active_transaction(None)
            return
        self._persistence.save_active_transaction({
            "transaction_id": self._transaction_id,
            "id_tag": self._transaction_id_tag,
            "energy_wh": self._energy_register_wh,
            "start_energy_wh": self._transaction_start_energy_wh,
            "timestamp": _now_iso(),
            "stop_txn_sampled": self._stop_txn_sampled,
            "stop_txn_data": self._stop_txn_data,
            "profile": self._tx_profile,
            "resume": self._suspending,  # left open on purpose, to continue after a restart
        })

    def suspend_for_restart(self) -> bool:
        """At shutdown, mid-session: leave the transaction open (no
        StopTransaction) so the next start continues it, as a charger does
        across a dropped connection. False if there's nothing to continue."""
        if not self.resume_on_restart or self._transaction_id is None or not self._plugged_in:
            return False
        self._checkpoint_energy()  # energy up to now, saved
        self._suspending = True
        self._save_active_transaction()
        logger.info("Transaction %s left open to continue after the restart", self._transaction_id)
        return True

    def _resume_transaction(self, saved: dict, age_s: float) -> None:
        """Continue a transaction left open by suspend_for_restart."""
        self._transaction_id = saved["transaction_id"]
        self._transaction_id_tag = saved.get("id_tag")
        self._transaction_start_energy_wh = int(saved.get("start_energy_wh", self._energy_register_wh))
        self._stop_txn_sampled = list(saved.get("stop_txn_sampled") or [])
        self._stop_txn_data = list(saved.get("stop_txn_data") or [])
        if isinstance(saved.get("profile"), dict):
            self._tx_profile = normalise_profile(saved["profile"])
            try:
                self._profile_scheduler.set_profile(self._tx_profile)
            except Exception:
                logger.warning("Couldn't restore the session's charging profile", exc_info=True)
        if self.sessions.current is None:
            self.sessions.start(self._transaction_id, self._transaction_id_tag,
                                self._transaction_start_energy_wh, saved.get("timestamp") or _now_iso())
        self._last_meter_time = time.monotonic()
        self._charger_sim.start_charging()
        self._resumed = True
        self.state = ChargePointStatus.charging
        self._shared_state.state = self.state
        self._shared_state.transaction_id = self._transaction_id
        self._save_active_transaction()  # open, no longer waiting to continue
        logger.info("Continuing transaction %s after the restart (stopped %d s ago)",
                    self._transaction_id, round(age_s))

    def _recover_interrupted_transaction(self) -> None:
        saved = self._persistence.load_active_transaction()
        if not isinstance(saved, dict) or saved.get("transaction_id") is None:
            return
        tx_id = saved["transaction_id"]
        already_stopped = any(
            e["action"] == "StopTransactionPayload"
            and e["payload"].get("transaction_id") == tx_id
            for e in self._offline_queue
        )
        reason = Reason.power_loss
        if saved.get("resume") and not already_stopped:
            age = _age_s(saved.get("timestamp"))
            if self.resume_on_restart and self._plugged_in and age is not None and 0 <= age <= RESUME_MAX_S:
                self._resume_transaction(saved, age)
                return
            reason = Reason.reboot  # stopped on purpose, but too long ago (or unplugged) to continue
            logger.info("Not continuing transaction %s after the restart (%s): stopping it", tx_id,
                        "the car was unplugged" if not self._plugged_in
                        else "Continue session after a restart is off" if not self.resume_on_restart
                        else f"stopped more than {RESUME_MAX_S // 60} min ago")
        if not already_stopped:
            # Last known meter reading and time = the moment power was lost
            meter_stop = int(saved.get("energy_wh", self._energy_register_wh))
            timestamp = saved.get("timestamp") or _now_iso()
            transaction_data = list(saved.get("stop_txn_data") or [])
            measurands = saved.get("stop_txn_sampled") or []
            if measurands:
                end = build_meter_values(
                    reading=None, energy_register_wh=meter_stop,
                    context="Transaction.End", measurands=measurands,
                    timestamp=timestamp,
                )[0]
                if end["sampledValue"]:
                    transaction_data.append(end)
            self._enqueue(call.StopTransactionPayload(
                transaction_id=tx_id,
                id_tag=saved.get("id_tag"),
                meter_stop=meter_stop,
                timestamp=timestamp,
                reason=reason,
                transaction_data=transaction_data or None,
            ))
            self._offline_queue[-1]["_held"] = True
            self._save_queue()
            if reason == Reason.power_loss:
                logger.warning(
                    "Transaction %s was still open when the add-on last stopped "
                    "(power cut or crash); holding StopTransaction (PowerLoss, %d Wh)",
                    tx_id, meter_stop,
                )
            self.sessions.stop(meter_stop, reason, timestamp, tx_id)
        self._persistence.save_active_transaction(None)

    def _close_orphan_session(self) -> None:
        """A session saved as running with no open transaction (e.g. the add-on
        stopped between the two saves): close it in the history."""
        if self.sessions.current is not None and self._transaction_id is None:
            self.sessions.stop(self._energy_register_wh, Reason.power_loss)

    # --- StopTransaction transactionData ----------------------------------

    def _record_stop_txn_reading(
        self,
        reading: Optional[ChargerReading],
        measurands: list[str],
        context: str,
        timestamp: Optional[str] = None,
        energy_wh: Optional[int] = None,
    ) -> None:
        """Keep a reading for the StopTransaction transactionData."""
        if self._transaction_id is None or not measurands:
            return
        mv = build_meter_values(
            reading=reading,
            energy_register_wh=self._energy_register_wh if energy_wh is None else energy_wh,
            context=context,
            measurands=measurands,
            timestamp=timestamp,
            soc=self._soc_for_report(),
        )[0]
        if not mv["sampledValue"]:
            return
        self._stop_txn_data.append(mv)
        if len(self._stop_txn_data) > STOP_TXN_MAX_READINGS:
            # Halve the resolution, always keeping Transaction.Begin and the latest
            data = self._stop_txn_data
            self._stop_txn_data = [data[0], *data[1:-1][1::2], data[-1]]
        self._save_active_transaction()

    # --- Charging current -------------------------------------------------

    def _effective_amps(self) -> int:
        """Lower of the max current and the supplier's limit, as a supported setting."""
        limit = float(self._max_current_amps)
        if self._server_limit_amps is not None:
            limit = min(limit, self._server_limit_amps)
        allowed = [a for a in VALID_CURRENT_SETTINGS if a <= limit + 1e-9]
        return max(allowed) if allowed else VALID_CURRENT_SETTINGS[0]  # 6A minimum

    def _apply_current(self) -> None:
        effective = self._effective_amps()
        if effective != self._charger_sim.current_amps:
            self._charger_sim.current_amps = effective  # logs the change
        self._shared_state.current_amps_setting = self._max_current_amps
        self._shared_state.current_amps_effective = effective
        self._shared_state.current_amps_provider_limit = self._server_limit_amps

    def set_voltage_source(self, source) -> None:
        """Where the simulated charger gets the supply voltage (Settings › Voltage)."""
        self._charger_sim.voltage_source = source

    def set_ramp(self, start_delay_s: float, ramp_up_s: float) -> None:
        """Simulated car start-up: seconds before it draws current, then seconds
        to ramp to full power (0-60 each). Saved; applies from the next start."""
        delay, ramp = float(start_delay_s), float(ramp_up_s)
        if not (0 <= delay <= 60 and 0 <= ramp <= 60):
            raise ValueError("Start delay and ramp-up must be 0 to 60 seconds")
        self._charger_sim.set_ramp(delay, ramp)
        self._persistence.save_ramp_setting({"start_delay_s": delay, "ramp_up_s": ramp})
        self._shared_state.start_delay_s = delay
        self._shared_state.ramp_up_s = ramp
        logger.info("Start delay %gs, ramp-up %gs", delay, ramp)

    def set_max_current(self, amps: int) -> None:
        """The HA current setting: the charger's maximum, remembered across restarts."""
        if amps not in VALID_CURRENT_SETTINGS:
            raise ValueError(f"Invalid current setting {amps}A. Valid: {VALID_CURRENT_SETTINGS}")
        self._max_current_amps = amps
        self._persistence.save_current_setting({
            "amps": amps,
        })
        self._apply_current()
        if self._charger_sim.current_amps < amps:
            logger.info(
                "Max current set to %dA; supplier limit keeps it at %dA",
                amps, self._charger_sim.current_amps,
            )
        else:
            logger.info("Max current set to %dA", amps)

    @property
    def energy_register_kwh(self) -> float:
        return self._energy_register_wh / 1000.0

    def _zero_power_state(self) -> None:
        """Zero out power-related shared state values."""
        self._shared_state.power_kw = 0.0
        self._shared_state.current_a = 0.0
        self._shared_state.power_offered_kw = 0.0
        # power_source / power_entity_value describe the configuration (is a
        # power entity in use?), not whether power is flowing, so they're left
        # alone here; see set_power_override.

    def set_power_override(self, power_kw: Optional[float]) -> None:
        """Real power from your power sensor (kW), or None for the simulation."""
        self._power_override = power_kw
        self._shared_state.power_source = "simulated" if power_kw is None else "entity"
        self._shared_state.power_entity_value = power_kw

    def _set_heartbeat_interval(self, seconds: int) -> None:
        """Apply a new heartbeat interval and keep the reported config in sync."""
        self._heartbeat_interval = seconds
        _, readonly = self._config_store["HeartbeatInterval"]
        self._config_store["HeartbeatInterval"] = (str(seconds), readonly)
        self._heartbeat_interval_changed.set()  # wake the loop to use it now
        logger.info("Heartbeat interval set to %ds", seconds)

    async def send_boot_notification(
        self, model: str, vendor: str,
        serial_number: str = "", firmware_version: str = "",
    ) -> int:
        # Optional fields are left out (None is dropped from the message)
        # rather than sent as empty strings.
        request = call.BootNotificationPayload(
            charge_point_model=model,
            charge_point_vendor=vendor,
            charge_point_serial_number=serial_number or None,
            charge_box_serial_number=serial_number or None,
            firmware_version=firmware_version or None,
            meter_type="Internal NON compliant",
        )
        self._boot_request = request

        while True:
            response: call_result.BootNotificationPayload = await self.call(request)

            if response.status == RegistrationStatus.accepted:
                self._registered = True
                self._shared_state.connected_to_server = True
                # Messages held while offline go first, oldest first
                await self._drain_queue()
                await self._send_status_for_connector(0)
                await self.send_status()
                interval = response.interval if response.interval and response.interval > 0 else 30
                # OCPP 1.6: the interval in an accepted BootNotification is the
                # heartbeat interval the CP must use (and report).
                self._set_heartbeat_interval(interval)
                return interval
            elif response.status == RegistrationStatus.pending:
                wait = response.interval if response.interval and response.interval > 0 else 30
                logger.info("BootNotification pending, retrying in %ds", wait)
                await asyncio.sleep(wait)
            else:
                logger.error("BootNotification rejected")
                raise SystemExit("BootNotification rejected by server")

    async def heartbeat_loop(self, interval: int | None = None) -> None:
        if interval is not None and interval > 0 and interval != self._heartbeat_interval:
            self._set_heartbeat_interval(interval)
        self._heartbeat_interval_changed.clear()
        while True:
            # Sleep for the current interval; restart the wait early if the
            # server changes HeartbeatInterval so the new value applies now.
            try:
                await asyncio.wait_for(
                    self._heartbeat_interval_changed.wait(), self._heartbeat_interval,
                )
                self._heartbeat_interval_changed.clear()
                continue
            except asyncio.TimeoutError:
                pass
            try:
                await self.call(call.HeartbeatPayload())
                if self._offline_queue:
                    await self._drain_queue()  # retry anything a timeout held back
            except websockets.exceptions.ConnectionClosed:
                # Socket is gone — exit so the supervisor reconnects instead of
                # leaving a zombie loop spamming a dead connection.
                logger.info("Heartbeat loop stopping: connection closed")
                raise
            except asyncio.TimeoutError:
                # One line: the connection's own keepalive notices if it's really gone
                logger.warning("Heartbeat: no reply from the OCPP server in time")
            except Exception:
                logger.warning("Heartbeat cycle failed", exc_info=True)

    async def meter_values_loop(self) -> None:
        while True:
            await asyncio.sleep(self._meter_value_interval)
            # Runs for the life of the charger, online or not: charging and
            # the energy register carry on while offline.
            try:
                await self.send_meter_values()
            except _CONNECTION_ERRORS:
                logger.debug("Meter values not sent: offline")
            except Exception:
                logger.warning("Meter values cycle failed", exc_info=True)

    async def _send_status_for_connector(self, connector_id: int, status: ChargePointStatus | None = None) -> None:
        """Send StatusNotification for a connector (skipped while offline).

        Status isn't queued: the current status is sent after BootNotification
        on reconnect instead.
        """
        if not self._registered:
            logger.debug("Offline: not sending StatusNotification")
            return
        if status is None:
            status = self.state
            if connector_id == 0 and status != ChargePointStatus.unavailable:
                # OCPP 1.6: the charger itself (connector 0) is only ever
                # Available, Unavailable or Faulted, whatever the cable does.
                status = ChargePointStatus.available
        request = call.StatusNotificationPayload(
            connector_id=connector_id,
            error_code=ChargePointErrorCode.no_error,
            status=status,
            timestamp=_now_iso(),
        )
        try:
            await self.call(request)
        except _CONNECTION_ERRORS:
            # A status lost to a dropped connection must never abort what
            # called it (e.g. the StopTransaction that follows Finishing).
            logger.debug("StatusNotification not sent: offline")

    async def send_status(self) -> None:
        await self._send_status_for_connector(self.connector_id)

    DEBUG_STATUSES = ("Available", "Preparing", "Charging", "SuspendedEV", "SuspendedEVSE",
                      "Finishing", "Unavailable", "Faulted")

    async def debug_send(self, message: str, status: Optional[str] = None) -> dict:
        """Diagnostics › Debug: send a message now, as the charger. A status
        sent here doesn't change the charger's own state: its next real change
        is sent as usual. Faulted goes with error code OtherError."""
        if not self.is_online:
            raise ValueError("Not connected to the supplier's server")
        response = None
        try:
            if message == "StatusNotification":
                if status not in self.DEBUG_STATUSES:
                    raise ValueError("Pick a status: " + ", ".join(self.DEBUG_STATUSES))
                st = ChargePointStatus(status)
                response = await self.call(call.StatusNotificationPayload(
                    connector_id=self.connector_id,
                    error_code=(ChargePointErrorCode.other_error if status == "Faulted"
                                else ChargePointErrorCode.no_error),
                    status=st,
                    timestamp=_now_iso(),
                ))
            elif message == "MeterValues":
                await self.send_meter_values()
            elif message == "Heartbeat":
                response = await self.call(call.HeartbeatPayload())
            elif message == "BootNotification":
                if self._boot_request is None:
                    raise ValueError("No BootNotification has been sent yet")
                response = await self.call(self._boot_request)
            else:
                raise ValueError("Message must be StatusNotification, MeterValues, Heartbeat or BootNotification")
        except ValueError:
            raise
        except Exception as err:
            raise ValueError(f"{message} not sent: {err or type(err).__name__}")
        logger.info("Debug: sent %s%s from the web page", message,
                    f" ({status})" if message == "StatusNotification" else "")
        return {"message": message, "response": _payload_to_dict(response) if response is not None else None}

    async def send_status_unavailable(self) -> None:
        await self._send_status_for_connector(
            self.connector_id, ChargePointStatus.unavailable,
        )

    # --- SoC and car full ------------------------------------------------

    def set_soc(self, soc: Optional[float]) -> None:
        """Car's state of charge (%) from your SoC sensor or the test value, or None if unknown/unset."""
        if soc is not None:
            soc = max(0.0, min(100.0, float(soc)))
        self._soc = soc
        self._shared_state.soc_percent = soc

    @property
    def car_full(self) -> bool:
        """Only ever true with a SoC entity set and reading 100%."""
        return self._soc is not None and self._soc >= 100.0

    def _taper_factor(self) -> float:
        """Fraction of power the car accepts at its SoC (CC/CV taper near full).

        Full power up to TAPER_START_SOC, then down linearly to TAPER_MIN_FACTOR
        at 100%. 1.0 without a SoC entity.
        """
        if self._soc is None or self._soc <= TAPER_START_SOC:
            return 1.0
        span = (min(self._soc, 100.0) - TAPER_START_SOC) / (100.0 - TAPER_START_SOC)
        return round(1.0 - (1.0 - TAPER_MIN_FACTOR) * span, 4)

    def _soc_for_report(self) -> Optional[float]:
        """SoC to put in meter values: only while a car is connected."""
        if self.state in (ChargePointStatus.available, ChargePointStatus.unavailable,
                          ChargePointStatus.faulted):
            return None
        return self._soc

    async def _apply_profile_state(self) -> None:
        """Set Charging / SuspendedEVSE / SuspendedEV for an open transaction.

        SuspendedEVSE: the charging profile allows 0 kW (charger not offering).
        SuspendedEV:   the car is full (SoC entity at 100%) and stops drawing,
                       like a real car; charging resumes if SoC drops below 100%.
        The charger pause wins if both apply, as on a real charger.
        """
        if self._transaction_id is None:
            return
        if self.state not in (
            ChargePointStatus.charging,
            ChargePointStatus.suspended_evse,
            ChargePointStatus.suspended_ev,
        ):
            return
        limit_kw = (
            self._profile_scheduler.get_current_limit_kw()
            if self._profile_scheduler.has_profile else None
        )
        if limit_kw is not None and limit_kw <= 0:
            target = ChargePointStatus.suspended_evse
        elif self.car_full:
            target = ChargePointStatus.suspended_ev
        else:
            target = ChargePointStatus.charging
        if target == self.state:
            return

        self._checkpoint_energy()  # close the energy interval at the change
        if target == ChargePointStatus.charging:
            if limit_kw is not None:
                logger.info("Profile says charge at %.1f kW — resuming", limit_kw)
            else:
                logger.info("Resuming charge (car no longer full)")
            self._charger_sim.start_charging()
        else:
            if target == ChargePointStatus.suspended_evse:
                logger.info("Profile says pause — suspending charge")
            else:
                logger.info("Car full (SoC %.0f%%) — car stopped drawing power", self._soc)
            self._charger_sim.stop_charging()
            self._zero_power_state()
        self.state = target
        self._shared_state.state = self.state
        await self.send_status()

    def _checkpoint_energy(self) -> None:
        """Close the current energy interval at a charging state change.

        Call this *before* changing state. While charging it counts the
        energy delivered up to this exact moment; while not charging it just
        restarts the interval. Without it, the first reading after a start
        multiplied the preceding idle time by the new charging power
        (phantom energy), and a stop dropped the energy since the last
        reading from meterStop.
        """
        self._take_reading()

    def _take_reading(self) -> Optional[ChargerReading]:
        """Sample the charger and add energy delivered since the last reading.

        Shared by periodic and clock-aligned meter values, so energy is only
        ever counted once: each call integrates just the time since the
        previous call. Returns None when not delivering power.
        """
        now = time.monotonic()
        prev = self._last_meter_time
        elapsed_hours = (now - prev) / 3600.0
        self._last_meter_time = now

        if self.state != ChargePointStatus.charging:
            if self._transaction_id is not None:
                self._save_active_transaction()  # paused, still open
            self._shared_state.energy_kwh = self.energy_register_kwh
            # Not charging: no power
            self._zero_power_state()
            return None

        reading, full_reading = self._instant_reading(now)
        if self._power_override is not None:
            energy_added_kwh = reading.power_kw * elapsed_hours
        else:
            # Integrate over the ramp rather than multiplying the whole interval
            # by the instantaneous power, so the delay/ramp is billed exactly.
            ramp_avg = self._charger_sim.average_ramp_factor(prev, now)
            energy_added_kwh = (
                full_reading.power_kw * ramp_avg * self._taper_factor() * elapsed_hours
            )

        self._energy_register_wh += round(energy_added_kwh * 1000)
        self._persistence.save_energy_register_wh(self._energy_register_wh)

        self._publish_reading(reading)
        self._shared_state.energy_kwh = self.energy_register_kwh
        if self._transaction_id is not None:
            self._save_active_transaction()
        return reading

    def _instant_reading(self, now: float) -> tuple[ChargerReading, ChargerReading]:
        """What the charger is delivering at `now`: (reading, full-power reading).

        Applies the car's start delay / ramp-up, or the power entity override.
        Touches no energy accounting, so it's safe to call at any time.
        """
        full_reading = self._charger_sim.sample_full()
        sim_reading = self._charger_sim.scale(
            full_reading, self._charger_sim.ramp_factor(now) * self._taper_factor(),
        )

        # Use power override from integration if available
        real_power = self._power_override
        if real_power is not None:
            # Clamp negatives to 0 (e.g. solar export), cap at charger max.
            # A real measured power already includes the car's own ramp-up,
            # so the simulated delay/ramp isn't applied on top of it.
            capped_power = max(0.0, min(real_power, full_reading.power_kw))
            current_a = round((capped_power * 1000) / sim_reading.voltage, 2) if capped_power > 0 else 0.0
            reading = ChargerReading(
                power_kw=capped_power,
                voltage=sim_reading.voltage,
                current_a=current_a,
                frequency_hz=sim_reading.frequency_hz,
                power_offered_kw=sim_reading.power_offered_kw,
                current_offered_a=sim_reading.current_offered_a,
            )
            self._shared_state.power_source = "entity"
            self._shared_state.power_entity_value = real_power
        else:
            reading = sim_reading
            self._shared_state.power_source = "simulated"
            self._shared_state.power_entity_value = None
        return reading, full_reading

    def _publish_reading(self, reading: ChargerReading) -> None:
        self._shared_state.power_kw = reading.power_kw
        self._shared_state.voltage = reading.voltage
        self._shared_state.current_a = reading.current_a
        self._shared_state.frequency_hz = reading.frequency_hz
        self._shared_state.power_offered_kw = reading.power_offered_kw

    def refresh_live_power(self) -> None:
        """Update the live power figures for the API between meter readings.

        Called by the chart sampler and on every /api/state poll, so the
        page and Home Assistant see the start delay, ramp-up, profile pauses
        and current changes straight away, not once per
        MeterValueSampleInterval. Energy is still only counted
        by _take_reading, so this never changes the energy register.
        """
        if self.state != ChargePointStatus.charging or not self._charger_sim.is_charging:
            self._zero_power_state()
            return
        reading, _ = self._instant_reading(time.monotonic())
        self._publish_reading(reading)

    async def send_meter_values(self) -> None:
        """Periodic (Sample.Periodic) meter values — unchanged payload."""
        await self._apply_profile_state()
        reading = self._take_reading()

        # Only the measurands the server asked for in MeterValuesSampledData;
        # ones we can't supply (e.g. SoC, or Frequency while idle) are skipped.
        meter_value = build_meter_values(
            reading=reading,
            energy_register_wh=self._energy_register_wh,
            context="Sample.Periodic",
            measurands=self._sampled_measurands,
            soc=self._soc_for_report(),
        )
        self._record_stop_txn_reading(
            reading, self._stop_txn_sampled, "Sample.Periodic",
            timestamp=meter_value[0]["timestamp"],
        )
        # transactionId whenever a transaction is open (incl. paused by profile)
        request = call.MeterValuesPayload(
            connector_id=self.connector_id,
            transaction_id=self._transaction_id,
            meter_value=meter_value,
        )
        if self._transaction_id is not None:
            await self._send_tx(request)  # held while offline
        elif self._registered:
            await self.call(request)  # idle readings aren't held

    async def send_clock_aligned_meter_values(
        self, boundary: Optional[datetime.datetime] = None,
    ) -> None:
        """Clock-aligned (Sample.Clock) meter values, per MeterValuesAlignedData."""
        reading = self._take_reading()
        timestamp = (
            boundary.strftime("%Y-%m-%dT%H:%M:%SZ") if boundary is not None else None
        )
        meter_value = build_meter_values(
            reading=reading,
            energy_register_wh=self._energy_register_wh,
            context="Sample.Clock",
            measurands=self._aligned_measurands,
            timestamp=timestamp,
            soc=self._soc_for_report(),
        )
        self._record_stop_txn_reading(
            reading, self._stop_txn_aligned, "Sample.Clock",
            timestamp=meter_value[0]["timestamp"],
        )
        kwargs = {}
        if self._transaction_id is not None:
            kwargs["transaction_id"] = self._transaction_id
        request = call.MeterValuesPayload(
            connector_id=self.connector_id,
            meter_value=meter_value,
            **kwargs,
        )
        if self._transaction_id is not None:
            await self._send_tx(request)  # held while offline
        elif self._registered:
            await self.call(request)  # idle readings aren't held

    def _set_clock_aligned_interval(self, seconds: int) -> None:
        self._clock_aligned_interval = seconds
        self._config_store["ClockAlignedDataInterval"] = (str(seconds), False)
        self._clock_aligned_changed.set()
        if seconds > 0:
            logger.info("Clock-aligned meter values every %ds", seconds)
        else:
            logger.info("Clock-aligned meter values disabled")

    async def clock_aligned_loop(self) -> None:
        """Send Sample.Clock meter values on ClockAlignedDataInterval boundaries."""
        while True:
            interval = self._clock_aligned_interval
            if interval <= 0:
                await self._clock_aligned_changed.wait()
                self._clock_aligned_changed.clear()
                continue

            now = datetime.datetime.now(datetime.timezone.utc)
            delay, boundary = _next_aligned(now, interval)
            # Guard against waking a hair early and resending the same boundary
            if self._last_aligned_boundary is not None and boundary <= self._last_aligned_boundary:
                _, boundary = _next_aligned(self._last_aligned_boundary, interval)
                delay = (boundary - now).total_seconds()

            try:
                await asyncio.wait_for(self._clock_aligned_changed.wait(), delay)
                self._clock_aligned_changed.clear()
                continue  # interval changed — recompute
            except asyncio.TimeoutError:
                pass

            self._last_aligned_boundary = boundary
            try:
                await self.send_clock_aligned_meter_values(boundary)
            except _CONNECTION_ERRORS:
                logger.debug("Clock-aligned meter values not sent: offline")
            except Exception:
                logger.warning("Clock-aligned meter values failed", exc_info=True)

    async def _do_start_transaction(self) -> None:
        """Start a charging transaction."""
        try:
            # OCPP 1.6 sequence after RemoteStart: (Preparing) -> StartTransaction
            # -> Charging. No intermediate Available/SuspendedEV, and connector 0
            # status only belongs at boot.
            id_tag = self._pending_id_tag or "NoAuthorization"
            self._resumed = False

            # Not charging yet: restart the energy interval so idle time
            # before the start isn't counted at charging power.
            self._checkpoint_energy()
            self._charger_sim.start_charging()
            self._transaction_start_energy_wh = self._energy_register_wh
            start_ts = _now_iso()
            request = call.StartTransactionPayload(
                connector_id=self.connector_id,
                id_tag=id_tag,
                meter_start=self._energy_register_wh,
                timestamp=start_ts,
            )
            # Online, the transactionId is the server's, as before. Only if
            # StartTransaction is held (offline) does the transaction run on a
            # provisional id, and messages sent for it are renumbered once the
            # server accepts the start.
            local_tx_id = self._new_local_tx_id()
            self._transaction_id_tag = id_tag
            self._stop_txn_data = []
            response = await self._send_tx(request, local_tx_id=local_tx_id)
            if response is None:
                if self._transaction_id is None:
                    self._transaction_id = local_tx_id
                logger.info("Transaction started offline (idTag %s); StartTransaction held", id_tag)
            else:
                self._transaction_id = response.transaction_id
                logger.info("Transaction started: %s (idTag %s)", self._transaction_id, id_tag)
            self.sessions.start(
                self._transaction_id, id_tag, self._transaction_start_energy_wh, start_ts,
            )
            self._record_stop_txn_reading(
                None, self._stop_txn_sampled, "Transaction.Begin", timestamp=start_ts,
                energy_wh=self._transaction_start_energy_wh,
            )
            self._save_active_transaction()

            # Transition to Charging — now update shared_state atomically
            self.state = ChargePointStatus.charging
            self._shared_state.state = self.state
            self._shared_state.transaction_id = self._transaction_id
            await self.send_status()
            if self.car_full:
                await self._apply_profile_state()  # plugged in already full
        except Exception:
            # Start failed: back to a consistent state
            logger.error("Failed to start transaction", exc_info=True)
            self._charger_sim.stop_charging()
            self._transaction_id = None
            self._transaction_id_tag = None
            self._stop_txn_data = []
            self._save_active_transaction()
            self.state = ChargePointStatus.preparing
            self._shared_state.state = self.state
            self._shared_state.transaction_id = None
            self._zero_power_state()

    async def _do_stop_transaction(
        self,
        final_state: ChargePointStatus = ChargePointStatus.preparing,
        reason: Reason = Reason.remote,
        announce: bool = False,
    ) -> None:
        """Stop the active transaction. final_state controls where we end up.

        announce: also send a StatusNotification for final_state once
        StopTransaction is done. Callers that send their own status
        afterwards (unplug, reset) or are shutting down leave it off."""
        request = None
        handled = False
        try:
            # Still Charging here: count energy up to now so meterStop is complete
            self._checkpoint_energy()
            transaction_id = self._transaction_id
            energy_delivered_kwh = (self._energy_register_wh - self._transaction_start_energy_wh) / 1000.0
            stop_ts = _now_iso()
            self._record_stop_txn_reading(
                None, self._stop_txn_sampled, "Transaction.End", timestamp=stop_ts,
            )
            transaction_data = self._stop_txn_data or None  # never an empty list
            self._charger_sim.stop_charging()
            self._profile_scheduler.clear_profile()

            # Send Finishing status before StopTransaction
            self.state = ChargePointStatus.finishing
            await self.send_status()

            request = call.StopTransactionPayload(
                transaction_id=transaction_id,
                id_tag=self._transaction_id_tag,  # the session's own tag (omitted if unknown)
                meter_stop=self._energy_register_wh,
                timestamp=stop_ts,
                reason=reason,
                transaction_data=transaction_data,
            )
            self.sessions.stop(self._energy_register_wh, reason, stop_ts, transaction_id)
            response = await self._send_tx(request)
            handled = True
            if response is None:
                logger.info("Transaction %s stopped offline; StopTransaction held", transaction_id)
            else:
                logger.info("Transaction %s stopped, response: %s", transaction_id, response)
        except Exception:
            logger.error("Failed to stop transaction", exc_info=True)
        finally:
            self._transaction_id = None
            self._transaction_id_tag = None
            self._pending_id_tag = None
            self._stop_txn_data = []
            self._tx_profile = None
            self._resumed = False
            if handled or (request is not None and any(
                e.get("_request") is request for e in self._offline_queue
            )):
                self._save_active_transaction()  # StopTransaction sent or held: closed
            else:
                # Cut off before StopTransaction was queued (e.g. shutdown timed
                # out on the Finishing status): leave the transaction saved so
                # the next start closes it with reason PowerLoss.
                logger.warning("Transaction left open on disk; will be closed on next start")
            self._shared_state.transaction_id = None
            self._zero_power_state()
            # Where the caller wants the connector to end up
            self.state = final_state
            self._shared_state.state = self.state
        if announce:
            # Without this the server's last word from us is "Finishing",
            # and it can't tell the car is still plugged in and idle.
            try:
                await self.send_status()
            except Exception:
                logger.warning("Status after stop not sent", exc_info=True)

    @on(Action.RemoteStartTransaction)
    async def on_remote_start_transaction(self, id_tag: str, charging_profile: dict = None, **kwargs):
        if self._resumed and self._transaction_id is not None:
            # The server didn't take up the session continued after a restart
            # and wants a new one: close the old one, then start.
            logger.warning("The server started a new session instead of continuing transaction %s: "
                           "stopping that one first", self._transaction_id)
            asyncio.create_task(self._replace_resumed_transaction(id_tag, charging_profile))
            return call_result.RemoteStartTransactionPayload(status=RemoteStartStopStatus.accepted)
        # Only when the car is plugged in (Preparing / suspended)
        if self.state not in (ChargePointStatus.preparing, ChargePointStatus.suspended_ev, ChargePointStatus.suspended_evse):
            logger.warning("RemoteStart rejected: state is %s (not plugged in)", self.state)
            return call_result.RemoteStartTransactionPayload(
                status=RemoteStartStopStatus.rejected
            )

        if charging_profile:
            self._profile_scheduler.set_profile(charging_profile)
        self._tx_profile = normalise_profile(charging_profile) if charging_profile else None

        self.set_plugged_in(True, "supplier")
        self._pending_id_tag = id_tag
        asyncio.create_task(self._do_start_transaction())
        return call_result.RemoteStartTransactionPayload(
            status=RemoteStartStopStatus.accepted
        )

    async def _replace_resumed_transaction(self, id_tag: str, charging_profile: Optional[dict]) -> None:
        await self._do_stop_transaction(reason=Reason.reboot)
        if charging_profile:
            self._profile_scheduler.set_profile(charging_profile)
        self._tx_profile = normalise_profile(charging_profile) if charging_profile else None
        self._pending_id_tag = id_tag
        await self._do_start_transaction()

    @on(Action.RemoteStopTransaction)
    async def on_remote_stop_transaction(self, transaction_id: int, **kwargs):
        if self._transaction_id is None:
            logger.warning("RemoteStop rejected: no active transaction")
            return call_result.RemoteStopTransactionPayload(
                status=RemoteStartStopStatus.rejected
            )
        if transaction_id != self._transaction_id:
            # Workaround: some CSMS backends (seen with Octopus) send a
            # RemoteStop with a transactionId that doesn't match the one they
            # issued in the StartTransaction response (e.g. 1 vs 1790607644).
            # We only have one connector and one active transaction, so the
            # server can only mean that one — accept and stop it, otherwise
            # the car never stops charging.
            logger.warning(
                "RemoteStop transaction_id mismatch (%s != current %s) — "
                "accepting anyway, single active transaction",
                transaction_id, self._transaction_id,
            )
        asyncio.create_task(self._do_stop_transaction(announce=True))
        return call_result.RemoteStopTransactionPayload(
            status=RemoteStartStopStatus.accepted
        )

    @on(Action.GetConfiguration)
    async def on_get_configuration(self, key: list[str] = None, **kwargs):
        """Return configuration keys. Returns all keys if none specified."""
        configuration_key = []
        unknown_key = []

        keys_to_return = key if key else list(self._config_store.keys())

        for k in keys_to_return:
            if k in self._config_store:
                value, readonly = self._config_store[k]
                configuration_key.append({
                    "key": k,
                    "readonly": readonly,
                    "value": value,
                })
            else:
                unknown_key.append(k)

        return call_result.GetConfigurationPayload(
            configuration_key=configuration_key,
            unknown_key=unknown_key,
        )

    @on(Action.ChangeConfiguration)
    async def on_change_configuration(self, key: str, value: str, **kwargs):
        """Handle configuration changes from the server."""
        logger.info("Server set config: %s = %s", key, value)

        if key == "ClockAlignedDataInterval":
            try:
                aligned_s = int(value)
                if aligned_s < 0:
                    raise ValueError
            except ValueError:
                logger.warning("Invalid ClockAlignedDataInterval: %s, rejecting", value)
                return call_result.ChangeConfigurationPayload(
                    status=ConfigurationStatus.rejected
                )

        if key == "HeartbeatInterval":
            try:
                heartbeat_s = int(value)
                if heartbeat_s < 1:
                    raise ValueError
            except ValueError:
                logger.warning("Invalid HeartbeatInterval: %s, rejecting", value)
                return call_result.ChangeConfigurationPayload(
                    status=ConfigurationStatus.rejected
                )

        if key in self._config_store:
            _, readonly = self._config_store[key]
            if readonly:
                logger.info("ChangeConfiguration: key %s is read-only", key)
                return call_result.ChangeConfigurationPayload(
                    status=ConfigurationStatus.rejected
                )
            self._config_store[key] = (value, False)
        else:
            # Keys we don't model (e.g. vendor keys minSoC, maxSoC,
            # AuthEnabledOffline) are accepted as before, and now stored so
            # GetConfiguration reports what was set.
            self._config_store[key] = (value, False)

        self._server_config[key] = value
        self._shared_state.server_config = dict(self._server_config)

        if key == "HeartbeatInterval":
            self._set_heartbeat_interval(heartbeat_s)
        elif key == "ClockAlignedDataInterval":
            self._set_clock_aligned_interval(aligned_s)
        elif key == "MeterValuesSampledData":
            self._sampled_measurands = [m.strip() for m in value.split(",") if m.strip()]
            logger.info("Sampled measurands: %s", self._sampled_measurands or "(default)")
        elif key == "StopTxnSampledData":
            self._stop_txn_sampled = [m.strip() for m in value.split(",") if m.strip()]
            logger.info("StopTransaction sampled measurands: %s", self._stop_txn_sampled or "(none)")
        elif key == "StopTxnAlignedData":
            self._stop_txn_aligned = [m.strip() for m in value.split(",") if m.strip()]
            logger.info("StopTransaction aligned measurands: %s", self._stop_txn_aligned or "(none)")
        elif key == "MeterValuesAlignedData":
            self._aligned_measurands = [m.strip() for m in value.split(",") if m.strip()]
            logger.info("Clock-aligned measurands: %s", self._aligned_measurands or "(default)")
        elif key == "MeterValueSampleInterval":
            try:
                interval = int(value)
                if interval < 1:
                    raise ValueError("interval must be >= 1")
                self._meter_value_interval = interval
                self._shared_state.meter_interval = self._meter_value_interval
                logger.info("Meter value interval updated to %ds", self._meter_value_interval)
            except ValueError:
                logger.warning("Invalid MeterValueSampleInterval: %s, ignoring", value)
        elif key == "chargingALimitConn1":
            # The supplier's limit: can only lower the current below the HA max
            try:
                limit = float(value)
                if limit < 0:
                    raise ValueError
            except ValueError:
                logger.warning("Invalid chargingALimitConn1: %s, ignoring", value)
            else:
                self._server_limit_amps = limit
                self._apply_current()
                if limit > self._max_current_amps:
                    # Only a current limit: it doesn't start or stop anything
                    logger.info(
                        "Supplier limit %gA is above your max %dA: %s at %dA",
                        limit, self._max_current_amps,
                        "charging" if self._transaction_id is not None else "next charge will run",
                        self._charger_sim.current_amps,
                    )

        return call_result.ChangeConfigurationPayload(
            status=ConfigurationStatus.accepted
        )

    @on(Action.GetLocalListVersion)
    async def on_get_local_list_version(self, **kwargs):
        """Return the current local authorization list version."""
        return call_result.GetLocalListVersionPayload(
            list_version=self._local_list_version
        )

    @on(Action.SendLocalList)
    async def on_send_local_list(
        self,
        list_version: int,
        update_type: str,
        local_authorization_list: list[dict] = None,
        **kwargs,
    ):
        """Handle local authorization list updates."""
        logger.info(
            "SendLocalList: version=%d type=%s entries=%d",
            list_version, update_type,
            len(local_authorization_list) if local_authorization_list else 0,
        )

        if update_type == "Full":
            self._local_auth_list.clear()

        if local_authorization_list:
            for entry in local_authorization_list:
                id_tag = entry.get("id_tag", entry.get("idTag", ""))
                if id_tag:
                    self._local_auth_list[id_tag] = entry

        self._local_list_version = list_version
        return call_result.SendLocalListPayload(status=UpdateStatus.accepted)

    @on(Action.SetChargingProfile)
    async def on_set_charging_profile(self, connector_id: int, cs_charging_profiles: dict, **kwargs):
        logger.info("SetChargingProfile received for connector %s", connector_id)
        self._profile_scheduler.set_profile(cs_charging_profiles)
        purpose = (cs_charging_profiles or {}).get("charging_profile_purpose",
                                                    (cs_charging_profiles or {}).get("chargingProfilePurpose"))
        if str(getattr(purpose, "value", purpose)) == "TxProfile" and self._transaction_id is not None:
            self._tx_profile = normalise_profile(cs_charging_profiles)
        return call_result.SetChargingProfilePayload(
            status="Accepted"
        )

    @on(Action.ClearChargingProfile)
    async def on_clear_charging_profile(self, **kwargs):
        logger.info("ClearChargingProfile received: %s", kwargs)
        self._profile_scheduler.clear_profile(
            profile_id=kwargs.get("id"),
            connector_id=kwargs.get("connector_id"),
            purpose=kwargs.get("charging_profile_purpose"),
            stack_level=kwargs.get("stack_level"),
        )
        return call_result.ClearChargingProfilePayload(
            status="Accepted"
        )

    @on(Action.TriggerMessage)
    async def on_trigger_message(self, requested_message: str, connector_id: int = 0, **kwargs):
        """Handle TriggerMessage: server requests the CP to send a specific message."""
        supported = {
            "BootNotification", "Heartbeat", "MeterValues", "StatusNotification",
        }
        if requested_message not in supported:
            logger.warning("TriggerMessage for unsupported message: %s", requested_message)
            return call_result.TriggerMessagePayload(
                status=TriggerMessageStatus.not_implemented
            )

        logger.info("TriggerMessage accepted: %s", requested_message)
        asyncio.create_task(self._handle_triggered_message(requested_message, connector_id))
        return call_result.TriggerMessagePayload(
            status=TriggerMessageStatus.accepted
        )

    async def _handle_triggered_message(self, message: str, connector_id: int) -> None:
        """Execute the triggered message after returning the response."""
        try:
            if message == "StatusNotification":
                await self._send_status_for_connector(connector_id or self.connector_id)
            elif message == "MeterValues":
                await self.send_meter_values()
            elif message == "Heartbeat":
                await self.call(call.HeartbeatPayload())
            elif message == "BootNotification":
                if self._boot_request is None:
                    logger.warning("Triggered BootNotification before first boot; ignoring")
                    return
                # Same identity as at connect. Not a reconnect, so no boot
                # status sequence — just adopt the interval if accepted.
                response = await self.call(self._boot_request)
                if (
                    response.status == RegistrationStatus.accepted
                    and response.interval and response.interval > 0
                ):
                    self._set_heartbeat_interval(response.interval)
        except Exception:
            logger.warning("Failed to send triggered %s", message, exc_info=True)

    @on(Action.ChangeAvailability)
    async def on_change_availability(self, connector_id: int, type: str, **kwargs):
        """Handle ChangeAvailability: server requests connector operative/inoperative."""
        logger.info("ChangeAvailability: connector=%d type=%s", connector_id, type)

        if type == AvailabilityType.inoperative:
            if self._transaction_id is not None:
                logger.info("Transaction active, will change availability after completion")
                return call_result.ChangeAvailabilityPayload(
                    status=AvailabilityStatus.scheduled
                )
            self.state = ChargePointStatus.unavailable
            self._shared_state.state = self.state
            await self.send_status()
        else:
            if self.state == ChargePointStatus.unavailable:
                self.state = ChargePointStatus.available
                self._shared_state.state = self.state
                await self.send_status()

        return call_result.ChangeAvailabilityPayload(
            status=AvailabilityStatus.accepted
        )

    @on(Action.UnlockConnector)
    async def on_unlock_connector(self, connector_id: int, **kwargs):
        """Handle UnlockConnector: server requests to unlock a connector."""
        logger.info("UnlockConnector: connector=%d", connector_id)

        if connector_id != self.connector_id:
            return call_result.UnlockConnectorPayload(
                status=UnlockStatus.not_supported
            )

        if self._transaction_id is not None:
            # State changes to Available below, before the stop task runs,
            # so capture the energy delivered so far now.
            self._checkpoint_energy()
            asyncio.create_task(self._do_stop_transaction(
                final_state=ChargePointStatus.available,
                reason=Reason.unlock_command,
                announce=True,
            ))

        self.set_plugged_in(False, "supplier")
        self.state = ChargePointStatus.available
        self._shared_state.state = self.state

        return call_result.UnlockConnectorPayload(
            status=UnlockStatus.unlocked
        )

    @on(Action.Reset)
    async def on_reset(self, type: str, **kwargs):
        """Handle Reset: server requests a hard or soft reset."""
        logger.info("Reset requested: type=%s", type)

        if self._transaction_id is not None:
            await self._do_stop_transaction(
                final_state=ChargePointStatus.available,
                reason=Reason.hard_reset if type == ResetType.hard else Reason.soft_reset,
            )

        self._profile_scheduler.clear_profile()

        if type == ResetType.hard:
            asyncio.create_task(self._perform_hard_reset())
        else:
            self.state = ChargePointStatus.available
            self._shared_state.state = self.state
            self.set_plugged_in(False, "supplier")
            self._zero_power_state()
            await self.send_status()

        return call_result.ResetPayload(status=ResetStatus.accepted)

    async def _perform_hard_reset(self) -> None:
        """Simulate a hard reset by triggering reconnection."""
        await asyncio.sleep(2)
        raise SystemExit("Hard reset requested by server")

    @on(Action.ClearCache)
    async def on_clear_cache(self, **kwargs):
        """Handle ClearCache: server requests clearing the authorization cache."""
        logger.info("ClearCache requested")
        return call_result.ClearCachePayload(
            status=ClearCacheStatus.accepted
        )

    @on(Action.DataTransfer)
    async def on_data_transfer(
        self, vendor_id: str, message_id: str = "", data: str = "", **kwargs
    ):
        """Handle DataTransfer: vendor-specific messaging."""
        logger.info(
            "DataTransfer: vendor=%s message_id=%s data_len=%d",
            vendor_id, message_id, len(data) if data else 0,
        )
        return call_result.DataTransferPayload(
            status=DataTransferStatus.unknown_vendor_id,
            data="",
        )
