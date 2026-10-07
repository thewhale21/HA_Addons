"""Data kept for the web GUI only (not pushed to Home Assistant).

- MessageLog: the last few hundred OCPP frames, both ways, in full.
- SessionLog: the current charging session and the last few finished ones
  (saved to disk, so the history survives a restart).
- PowerHistory: power / current / SoC samples for the chart (memory only).
- Health: uptime, connection history and version.

Display only: recording never raises into the charger.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

from src.shared_state import display_status
from src.traffic import summarise_command

logger = logging.getLogger(__name__)

MESSAGE_LOG_SIZE = 300
SESSION_HISTORY_SIZE = 20
HISTORY_SAMPLE_S = 10
RECENT_MINUTES = 60  # kept in memory; older chart data comes from HA (src/ha_history.py)
# Files from before 2.3.0, when the add-on kept its own chart history
OLD_HISTORY_FILES = ("history.json", "history_long.json", "daily_energy.json")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value) -> Optional[datetime.datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)


# --- OCPP message log --------------------------------------------------------


class MessageLog:
    """Every OCPP frame, newest last, numbered so the GUI can ask for new ones.

    With a data_dir the log is kept in messages.json across restarts: saved
    every SAVE_INTERVAL_S seconds when something changed (not on every frame,
    to spare the SD card) and at shutdown. A "restart" marker is added when
    the add-on starts. A power cut loses at most the last minute.
    """

    SAVE_INTERVAL_S = 60

    def __init__(self, size: int = MESSAGE_LOG_SIZE, data_dir: Optional[str] = None) -> None:
        self._entries: deque[dict] = deque(maxlen=size)
        self._seq = 0
        self._actions: dict[str, str] = {}  # uid -> action of the call it answers
        self._path = os.path.join(data_dir, "messages.json") if data_dir else None
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self._path:
            return
        for path in (self._path, self._path + ".bak"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                entries = [e for e in data.get("messages") or [] if isinstance(e, dict) and "seq" in e]
                self._entries.extend(entries[-self._entries.maxlen:])
                self._seq = max([int(data.get("last_seq") or 0)] + [int(e["seq"]) for e in entries])
                break
            except FileNotFoundError:
                continue
            except Exception:
                logger.warning("Message log %s is unreadable", path)
        if self._entries:
            self._seq += 1
            self._entries.append({
                "seq": self._seq, "timestamp": _now_iso(), "direction": None,
                "type": "restart", "message_id": "", "action": None, "summary": "", "payload": None,
            })
            self._dirty = True

    def save(self) -> None:
        """Write the log if it changed since the last save."""
        if not self._path or not self._dirty:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"last_seq": self._seq, "messages": list(self._entries)}, f, default=str)
                f.flush()
                os.fsync(f.fileno())
            if os.path.exists(self._path):
                os.replace(self._path, self._path + ".bak")
            os.replace(tmp, self._path)
            self._dirty = False
        except Exception:
            logger.warning("Could not save the message log", exc_info=True)

    async def save_loop(self) -> None:
        import asyncio
        while True:
            await asyncio.sleep(self.SAVE_INTERVAL_S)
            self.save()

    def clear(self) -> None:
        """Forget every message (Diagnostics › Debug). Numbering carries on."""
        self._entries.clear()
        self._actions.clear()
        self._dirty = True
        self.save()

    @property
    def last_seq(self) -> int:
        return self._seq

    def record(self, raw, incoming: bool) -> None:
        try:
            msg = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            kind, uid = msg[0], str(msg[1])
            if kind == 2:
                action = msg[2]
                payload = msg[3] if len(msg) > 3 else {}
                if len(self._actions) >= 500:
                    self._actions.pop(next(iter(self._actions)))
                self._actions[uid] = action
                entry_type = "call"
            elif kind == 3:
                action = self._actions.pop(uid, None)
                payload = msg[2] if len(msg) > 2 else {}
                entry_type = "result"
            elif kind == 4:
                action = self._actions.pop(uid, None)
                payload = {
                    "errorCode": msg[2] if len(msg) > 2 else "",
                    "errorDescription": msg[3] if len(msg) > 3 else "",
                    "errorDetails": msg[4] if len(msg) > 4 else {},
                }
                entry_type = "error"
            else:
                return
            self._seq += 1
            self._entries.append({
                "seq": self._seq,
                "timestamp": _now_iso(),
                "direction": "received" if incoming else "sent",
                "type": entry_type,
                "message_id": uid,
                "action": action,
                "summary": summarise_command(action, payload) if entry_type == "call" else "",
                "payload": payload,
            })
            self._dirty = True
        except Exception:
            logger.debug("Could not log OCPP frame", exc_info=True)

    def since(self, after: int = 0, limit: int = MESSAGE_LOG_SIZE) -> list[dict]:
        newer = [e for e in self._entries if e["seq"] > after]
        return newer[-limit:]


# --- Charging sessions -------------------------------------------------------


PLUGGED_KEEP_DAYS = 8  # plugged-in stretches kept for the Automations tab's past days


class SessionLog:
    """The current session and recent finished ones, saved in sessions.json.

    The current session is saved too, so one cut short by a power cut is
    still closed (reason PowerLoss) after the restart.

    Plug-ins that never got a session are kept too (type "no_session"): from
    Plugged In turning on until it's turned off again with no session having
    started, with who plugged in / unplugged. The last `size` of each kind are
    kept.

    Every plugged-in stretch of the last PLUGGED_KEEP_DAYS days is kept too
    ("plugged": start, end, who plugged in and unplugged), for the
    Automations tab's past days: what actually happened, not the schedule as
    it is now.
    """

    def __init__(self, data_dir: Optional[str], size: int = SESSION_HISTORY_SIZE) -> None:
        self._path = os.path.join(data_dir, "sessions.json") if data_dir else None
        self._size = size
        self.current: Optional[dict] = None
        self.history: list[dict] = []  # newest first, sessions and no-session plug-ins
        self.plug: Optional[dict] = None  # plugged in, waiting for a session: {plugged_at, plugged_by}
        self.plugged_spans: list[dict] = []  # [{start, end, by, unplugged_by}], newest first
        self.plugged_open: Optional[dict] = None  # plugged in now: {start, by}
        self.plugged_since: Optional[str] = None  # when recording started
        self._load()
        if self.plugged_since is None:
            self.plugged_since = _now_iso()

    def _load(self) -> None:
        if not self._path:
            return
        for path in (self._path, self._path + ".bak"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                current = data.get("current")
                self.current = current if isinstance(current, dict) else None
                plug = data.get("plug")
                self.plug = plug if isinstance(plug, dict) else None
                self.history = [s for s in data.get("history") or [] if isinstance(s, dict)]
                self.plugged_spans = [s for s in data.get("plugged") or [] if isinstance(s, dict)]
                opened = data.get("plugged_open")
                self.plugged_open = opened if isinstance(opened, dict) else None
                self.plugged_since = data.get("plugged_since") if isinstance(data.get("plugged_since"), str) else None
                self._trim()
                return
            except FileNotFoundError:
                continue
            except Exception:
                logger.warning("Session history %s is unreadable", path)

    def _save(self) -> None:
        if not self._path:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"current": self.current, "plug": self.plug, "history": self.history,
                           "plugged": self.plugged_spans, "plugged_open": self.plugged_open,
                           "plugged_since": self.plugged_since}, f)
                f.flush()
                os.fsync(f.fileno())
            if os.path.exists(self._path):
                os.replace(self._path, self._path + ".bak")
            os.replace(tmp, self._path)
        except Exception:
            logger.warning("Could not save session history", exc_info=True)

    def _trim(self) -> None:
        """Keep the newest `size` sessions and the newest `size` no-session plug-ins."""
        counts = {"session": 0, "no_session": 0}
        kept = []
        for entry in self.history:
            kind = "no_session" if entry.get("type") == "no_session" else "session"
            counts[kind] += 1
            if counts[kind] <= self._size:
                kept.append(entry)
        self.history = kept
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=PLUGGED_KEEP_DAYS)
        self.plugged_spans = [s for s in self.plugged_spans if (_parse_iso(s.get("end")) or cutoff) >= cutoff]

    def plugged(self, plugged_in: bool, source: Optional[str] = None, timestamp: Optional[str] = None) -> None:
        """Plugged In changed. Unplugged with no session since plugging in: a
        no-session entry with who unplugged (and why, for a re-plug)."""
        ts = timestamp or _now_iso()
        if plugged_in:
            if self.plugged_open is None:
                self.plugged_open = {"start": ts, "by": source}
            if self.plug is None and self.current is None:
                self.plug = {"plugged_at": ts, "plugged_by": source}
            self._save()
            return
        if self.plugged_open is not None:
            opened, self.plugged_open = self.plugged_open, None
            self.plugged_spans.insert(0, {"start": opened.get("start"), "end": ts, "by": opened.get("by"),
                                          "unplugged_by": source})
            self._trim()
            self._save()
        if self.plug is None:
            return
        plug, self.plug = self.plug, None
        if self.current is None:
            start, stop = _parse_iso(plug.get("plugged_at")), _parse_iso(ts)
            self.history.insert(0, {
                "type": "no_session",
                "start": plug.get("plugged_at"),
                "stop": ts,
                "duration_s": int((stop - start).total_seconds()) if start and stop else None,
                "plugged_by": plug.get("plugged_by"),
                "unplugged_by": source,
                "reason": "replugged" if source == "auto re-plug" else "unplugged",
            })
            self._trim()
        self._save()

    def start(self, transaction_id, id_tag, meter_start_wh: int, timestamp: Optional[str] = None) -> None:
        self.plug = None  # a session started: this plug-in worked
        self.current = {
            "transaction_id": transaction_id,
            "id_tag": id_tag,
            "start": timestamp or _now_iso(),
            "meter_start_wh": int(meter_start_wh),
            "peak_power_kw": 0.0,
        }
        self._save()

    def remap_transaction_id(self, old, new) -> None:
        """A held StartTransaction was accepted: use the server's id."""
        changed = False
        for session in ([self.current] if self.current else []) + self.history:
            if session.get("transaction_id") == old:
                session["transaction_id"] = new
                changed = True
        if changed:
            self._save()

    def sample(self, power_kw: float) -> None:
        """Track the session's peak power (saved at the stop, not every sample)."""
        if self.current is not None and power_kw > self.current.get("peak_power_kw", 0.0):
            self.current["peak_power_kw"] = round(power_kw, 2)

    def stop(self, meter_stop_wh: int, reason, timestamp: Optional[str] = None, transaction_id=None) -> None:
        if self.current is None:
            return
        session = dict(self.current)
        session["stop"] = timestamp or _now_iso()
        session["meter_stop_wh"] = int(meter_stop_wh)
        session["energy_kwh"] = round(max(0, int(meter_stop_wh) - session["meter_start_wh"]) / 1000.0, 3)
        session["reason"] = str(getattr(reason, "value", reason)) if reason else None
        if transaction_id is not None:
            session["transaction_id"] = transaction_id
        start, stop = _parse_iso(session["start"]), _parse_iso(session["stop"])
        session["duration_s"] = int((stop - start).total_seconds()) if start and stop else None
        self.history.insert(0, session)
        self.current = None
        self._trim()
        self._save()

    def clear_history(self) -> None:
        """Forget the finished sessions and no-session plug-ins (Diagnostics ›
        Debug). The current session, if any, carries on."""
        self.history = []
        self._save()

    def mark_supplier(self, periods: list, provider: Optional[str] = None) -> bool:
        """Note how much of each recent session was inside the supplier's
        dispatch slots (supplier_s, seconds). Kept at its highest, as finished
        slots drop out of the integration's list after a while."""
        spans = []
        for p in periods or []:
            a, b = _parse_iso(p.get("start")), _parse_iso(p.get("end"))
            if a and b and b > a:
                spans.append((a, b))
        if not spans:
            return False
        now = datetime.datetime.now(datetime.timezone.utc)
        changed = False
        for s in ([self.current] if self.current else []) + self.history:
            if s.get("type") == "no_session":
                continue
            a, b = _parse_iso(s.get("start")), _parse_iso(s.get("stop")) or now
            if not a or b <= a or now - b > datetime.timedelta(days=3):
                continue
            covered = sum(max(0.0, (min(b, e) - max(a, st)).total_seconds()) for st, e in spans)
            covered = int(min(covered, (b - a).total_seconds()))
            if covered > (s.get("supplier_s") or 0):
                s["supplier_s"] = covered
                s["supplier"] = provider
                changed = True
        if changed:
            self._save()
        return changed

    def snapshot(self, energy_register_wh: Optional[int] = None) -> dict:
        current = None
        if self.current is not None:
            current = dict(self.current)
            if energy_register_wh is not None:
                current["energy_kwh"] = round(
                    max(0, energy_register_wh - current["meter_start_wh"]) / 1000.0, 3,
                )
            start = _parse_iso(current["start"])
            if start:
                current["duration_s"] = int(
                    (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()
                )
        waiting = None
        if self.plug is not None:
            waiting = dict(self.plug)
            start = _parse_iso(waiting.get("plugged_at"))
            if start:
                waiting["duration_s"] = int(
                    (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()
                )
        plugged = list(self.plugged_spans)
        if self.plugged_open is not None:
            plugged.insert(0, {**self.plugged_open, "end": None})
        return {"current": current, "waiting": waiting, "history": list(self.history),
                "plugged": plugged, "plugged_since": self.plugged_since}


# --- Power history for the chart ---------------------------------------------


class PowerHistory:
    """The last RECENT_MINUTES of chart samples, every HISTORY_SAMPLE_S seconds.

    Only in memory: anything older is read back from Home Assistant's
    history, which records the add-on's sensors anyway.
    """

    def __init__(self, size: int = RECENT_MINUTES * 60 // HISTORY_SAMPLE_S,
                 clock: Callable[[], float] = time.time) -> None:
        self._samples: deque[dict] = deque(maxlen=size)
        self._clock = clock

    def sample(self, state) -> dict:
        entry = {
            "t": round(self._clock(), 1),
            "power_kw": round(float(state.power_kw or 0.0), 3),
            "current_a": round(float(state.current_a or 0.0), 2),
            "soc": state.soc_percent,
            "max_amps": state.current_amps_setting,
            "effective_amps": state.current_amps_effective,
            "provider_limit_amps": state.current_amps_provider_limit,
            "state": display_status(state),
        }
        self._samples.append(entry)
        return entry

    def since(self, after: float = 0.0) -> list[dict]:
        return [s for s in self._samples if s["t"] > after]


def daily_from_sessions(days: int, sessions: Optional[list], today: datetime.date,
                        metered: Optional[dict] = None, charging: Optional[dict] = None) -> list[dict]:
    """kWh and charging time per day for the last `days` days.

    metered: date -> kWh from HA's statistics. Each kept session's energy
    counts on the day it started, and the larger of the two figures is used
    (HA's figure lags by up to an hour; sessions cover HA being unreachable).
    charging: date -> seconds Charging from HA's history. Days without it
    use the sessions' lengths (charging_estimated: true), which include any
    paused time."""
    from_sessions: dict[str, float] = {}
    session_time: dict[str, float] = {}
    for s in sessions or []:
        if s.get("type") == "no_session" or s.get("energy_kwh") is None:
            continue
        start = _parse_iso(s.get("start"))
        if start:
            day = start.astimezone().date().isoformat()
            from_sessions[day] = from_sessions.get(day, 0.0) + float(s["energy_kwh"])
            session_time[day] = session_time.get(day, 0.0) + float(s.get("duration_s") or 0)
    metered, charging = metered or {}, charging or {}
    out = []
    for i in range(days - 1, -1, -1):
        day = (today - datetime.timedelta(days=i)).isoformat()
        known = day in charging
        out.append({
            "date": day,
            "kwh": round(max(metered.get(day, 0.0), from_sessions.get(day, 0.0)), 3),
            "charging_s": int(charging[day] if known else session_time.get(day, 0.0)),
            "charging_estimated": not known and day in session_time,
        })
    return out


def remove_old_history_files(data_dir: Optional[str]) -> None:
    """Delete the chart files older versions kept (now read from HA)."""
    if not data_dir:
        return
    for name in OLD_HISTORY_FILES:
        for path in (os.path.join(data_dir, name), os.path.join(data_dir, name + ".bak")):
            try:
                os.remove(path)
                logger.info("Removed %s: charts now come from Home Assistant's history", os.path.basename(path))
            except FileNotFoundError:
                pass
            except OSError as err:
                logger.debug("Couldn't remove %s: %s", path, err)


@dataclass
class GuiSources:
    """Everything the GUI endpoints read, handed to the API in one go."""

    message_log: MessageLog
    history: "object"  # ChartHistory (src/ha_history.py): samples / long_samples / daily
    sessions: Callable[[], dict]
    provider: Callable[[], dict]
    health: Callable[[], dict]


async def sample_loop(history: PowerHistory, shared_state, refresh: Optional[Callable[[], None]] = None,
                      on_sample: Optional[Callable[[dict], None]] = None,
                      interval: float = HISTORY_SAMPLE_S) -> None:
    """Record a chart sample every `interval` seconds, for the life of the add-on."""
    import asyncio
    while True:
        try:
            if refresh is not None:
                refresh()
            entry = history.sample(shared_state)
            if on_sample is not None:
                on_sample(entry)
        except Exception:
            logger.debug("History sample failed", exc_info=True)
        await asyncio.sleep(interval)


# --- Health ------------------------------------------------------------------


class Health:
    """Add-on uptime and connection history."""

    def __init__(self, version: Optional[str] = None, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self.version = version or os.environ.get("ADDON_VERSION") or "dev"
        self.started = self._clock()
        self.connected_since: Optional[float] = None
        self.connects = 0
        self.disconnects = 0
        self.last_disconnect: Optional[dict] = None

    def connected(self) -> None:
        self.connects += 1
        self.connected_since = self._clock()

    def disconnected(self, reason: str) -> None:
        if self.connected_since is not None:
            self.disconnects += 1
        self.connected_since = None
        self.last_disconnect = {
            "timestamp": _now_iso(),
            "reason": reason or "unknown",
        }

    def snapshot(self) -> dict:
        now = self._clock()
        return {
            "version": self.version,
            "started": datetime.datetime.fromtimestamp(self.started, datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "uptime_s": int(now - self.started),
            "connected_for_s": None if self.connected_since is None else int(now - self.connected_since),
            "connects": self.connects,
            "reconnects": max(0, self.connects - 1),
            "disconnects": self.disconnects,
            "last_disconnect": self.last_disconnect,
        }
