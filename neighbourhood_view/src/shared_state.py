"""What the add-on is doing right now, shown on the web page (Overview) and
pushed to it as it changes (/api/events). Add your own fields here and show
them in renderState() in static/index.html."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class SharedState:
    status: str = "Starting"  # a word or two for the page
    error: Optional[str] = None  # why there's no map (e.g. "The postcode RG41 9ZZ wasn't found")
    made: Optional[str] = None  # when the map was made (ISO 8601, UTC): the page reads it again when it changes
    address: Optional[str] = None  # e.g. "12, RG41 2AB"
    home_found: Optional[str] = None  # how your house was found: address, nearest, picked, postcode
    buildings: int = 0
    card: dict = field(default_factory=dict)
    live: dict = field(default_factory=dict)  # the weather, who's home, night (src/live.py)  # the dashboard card: {"status", "url", "detail"}
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
