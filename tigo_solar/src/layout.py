"""Where each panel is drawn on the page: Tigo's own layout (each panel's left and top
in the portal), or where you've dragged it (saved in /data/layout.json, by panel ID)."""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

GRID_X, GRID_Y = 90, 110  # a panel without a place on Tigo's layout: a grid, a row per string


class Layout:
    def __init__(self, data_dir: Optional[str]) -> None:
        self._path = os.path.join(data_dir, "layout.json") if data_dir else None
        self.moved: dict[int, dict] = {}  # panel ID -> {"left", "top"}
        self._load()

    def _load(self) -> None:
        if not self._path:
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                raw = json.load(f)
            self.moved = {int(k): {"left": float(v["left"]), "top": float(v["top"])}
                          for k, v in (raw.get("moved") or {}).items()}
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("The panel layout %s is unreadable: using Tigo's", self._path)

    def _save(self) -> None:
        if not self._path:
            return
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"moved": {str(k): v for k, v in self.moved.items()}}, f, indent=1)
        os.replace(tmp, self._path)

    def apply(self, panels: list) -> list:
        """The panels with left and top to draw them at (yours, else Tigo's, else a grid),
        and "moved" where they're yours."""
        out = []
        rows: dict = {}
        for p in panels:
            p = dict(p)
            mine = self.moved.get(p["id"])
            if mine:
                p["left"], p["top"], p["moved"] = mine["left"], mine["top"], True
            else:
                p["moved"] = False
                if p.get("left") is None or p.get("top") is None:
                    row = rows.setdefault(p.get("string") or "", len(rows))
                    col = sum(1 for q in out if q.get("_row") == row)
                    p["left"], p["top"], p["_row"] = 50 + col * GRID_X, 50 + row * GRID_Y, row
            out.append(p)
        for p in out:
            p.pop("_row", None)
        return out

    def update(self, body) -> None:
        """{"moved": {panel ID: {"left", "top"}}} (set, or null to put one back) or {"reset": true}."""
        if not isinstance(body, dict):
            raise ValueError("Send a JSON object")
        if body.get("reset"):
            self.moved = {}
        for key, value in (body.get("moved") or {}).items():
            try:
                pid = int(key)
            except (TypeError, ValueError):
                raise ValueError(f"Not a panel ID: {key}") from None
            if value is None:
                self.moved.pop(pid, None)
                continue
            try:
                left, top = float(value["left"]), float(value["top"])
            except (KeyError, TypeError, ValueError):
                raise ValueError("Each panel needs a left and a top") from None
            if not (-5000 <= left <= 5000 and -5000 <= top <= 5000):
                raise ValueError("That's off the roof")
            self.moved[pid] = {"left": round(left, 1), "top": round(top, 1)}
        self._save()
