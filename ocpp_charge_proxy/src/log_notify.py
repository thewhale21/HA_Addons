"""Notifications for warnings and errors in the add-on's log (Settings ›
Notifications › Problems in the log): none, warnings and errors, or errors only.

A logging handler (LogNotifyHandler) hands each WARNING or worse line to a
LogNotifier, which gathers them and says what to send: the lines from a few
seconds together in one notification (a problem often logs two or three), and
the same line (numbers aside) at most once every REPEAT_S, so one that comes
back every few minutes (e.g. Home Assistant unreachable) doesn't flood the
phone. src/__main__.py sends them through Home Assistant's notify service.

Pure apart from the clock passed in.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Callable, Optional

from src.log_filters import redact_secrets

LEVELS = ("none", "warning", "error")  # the setting: what's sent
GATHER_S = 10  # lines this close together go in one notification
REPEAT_S = 3600  # the same line again within this long isn't sent again
MAX_LINES = 5  # lines in one notification (and "and N more")
MAX_CHARS = 300  # of each line
KEEP = 50  # lines waiting at most (the oldest dropped)

# Lines that aren't sent: a notification that couldn't be sent (it would only
# try to send that), and the web server's own request lines
IGNORED_LOGGERS = ("aiohttp.access",)
IGNORED_START = ("Couldn't send a notification",)


def _key(text: str) -> str:
    """The line with its numbers, times and IDs taken out: the same problem again."""
    return re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}|\d+(?:[.:]\d+)*", "#", text.lower())[:200]


def wanted(setting: Optional[str], levelno: int) -> bool:
    if setting == "warning":
        return levelno >= logging.WARNING
    if setting == "error":
        return levelno >= logging.ERROR
    return False


class LogNotifier:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._waiting: list[tuple[float, int, str]] = []  # (when, level, text)
        self._sent: dict[str, float] = {}  # line key -> when last sent

    def add(self, now: float, levelno: int, name: str, text: str) -> None:
        if name.startswith(IGNORED_LOGGERS) or text.startswith(IGNORED_START):
            return
        text = redact_secrets(" ".join(str(text).split()))[:MAX_CHARS]
        with self._lock:
            self._waiting.append((now, levelno, text))
            del self._waiting[:-KEEP]

    def due(self, now: float, setting: Optional[str]) -> Optional[tuple[str, str]]:
        """(title, message) to send now, or None: once the latest line is GATHER_S old."""
        with self._lock:
            if setting not in ("warning", "error"):
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
                if not wanted(setting, levelno) or k in self._sent or k in seen:
                    continue
                seen.add(k)
                out.append((levelno, text))
            for k in seen:
                self._sent[k] = now
        if not out:
            return None
        error = any(lv >= logging.ERROR for lv, _ in out)
        title = "OCPP Charge Proxy: " + ("error" if error else "warning") + ("s" if len(out) > 1 else "")
        shown = [("Error: " if lv >= logging.ERROR else "") + text for lv, text in out[:MAX_LINES]]
        if len(out) > MAX_LINES:
            shown.append(f"…and {len(out) - MAX_LINES} more (Diagnostics › Debug)")
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
