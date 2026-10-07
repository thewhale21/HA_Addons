"""The car's SoC over the last two days, with the limits in use and what the
charger was doing, for the Overview's SoC chart. A point is kept when
anything changes, and every few minutes anyway. Saved in
/data/soc_history.json; filled from Home Assistant's history once, so the
chart isn't empty after installing (those points have no limits).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

KEEP_S = 50 * 3600
STEP_S = 300  # a point at least this often, even if nothing changed
SAVE_EVERY_S = 600


class SocHistory:
    def __init__(self, data_dir: Optional[str] = None) -> None:
        self._path = os.path.join(data_dir, "soc_history.json") if data_dir else None
        self.points: list[list] = []  # [ts, soc, high, low, state]: state "charge", "discharge", "idle", "unplugged" or "alarm"
        self.backfilled = False
        self.alarms_fixed = False  # points from before alarms were recognised (0.13.0) relabelled
        self._saved_at = 0.0
        self._load()

    def _load(self) -> None:
        if not self._path:
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            self.points = [p for p in data.get("points") or [] if isinstance(p, list) and len(p) == 5]
            self.backfilled = bool(data.get("backfilled"))
            self.alarms_fixed = bool(data.get("alarms_fixed"))
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("SoC history %s is unreadable: starting afresh", self._path)

    def save(self, now: Optional[float] = None) -> None:
        if now is not None:
            self._saved_at = now
        if not self._path:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"points": self.points, "backfilled": self.backfilled, "alarms_fixed": self.alarms_fixed}, f)
            os.replace(tmp, self._path)
        except Exception:
            logger.warning("Could not save the SoC history", exc_info=True)

    def add(self, now: float, soc: Optional[float], high: Optional[float], low: Optional[float], state: str) -> None:
        point = [round(now, 1), soc, high, low, state]
        last = self.points[-1] if self.points else None
        if last is not None and last[1:] == point[1:] and now - last[0] < STEP_S:
            return
        if last is not None and now < last[0]:
            return
        self.points.append(point)
        cutoff = now - KEEP_S
        if self.points[0][0] < cutoff:
            self.points = [p for p in self.points if p[0] >= cutoff]
        if now - self._saved_at >= SAVE_EVERY_S:
            self.save(now)

    def backfill(self, points: list) -> int:
        """Older points (from Home Assistant's history), before the first recorded one."""
        first = self.points[0][0] if self.points else float("inf")
        older = sorted([p for p in points if p[0] < first], key=lambda p: p[0])
        self.points = older + self.points
        self.backfilled = True
        self.save()
        return len(older)

    def fix_alarms(self, history_points: list, slack_s: float = 30) -> int:
        """Once: points recorded as "unplugged" while Home Assistant's history says the charger
        was in alarm (before 0.13.0 an alarm read as unplugged) become "alarm"."""
        hist = sorted(history_points, key=lambda p: p[0])
        fixed = 0
        for p in self.points:
            if p[4] != "unplugged":
                continue
            then = None
            for h in hist:  # what the history says at that time (the point may be a few seconds late)
                if h[0] > p[0] + slack_s:
                    break
                then = h[4]
            if then == "alarm":
                p[4] = "alarm"
                fixed += 1
        self.alarms_fixed = True
        self.save()
        return fixed

    def window(self, hours: float, now: float) -> list:
        start = now - hours * 3600
        inside = [p for p in self.points if p[0] >= start]
        before = [p for p in self.points if p[0] < start]
        if before:  # where the line was when the window starts
            inside.insert(0, [start, *before[-1][1:]])
        return inside
