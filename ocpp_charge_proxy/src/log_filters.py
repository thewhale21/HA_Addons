"""Logging filters for the ocpp library's message log."""

from __future__ import annotations

import json
import logging
import re

# OCPP actions whose send/receive lines are routine noise at INFO (shown with
# the Debug log level, Diagnostics › Debug). MeterValues only counts when it's a periodic reading;
# see _routine_meter_values.
DEBUG_ONLY_ACTIONS = frozenset({"Heartbeat", "MeterValues"})


def _routine_meter_values(payload) -> bool:
    """A periodic reading (every MeterValueSampleInterval), in a session or
    not, or any reading outside a session (no transactionId: e.g. the
    clock-aligned 0 W readings every 15 minutes while nothing charges).

    Clock-aligned readings during a session (Sample.Clock, every
    ClockAlignedDataInterval) stay at INFO.
    """
    if not isinstance(payload, dict):
        return False
    if payload.get("transactionId") is None:
        return True
    contexts = {
        sv.get("context", "Sample.Periodic")  # OCPP default context
        for mv in payload.get("meterValue") or []
        for sv in (mv.get("sampledValue") or [])
    }
    return contexts == {"Sample.Periodic"}


# The connection password your supplier may set (ChangeConfiguration AuthorizationKey):
# never in the log, the message log or the traffic recorder
_SECRET_KEYS = ("AuthorizationKey",)
_Q = r"[\"']"  # (JSON, or Python's repr)
_VAL = r"(?:\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"
_KEY = _Q + "(?:" + "|".join(_SECRET_KEYS) + ")" + _Q
_SECRET_RE = re.compile(
    r"(" + _Q + r"key" + _Q + r"\s*:\s*" + _KEY + r"\s*,\s*" + _Q + r"value" + _Q + r"\s*:\s*)" + _VAL
    + r"|(" + _Q + r"value" + _Q + r"\s*:\s*)" + _VAL + r"(\s*,\s*" + _Q + r"key" + _Q + r"\s*:\s*" + _KEY + ")"
)


def redact_secrets(raw):
    """A frame (or log line) with any AuthorizationKey value replaced by ***. If it
    can't be picked out, the whole thing is hidden rather than risk showing it."""
    if not isinstance(raw, str) or not any(k in raw for k in _SECRET_KEYS):
        return raw
    out = _SECRET_RE.sub(lambda m: (m.group(1) + '"***"') if m.group(1) else (m.group(2) + '"***"' + m.group(3)), raw)
    if out == raw and "ChangeConfiguration" in raw:
        return "(a message with the connection password in it: hidden)"
    return out


class RedactSecrets(logging.Filter):
    """The ocpp library logs every frame: hide the connection password in them."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            text = record.getMessage()
        except Exception:
            return True
        clean = redact_secrets(text)
        if clean != text:
            record.msg, record.args = clean, ()
        return True


class DemoteRoutineMessages(logging.Filter):
    """Show the ocpp library's Heartbeat and periodic MeterValues lines at DEBUG, not INFO.

    The library logs every frame at INFO ("send [...]" / "receive message
    [...]"). This catches those calls and the server's reply to them (matched
    by message id) and re-labels them DEBUG: they're dropped unless the log
    level is Debug. Every other message is untouched.
    """

    def __init__(self, actions=DEBUG_ONLY_ACTIONS) -> None:
        super().__init__()
        self._actions = frozenset(actions)
        self._pending: set[str] = set()  # ids of heartbeats awaiting a reply

    def _is_routine(self, record: logging.LogRecord) -> bool:
        raw = record.args[-1] if isinstance(record.args, tuple) and record.args else None
        if not isinstance(raw, (str, bytes)):
            return False
        try:
            frame = json.loads(raw)
            kind, uid = frame[0], frame[1]
        except (ValueError, TypeError, IndexError, KeyError):
            return False
        if (
            kind == 2 and len(frame) > 2 and frame[2] in self._actions
            and (frame[2] != "MeterValues" or _routine_meter_values(frame[3] if len(frame) > 3 else None))
        ):
            if len(self._pending) > 100:  # replies that never came
                self._pending.clear()
            self._pending.add(uid)
            return True
        if kind in (3, 4) and uid in self._pending:
            self._pending.discard(uid)
            return True
        return False

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno != logging.INFO or not self._is_routine(record):
            return True
        # The add-on's log_level is set on the root logger (basicConfig).
        # getEffectiveLevel, not isEnabledFor, which caches its answer.
        if logging.getLogger().getEffectiveLevel() > logging.DEBUG:
            return False
        record.levelno = logging.DEBUG
        record.levelname = logging.getLevelName(logging.DEBUG)
        return True


# A successful GET from the web page: "GET /api/state HTTP/1.1" 200 ...
_PAGE_GET = re.compile(r'"(?:GET|HEAD) \S+ HTTP/[\d.]+" (?:2\d\d|304) ')


class DemoteWebPageRequests(logging.Filter):
    """Show the web page's successful GETs (polling, refreshes) at DEBUG, not INFO.

    The page asks for its data every few seconds while open, which buried
    the OCPP lines in the add-on log. Commands (POST: plug, unplug, settings)
    and failed requests stay at INFO.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno != logging.INFO or not _PAGE_GET.search(record.getMessage()):
            return True
        if logging.getLogger().getEffectiveLevel() > logging.DEBUG:
            return False
        record.levelno = logging.DEBUG
        record.levelname = logging.getLevelName(logging.DEBUG)
        return True


def install() -> None:
    logging.getLogger("ocpp").addFilter(RedactSecrets())  # (first)
    logging.getLogger("ocpp").addFilter(DemoteRoutineMessages())
    logging.getLogger("aiohttp.access").addFilter(DemoteWebPageRequests())
