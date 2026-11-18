"""The add-on's history, in /data/tigo.db (SQLite, kept across updates).

Times are the system's own local time as Tigo gives them ("YYYY-MM-DD HH:MM", days
"YYYY-MM-DD"), so a day is the day the panels saw.

- system_power: the whole system's power by the minute (W): total, base (what the panels
  would make without the optimisers) and reclaimed (what the optimisers won back).
- system_energy: its energy by the day (Wh), the same three.
- panel_energy: each panel's energy by the day (Wh).
- panel_power: each panel's power and reclaimed power (W), as the add-on read them (Tigo
  keeps only the latest, so these start when the add-on does).
- done: the days whose history has been read in full (not read again).
"""
from __future__ import annotations

import os
import sqlite3
import threading
from typing import Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS system_power (ts TEXT PRIMARY KEY, total REAL, base REAL, reclaimed REAL);
CREATE TABLE IF NOT EXISTS system_energy (day TEXT PRIMARY KEY, total REAL, base REAL, reclaimed REAL);
CREATE TABLE IF NOT EXISTS panel_energy (day TEXT, panel INTEGER, wh REAL, PRIMARY KEY (day, panel));
CREATE TABLE IF NOT EXISTS panel_power (ts TEXT, panel INTEGER, power REAL, reclaimed REAL, PRIMARY KEY (ts, panel));
CREATE TABLE IF NOT EXISTS done (day TEXT, kind TEXT, PRIMARY KEY (day, kind));
"""


class Store:
    def __init__(self, path: Optional[str]) -> None:
        """`path` None: in memory (tests, or no /data)."""
        self.path = path
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._db = sqlite3.connect(path or ":memory:", check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _write(self, sql: str, rows: Iterable[tuple]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        with self._lock:
            self._db.executemany(sql, rows)
            self._db.commit()
        return len(rows)

    def _read(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # --- writing ---------------------------------------------------------------------

    def put_system_power(self, rows: Iterable[tuple]) -> int:
        """(ts, total, base, reclaimed)"""
        return self._write("INSERT OR REPLACE INTO system_power VALUES (?, ?, ?, ?)", rows)

    def put_system_energy(self, rows: Iterable[tuple]) -> int:
        """(day, total, base, reclaimed)"""
        return self._write("INSERT OR REPLACE INTO system_energy VALUES (?, ?, ?, ?)", rows)

    def put_panel_energy(self, day: str, panels: dict) -> int:
        return self._write("INSERT OR REPLACE INTO panel_energy VALUES (?, ?, ?)",
                           ((day, int(p), float(wh)) for p, wh in panels.items()))

    def put_panel_power(self, ts: str, power: dict, reclaimed: dict) -> int:
        ids = set(power) | set(reclaimed)
        return self._write("INSERT OR REPLACE INTO panel_power VALUES (?, ?, ?, ?)",
                           ((ts, int(p), power.get(p), reclaimed.get(p)) for p in ids))

    def mark_done(self, day: str, kind: str) -> None:
        self._write("INSERT OR REPLACE INTO done VALUES (?, ?)", [(day, kind)])

    def is_done(self, day: str, kind: str) -> bool:
        return bool(self._read("SELECT 1 FROM done WHERE day = ? AND kind = ?", (day, kind)))

    # --- reading ---------------------------------------------------------------------

    def system_power(self, day: str) -> list[tuple]:
        """[(ts, total, base, reclaimed)] for the day, by time."""
        return self._read("SELECT ts, total, base, reclaimed FROM system_power WHERE ts >= ? AND ts < ? ORDER BY ts",
                          (day, day + "~"))

    def panel_power(self, day: str, panels: Optional[list] = None) -> list[tuple]:
        """[(ts, panel, power, reclaimed)] for the day, by time."""
        rows = self._read("SELECT ts, panel, power, reclaimed FROM panel_power WHERE ts >= ? AND ts < ? ORDER BY ts",
                          (day, day + "~"))
        if panels is not None:
            keep = {int(p) for p in panels}
            rows = [r for r in rows if r[1] in keep]
        return rows

    def system_energy(self, start: str, end: str) -> list[tuple]:
        """[(day, total, base, reclaimed)] from start to end (days, both included)."""
        return self._read("SELECT day, total, base, reclaimed FROM system_energy WHERE day >= ? AND day <= ? ORDER BY day",
                          (start, end))

    def panel_energy(self, start: str, end: str) -> list[tuple]:
        """[(day, panel, wh)] from start to end."""
        return self._read("SELECT day, panel, wh FROM panel_energy WHERE day >= ? AND day <= ? ORDER BY day",
                          (start, end))

    def first_day(self) -> Optional[str]:
        rows = self._read("SELECT MIN(day) FROM (SELECT MIN(day) AS day FROM system_energy WHERE total > 0 "
                          "UNION SELECT MIN(day) FROM panel_energy WHERE wh > 0)")
        return rows[0][0] if rows and rows[0][0] else None

    def panel_power_since(self) -> Optional[str]:
        rows = self._read("SELECT MIN(ts) FROM panel_power")
        return rows[0][0] if rows and rows[0][0] else None

    def counts(self) -> dict:
        out = {}
        for table in ("system_power", "system_energy", "panel_energy", "panel_power", "done"):
            out[table] = self._read(f"SELECT COUNT(*) FROM {table}")[0][0]
        return out
