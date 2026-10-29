"""Anything new from your supplier: settings, messages and questions the add-on
doesn't know, things it had to refuse, and errors your supplier sent back.

Each is noted once (with when it was first and last seen, and how often), kept
across restarts, shown on Diagnostics › Health › Supplier, and (Settings ›
Notifications) sent as a notification the first time it's seen. So a change on
your supplier's side shows up the day it happens, not when charging breaks.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

MAX_ITEMS = 100

# What each kind means, for the page and the notification
KINDS = {
    "setting": "New setting",
    "message": "New message",
    "asked": "Asked for a setting the add-on doesn't have",
    "refused": "Had to refuse",
    "error": "Your supplier answered with an error",
    "password": "Connection password changed",
}


class SupplierNews:
    def __init__(self, persistence=None, on_new: Optional[Callable[[dict], None]] = None):
        self._persistence = persistence
        self.on_new = on_new
        self.items: dict[str, dict] = {}
        try:
            saved = persistence.load_supplier_news() if persistence is not None else None
        except Exception:
            saved = None
        if isinstance(saved, list):
            for it in saved:
                if isinstance(it, dict) and it.get("id"):
                    self.items[it["id"]] = it

    def note(self, kind: str, name: str, detail: str = "") -> bool:
        """Note one; True if it's the first time (and it's announced)."""
        key = f"{kind}:{name}"
        now = time.time()
        it = self.items.get(key)
        if it is not None:
            it["last"] = now
            it["count"] = it.get("count", 1) + 1
            if detail:
                it["detail"] = detail
            self._save()
            return False
        it = {"id": key, "kind": kind, "what": KINDS.get(kind, kind), "name": name, "detail": detail,
              "first": now, "last": now, "count": 1, "seen": False}
        self.items[key] = it
        while len(self.items) > MAX_ITEMS:  # (the oldest go)
            self.items.pop(min(self.items.values(), key=lambda x: x["last"])["id"])
        self._save()
        logger.warning("New from your supplier: %s: %s%s", it["what"], name, f" ({detail})" if detail else "")
        if self.on_new:
            try:
                self.on_new(it)
            except Exception:
                logger.debug("Couldn't announce it", exc_info=True)
        return True

    def mark_seen(self) -> None:
        for it in self.items.values():
            it["seen"] = True
        self._save()

    def clear(self) -> None:
        self.items.clear()
        self._save()

    def snapshot(self) -> list[dict]:
        return sorted((dict(it) for it in self.items.values()), key=lambda x: x["last"], reverse=True)

    def _save(self) -> None:
        if self._persistence is None:
            return
        try:
            self._persistence.save_supplier_news(list(self.items.values()))
        except Exception:
            logger.debug("Couldn't save the supplier news", exc_info=True)
