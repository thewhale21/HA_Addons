"""What the add-on is doing right now, shown on the web page (Overview) and
pushed to it as it changes (/api/events). Add your own fields here and show
them in renderState() in static/index.html."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class SharedState:
    status: str = "Starting"  # a word or two for the Overview card
    example_option: str = ""  # from the add-on's options (src/config.py)
    example_entity: Optional[str] = None  # the entity picked on the Settings tab
    example_value: Optional[str] = None  # ...and its state, live from Home Assistant
    ticks: int = 0  # how many times the worker loop has run (src/__main__.py)
    last_tick: Optional[str] = None  # when, ISO 8601 (UTC)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
