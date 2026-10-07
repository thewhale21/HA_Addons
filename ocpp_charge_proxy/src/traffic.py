"""Records the last OCPP commands both ways, for the Overview's last command.

Fed every frame the charger sends or receives (OCPP-J: [2, id, action,
payload] call, [3, id, payload] result, [4, id, code, description, details]
error). Keeps, in SharedState:

- last_command_received / last_command_sent: the latest command each way
  (sent excludes Heartbeat and MeterValues) with a readable summary, the
  reply's status, the round trip time, and the last few commands as "recent".
- last_heartbeat: the last answered Heartbeat, its round trip and the
  server's clock.

Display only: never raises.
"""

from __future__ import annotations

import datetime
import json
import logging
import time
from collections import deque
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Routine traffic left out of the last command sent
UNTRACKED_SENT_ACTIONS = {"Heartbeat", "MeterValues"}
# Bulky list fields summarised (as a count) in the summaries
SUMMARISED_FIELDS = {"transactionData", "meterValue", "configurationKey", "localAuthorizationList"}
RECENT_COMMANDS = 10
_MAX_PENDING = 200


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def summarise_payload(payload) -> dict:
    if not isinstance(payload, dict):
        return {}
    return {
        k: (f"{len(v)} item(s)" if k in SUMMARISED_FIELDS and isinstance(v, list) else v)
        for k, v in payload.items()
    }


def response_status(payload) -> Optional[str]:
    """'status' (or idTagInfo.status) from a response payload, if any."""
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if status is None and isinstance(payload.get("idTagInfo"), dict):
        status = payload["idTagInfo"].get("status")
    return None if status is None else str(status)


def _profile_summary(profile) -> str:
    if not isinstance(profile, dict):
        return ""
    schedule = profile.get("chargingSchedule") or {}
    periods = schedule.get("chargingSchedulePeriod") or []
    purpose = profile.get("chargingProfilePurpose", "profile")
    if periods and isinstance(periods[0], dict) and "limit" in periods[0]:
        unit = schedule.get("chargingRateUnit", "")
        more = f" (+{len(periods) - 1} more)" if len(periods) > 1 else ""
        return f"{purpose} {periods[0]['limit']:g} {unit}{more}".strip()
    return str(purpose)


def summarise_command(action: str, p) -> str:
    """One readable line for a command, e.g. "chargingALimitConn1 = 32"."""
    if not isinstance(p, dict):
        return ""
    try:
        if action == "ChangeConfiguration":
            return f"{p.get('key')} = {p.get('value')}"
        if action == "GetConfiguration":
            keys = p.get("key") or []
            return ", ".join(keys) if keys else "all keys"
        if action == "RemoteStartTransaction":
            text = f"idTag {p.get('idTag')}"
            if p.get("chargingProfile"):
                text += f", {_profile_summary(p['chargingProfile'])}"
            return text
        if action in ("RemoteStopTransaction",):
            return f"transaction {p.get('transactionId')}"
        if action == "SetChargingProfile":
            return _profile_summary(p.get("csChargingProfiles"))
        if action == "ClearChargingProfile":
            return ", ".join(f"{k} {v}" for k, v in p.items()) or "all profiles"
        if action == "TriggerMessage":
            return str(p.get("requestedMessage"))
        if action in ("Reset", "ChangeAvailability"):
            return str(p.get("type"))
        if action == "UnlockConnector":
            return f"connector {p.get('connectorId')}"
        if action == "SendLocalList":
            tags = p.get("localAuthorizationList") or []
            return f"{p.get('updateType')} v{p.get('listVersion')}, {len(tags)} tag(s)"
        if action == "DataTransfer":
            return f"{p.get('vendorId')} {p.get('messageId', '')}".strip()
        if action == "StatusNotification":
            return f"connector {p.get('connectorId')}: {p.get('status')}"
        if action == "StartTransaction":
            return f"idTag {p.get('idTag')}, meterStart {p.get('meterStart')} Wh"
        if action == "StopTransaction":
            text = f"transaction {p.get('transactionId')}, meterStop {p.get('meterStop')} Wh"
            return text + (f", {p['reason']}" if p.get("reason") else "")
        if action == "BootNotification":
            return " ".join(str(x) for x in (
                p.get("chargePointVendor"), p.get("chargePointModel"),
                f"fw {p['firmwareVersion']}" if p.get("firmwareVersion") else None,
            ) if x)
        if action == "Authorize":
            return f"idTag {p.get('idTag')}"
    except Exception:
        pass
    return ""


def _parse_time(value) -> Optional[datetime.datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)


class TrafficRecorder:
    def __init__(
        self,
        shared_state,
        heartbeat_interval: Callable[[], int],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._shared = shared_state
        self._heartbeat_interval = heartbeat_interval
        self._clock = clock
        # uid -> (direction, full entry, compact recent entry, start time)
        self._pending: dict[str, tuple[str, dict, dict, float]] = {}
        self._heartbeats: dict[str, float] = {}  # uid -> send time
        self._recent = {"received": deque(maxlen=RECENT_COMMANDS), "sent": deque(maxlen=RECENT_COMMANDS)}
        self._latest: dict[str, Optional[dict]] = {"received": None, "sent": None}

    def record(self, raw, incoming: bool) -> None:
        try:
            msg = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            kind, uid = msg[0], msg[1]
            if kind == 2:
                self._call(uid, msg[2], msg[3] if len(msg) > 3 else {}, incoming)
            elif kind in (3, 4):
                self._reply(uid, kind, msg, incoming)
        except Exception:
            logger.debug("Could not record OCPP traffic", exc_info=True)

    # --- calls ---------------------------------------------------------------

    def _call(self, uid, action, payload, incoming: bool) -> None:
        if not incoming and action == "Heartbeat":
            self._remember(self._heartbeats, uid, self._clock())
            return
        if not incoming and action in UNTRACKED_SENT_ACTIONS:
            return
        direction = "received" if incoming else "sent"
        summary = summarise_command(action, payload)
        entry = {
            "action": action,
            "timestamp": _now_iso(),
            "message_id": uid,
            "summary": summary,
            "payload": summarise_payload(payload),
            "status": None,
            "response": None,
            "round_trip_ms": None,
        }
        compact = {"timestamp": entry["timestamp"], "action": action, "summary": summary, "status": None}
        self._recent[direction].appendleft(compact)  # newest first
        self._latest[direction] = entry
        self._remember(self._pending, uid, (direction, entry, compact, self._clock()))
        self._publish(direction)

    # --- replies -------------------------------------------------------------

    def _reply(self, uid, kind, msg, incoming: bool) -> None:
        if incoming and uid in self._heartbeats:
            self._heartbeat_reply(uid, kind, msg)
            return
        pending = self._pending.pop(uid, None)
        if pending is None:
            return
        direction, entry, compact, started = pending
        # Our replies answer what we received; the server's answer what we sent
        if (direction == "received") == incoming:
            return
        entry["round_trip_ms"] = round((self._clock() - started) * 1000)
        if kind == 3:
            payload = msg[2] if len(msg) > 2 else {}
            entry["status"] = response_status(payload) or "OK"  # reply without a status
            entry["response"] = summarise_payload(payload)
        else:
            entry["status"] = f"Error: {msg[2]}"
            entry["response"] = {"errorCode": msg[2], "errorDescription": msg[3] if len(msg) > 3 else ""}
        compact["status"] = entry["status"]
        self._publish(direction)

    def _heartbeat_reply(self, uid, kind, msg) -> None:
        started = self._heartbeats.pop(uid)
        if kind != 3:
            return
        payload = msg[2] if len(msg) > 2 and isinstance(msg[2], dict) else {}
        now = datetime.datetime.now(datetime.timezone.utc)
        server_time = payload.get("currentTime")
        server = _parse_time(server_time)
        self._shared.last_heartbeat = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "round_trip_ms": round((self._clock() - started) * 1000),
            "interval_s": self._heartbeat_interval(),
            "server_time": server_time,
            # + = the server's clock is ahead of ours
            "clock_offset_s": round((server - now).total_seconds(), 1) if server else None,
        }

    # --- helpers -------------------------------------------------------------

    @staticmethod
    def _remember(store: dict, uid, value) -> None:
        if len(store) >= _MAX_PENDING:  # replies that never came
            store.pop(next(iter(store)))
        store[uid] = value

    def _publish(self, direction: str) -> None:
        entry = self._latest[direction]
        record = None if entry is None else {
            **entry, "recent": [dict(c) for c in self._recent[direction]],
        }
        if direction == "received":
            self._shared.last_command_received = record
        else:
            self._shared.last_command_sent = record
