"""What the add-on is doing right now, shown on the web page (Overview) and
pushed to it as it changes (/api/events)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class SharedState:
    status: str = "Starting"  # a word or two for the Overview card
    error: Optional[str] = None  # what went wrong last time, if anything
    device_id: Optional[str] = None  # the device whose dispatches are read
    devices: list = field(default_factory=list)  # the account's devices, when it had to find one
    last_update: Optional[str] = None  # when the dispatches were last read, ISO 8601 (UTC)
    poll_seconds: int = 60
    summary: dict = field(default_factory=dict)  # src/dispatches.py summarise(): what the sensors show
    completed: list = field(default_factory=list)  # completed sessions, newest first (src/dispatches.py)
    changes: list = field(default_factory=list)  # changes to the plan, newest first (src/dispatches.py)
    soc_entity: Optional[str] = None  # the home battery's SoC sensor (Settings), for the History tab
    calendar: dict = field(default_factory=dict)  # the calendar of dispatches (src/calendar_sync.py)
    telemetry: Optional[dict] = None  # the battery's readings and status (src/telemetry.py), None: none sent

    def to_dict(self) -> dict:
        return asdict(self)
