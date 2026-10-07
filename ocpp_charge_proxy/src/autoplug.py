"""Auto plug-in when the car's SoC drops below a threshold.

Kept free of Home Assistant imports so the logic can be tested on its own.
"""

from __future__ import annotations

DEFAULT_AUTO_PLUG_SOC = 30


class AutoPlug:
    """Decides when to switch Plugged In on from SoC readings.

    Triggers once when the SoC *drops* below the threshold, not whenever it
    *is* below: unplugging by hand at a low SoC doesn't immediately plug back
    in. It re-arms once the SoC is back at or above the threshold. The first
    reading only arms it (if at or above), so restarting HA with a low SoC
    doesn't plug in either.
    """

    def __init__(self, enabled: bool, threshold: float = DEFAULT_AUTO_PLUG_SOC) -> None:
        self.enabled = enabled
        self.threshold = float(threshold)
        self.armed = False

    def should_plug(self, soc: float | None, plugged_in: bool | None) -> bool:
        if not self.enabled or soc is None:
            return False
        if soc >= self.threshold:
            self.armed = True
            return False
        if not self.armed:
            return False
        self.armed = False  # fire once per drop
        return not plugged_in


class CarConnected:
    """Decides when to switch Plugged In on from a car-connected binary sensor.

    Plugs in when the sensor changes from off to on; never unplugs. Only
    definite on/off readings count: unavailable/unknown in between are
    ignored, so on -> unavailable -> on (e.g. the car's integration
    reconnecting) isn't a new connection. The first reading only sets the
    starting point, so restarting HA with the cable connected doesn't plug in.
    """

    def __init__(self) -> None:
        self.last: str | None = None  # last definite reading: "on" / "off"

    def should_plug(self, state: str | None, plugged_in: bool | None) -> bool:
        if state not in ("on", "off"):
            return False
        previous, self.last = self.last, state
        return previous == "off" and state == "on" and not plugged_in
