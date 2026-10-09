"""What the add-on is doing right now, shown on the web page (Overview) and
pushed to it as it changes (/api/events). The statistics themselves are at
/api/stats (src/evstats.py summary())."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class SharedState:
    status: str = "Starting"  # a word or two for the header
    reason: str = ""  # ...and why
    car: dict = field(default_factory=dict)  # the car's readings now: soc, range_km, temp_c, odometer_km...
    brief: dict = field(default_factory=dict)  # the headline figures (summary()["now"], efficiency, health)
    stats_at: Optional[str] = None  # when the statistics last changed (the page reloads them then)
    trips: int = 0
    backfill: Optional[str] = None  # how reading Home Assistant's history went

    def to_dict(self) -> dict:
        return asdict(self)
