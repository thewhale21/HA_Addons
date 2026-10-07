"""Diagnostics › Debug on the web page: tools for testing and bug reports.

- Recent log lines (LogBuffer, on the root logger) and the log level (saved
  in src/app_settings.py)
- The add-on's settings for a diagnostics bundle, with the password and
  most of the charge point ID hidden
- Clearing the session history or the message log
- Sending a message, dropping the connection and restarting the add-on are
  callbacks from __main__ (they need the connection and the Supervisor)
"""
from __future__ import annotations

import dataclasses
import logging
from collections import deque
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

LOG_LINES = 500
LEVELS = ("debug", "info", "warning", "error")


class LogBuffer(logging.Handler):
    """The last `size` log lines, formatted as in the add-on's log."""

    def __init__(self, size: int = LOG_LINES) -> None:
        super().__init__()
        self.lines: deque[str] = deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:
            pass


def install_log_buffer(fmt: str, size: int = LOG_LINES) -> LogBuffer:
    buffer = LogBuffer(size)
    buffer.setFormatter(logging.Formatter(fmt))
    logging.getLogger().addHandler(buffer)
    return buffer


def redacted_config(config) -> dict:
    """The add-on's options, safe to share: no password, and only the last 4
    characters of the charge point ID (it's also the username)."""
    if config is None:
        return {}
    out = dataclasses.asdict(config) if dataclasses.is_dataclass(config) else dict(vars(config))
    if out.get("password"):
        out["password"] = "***"
    cid = str(out.get("chargepoint_id") or "")
    if cid:
        out["chargepoint_id"] = "…" + cid[-4:] if len(cid) > 4 else "***"
    return out


def mask_id(value) -> str:
    text = str(value or "")
    return ("…" + text[-4:] if len(text) > 4 else "***") if text else ""


class DebugTools:
    def __init__(self, *, send: Optional[Callable[[str, Optional[str]], Awaitable[dict]]] = None,
                 drop: Optional[Callable[[float], Awaitable[dict]]] = None,
                 restart: Optional[Callable[[], Awaitable[dict]]] = None,
                 config=None, log_buffer: Optional[LogBuffer] = None,
                 sessions=None, messages=None, settings=None) -> None:
        self._send, self._drop, self._restart = send, drop, restart
        self._config = config
        self._log_buffer = log_buffer
        self._sessions = sessions  # src.gui_data.SessionLog
        self._messages = messages  # src.gui_data.MessageLog
        self._settings = settings  # src.app_settings.AppSettings: the log level is saved there

    # --- logs ------------------------------------------------------------

    @staticmethod
    def log_level() -> str:
        return logging.getLevelName(logging.getLogger().getEffectiveLevel()).lower()

    def info(self, lines: int = 200) -> dict:
        logs = list(self._log_buffer.lines) if self._log_buffer is not None else []
        lines = max(0, min(int(lines), LOG_LINES))
        return {
            "log_level": self.log_level(),
            "config": redacted_config(self._config),
            "logs": logs[-lines:] if lines else [],
        }

    def set_log_level(self, level) -> dict:
        level = str(level or "").lower()
        if level not in LEVELS:
            raise ValueError("Log level must be one of: " + ", ".join(LEVELS))
        if self._settings is not None:
            self._settings.update({"log_level": level})  # saved, and applied by its on_change
        else:
            logging.getLogger().setLevel(getattr(logging, level.upper()))
        logger.warning("Log level set to %s from the web page", level)
        return {"log_level": level}

    # --- data ------------------------------------------------------------

    def clear(self, what) -> dict:
        if what == "sessions" and self._sessions is not None:
            self._sessions.clear_history()
        elif what == "messages" and self._messages is not None:
            self._messages.clear()
        else:
            raise ValueError("Clear what: sessions or messages")
        logger.info("Cleared the %s from the web page", "session history" if what == "sessions" else "message log")
        return {"cleared": what}

    # --- the connection ----------------------------------------------------

    async def send(self, message, status=None) -> dict:
        if self._send is None:
            raise ValueError("Not available")
        return await self._send(str(message or ""), status)

    async def drop(self, seconds) -> dict:
        if self._drop is None:
            raise ValueError("Not available")
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            raise ValueError("Seconds must be a number")
        if not 0 <= seconds <= 600:
            raise ValueError("Seconds must be 0 to 600")
        return await self._drop(seconds)

    async def restart(self) -> dict:
        if self._restart is None:
            raise ValueError("Not available")
        return await self._restart()
