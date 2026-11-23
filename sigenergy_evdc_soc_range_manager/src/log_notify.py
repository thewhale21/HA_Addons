"""Notifications (Settings › Watch only and notifications): what's sent to the notify service picked,
by how important it is (`notify_level`): "info" (everything: starts and stops too), "warning"
(warnings and errors), "error" (errors only) or "none".

- Starts and stops of the charger are "info"; the dropout alert "warning"; a charger alarm "error".
- Warning and error lines in the add-on's log are sent too (LogNotifyHandler -> LogNotifier): the lines
  a few seconds apart in one notification, the same line (numbers aside) at most once an hour.

Pure apart from the clock passed in (as the OCPP Charge Proxy's src/log_notify.py).
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Callable, Optional

LEVELS = ("none", "error", "warning", "info")  # the setting: from nothing to everything
RANK = {"info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}
GATHER_S = 10  # log lines this close together go in one notification
REPEAT_S = 3600  # the same line again within this long isn't sent again
MAX_LINES = 5
MAX_CHARS = 300
KEEP = 50

IGNORED_LOGGERS = ("aiohttp.access",)
IGNORED_START = ("Couldn't send the notification", "Couldn't send a notification")
# (anything that looks like a secret: a token, key or password after its name, or a long token)
_SECRET = re.compile(r"(?i)((?:token|password|passwd|secret|api[_-]?key|authorization)\S*\s*[=:]\s*)\S+|\b[A-Za-z0-9_\-]{32,}\.[A-Za-z0-9_\-.]+\b")


def wanted(setting: Optional[str], level: str) -> bool:
    """Whether a notification of `level` ("info", "warning", "error") is sent with the setting."""
    if setting not in RANK:
        return False
    return RANK.get(level, logging.INFO) >= RANK[setting]


def redact(text: str) -> str:
    return _SECRET.sub(lambda m: (m.group(1) or "") + "***", text)


def _key(text: str) -> str:
    """The line with its numbers, times and IDs taken out: the same problem again."""
    return re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}|\d+(?:[.:]\d+)*", "#", text.lower())[:200]


class LogNotifier:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._waiting: list[tuple[float, int, str]] = []
        self._sent: dict[str, float] = {}

    def add(self, now: float, levelno: int, name: str, text: str) -> None:
        if name.startswith(IGNORED_LOGGERS) or str(text).startswith(IGNORED_START):
            return
        text = redact(" ".join(str(text).split()))[:MAX_CHARS]
        with self._lock:
            self._waiting.append((now, levelno, text))
            del self._waiting[:-KEEP]

    def due(self, now: float, setting: Optional[str]) -> Optional[tuple[str, str]]:
        """(title, message) to send now, or None: once the latest line is GATHER_S old."""
        with self._lock:
            if setting not in RANK:
                self._waiting.clear()
                return None
            if not self._waiting or now - self._waiting[-1][0] < GATHER_S:
                return None
            lines, self._waiting = self._waiting, []
            for k in [k for k, t in self._sent.items() if now - t >= REPEAT_S]:
                del self._sent[k]
            out, seen = [], set()
            for _, levelno, text in lines:
                k = _key(text)
                if levelno < max(RANK[setting], logging.WARNING) or k in self._sent or k in seen:
                    continue
                seen.add(k)
                out.append((levelno, text))
            for k in seen:
                self._sent[k] = now
        if not out:
            return None
        error = any(lv >= logging.ERROR for lv, _ in out)
        title = "EVDC: " + ("error" if error else "warning") + ("s" if len(out) > 1 else "")
        shown = [("Error: " if lv >= logging.ERROR else "") + text for lv, text in out[:MAX_LINES]]
        if len(out) > MAX_LINES:
            shown.append(f"…and {len(out) - MAX_LINES} more (Diagnostics)")
        return title, "\n".join(shown)


class LogNotifyHandler(logging.Handler):
    """Hands each WARNING or worse line to the notifier."""

    def __init__(self, notifier: LogNotifier, clock: Callable[[], float]) -> None:
        super().__init__(level=logging.WARNING)
        self.notifier = notifier
        self.clock = clock

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.notifier.add(self.clock(), record.levelno, record.name, record.getMessage())
        except Exception:  # (a log line must never break)
            pass
