"""What the add-on knows right now, shown on the web page and pushed to it as it
changes (/api/events), and posted to Home Assistant as sensors (src/ha_entities.py)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class SharedState:
    status: str = "Starting"  # a few words for the page
    error: Optional[str] = None  # the last thing that went wrong talking to Tigo
    configured: bool = False  # username, password and system ID set
    premium: Optional[bool] = None  # the system's Tigo plan (None: not known yet)
    timezone: Optional[str] = None
    sunrise: Optional[str] = None
    sunset: Optional[str] = None
    # The system (src/tigo_data.py parse_config), with each panel's latest readings
    # (power, reclaimed, energy_today) and its place on the roof (left, top: yours if moved)
    panels: list = field(default_factory=list)
    strings: list = field(default_factory=list)
    inverters: list = field(default_factory=list)
    # The whole system now
    power: Optional[float] = None  # W
    reclaimed: Optional[float] = None  # W
    as_of: Optional[str] = None  # the latest reading's time (system time, "YYYY-MM-DD HH:MM")
    today_wh: Optional[float] = None
    today_reclaimed_wh: Optional[float] = None
    month_wh: Optional[float] = None
    year_wh: Optional[float] = None
    lifetime_wh: Optional[float] = None
    last_poll: Optional[str] = None  # when Tigo was last read (UTC)
    # Reading the history (src/collector.py backfill)
    history: dict = field(default_factory=dict)
    layout_moved: bool = False  # panels moved on the page (src/layout.py)

    def to_dict(self) -> dict:
        return asdict(self)
