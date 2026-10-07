from __future__ import annotations

import logging
import random
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Valid current settings (amps)
VALID_CURRENT_SETTINGS = [6, 10, 13, 16, 20, 25, 32]

# Power delivery model at 32A (~230V unless set on the Settings tab)
# At lower current settings, power scales proportionally
_VOLTAGE_NOMINAL = 230.0
VOLTAGE_RANGE = (100.0, 300.0)  # a supply voltage outside this is ignored
_EFFICIENCY_FACTOR = 0.985  # real delivery is ~98.5% of theoretical


class ChargerSimulator:
    """Simulates realistic power delivery for an OCPP chargepoint.

    Power model:
    - At 32A: steady state ~7.27 kW (230V nominal, 98.5% efficiency)
    - Fluctuation: ±0.08 kW typical, occasionally ±0.15 kW
    - Voltage: ~228-232V (UK grid)
    - Frequency: ~49.95-50.05 Hz

    Current setting supports 6/10/13/16/20/25/32A and power scales
    proportionally.

    Start-up behaviour (like a real car after StartTransaction):
    - start_delay_s: no current is drawn for this long after charging starts
    - ramp_up_s: power then rises linearly from 0 to full over this long
    Both default to 0 (instant full power). Pausing and resuming (e.g. a
    charging profile) repeats the delay and ramp, as a real car would.
    """

    def __init__(
        self,
        current_amps: int = 32,
        start_delay_s: float = 0.0,
        ramp_up_s: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if current_amps not in VALID_CURRENT_SETTINGS:
            logger.warning(
                "Current %dA not in valid settings %s, using closest",
                current_amps, VALID_CURRENT_SETTINGS,
            )
            current_amps = min(VALID_CURRENT_SETTINGS, key=lambda x: abs(x - current_amps))
        self._current_amps = current_amps
        self._charging = False
        self._start_delay_s = max(0.0, float(start_delay_s))
        self._ramp_up_s = max(0.0, float(ramp_up_s))
        self._clock = clock
        self._charging_started_at: Optional[float] = None
        # The supply voltage (Settings › Voltage: a sensor or a set value), or None: 230 V
        self.voltage_source: Optional[Callable[[], Optional[float]]] = None

    @property
    def nominal_voltage(self) -> float:
        """The supply voltage: from the Settings tab if set and sensible, else 230 V."""
        try:
            v = self.voltage_source() if self.voltage_source else None
        except Exception:
            v = None
        if v is not None and VOLTAGE_RANGE[0] <= v <= VOLTAGE_RANGE[1]:
            return float(v)
        return _VOLTAGE_NOMINAL

    @property
    def current_amps(self) -> int:
        return self._current_amps

    @property
    def start_delay_s(self) -> float:
        return self._start_delay_s

    @property
    def ramp_up_s(self) -> float:
        return self._ramp_up_s

    def set_ramp(self, start_delay_s: float, ramp_up_s: float) -> None:
        """Change the start delay / ramp-up (applies from the next start or resume)."""
        self._start_delay_s = max(0.0, float(start_delay_s))
        self._ramp_up_s = max(0.0, float(ramp_up_s))

    @current_amps.setter
    def current_amps(self, value: int) -> None:
        if value not in VALID_CURRENT_SETTINGS:
            raise ValueError(f"Invalid current setting {value}A. Valid: {VALID_CURRENT_SETTINGS}")
        self._current_amps = value
        logger.info("Charger current set to %dA (~%.1f kW)", value, self.rated_power_kw)

    @property
    def rated_power_kw(self) -> float:
        """Theoretical max power at current setting."""
        return round(self._current_amps * self.nominal_voltage / 1000, 1)

    @property
    def expected_power_kw(self) -> float:
        """Expected real-world power delivery (slightly below rated)."""
        return round(self._current_amps * self.nominal_voltage * _EFFICIENCY_FACTOR / 1000, 2)

    def start_charging(self, now: Optional[float] = None) -> None:
        if self._charging:
            return  # already charging: don't restart the delay/ramp
        self._charging = True
        self._charging_started_at = self._clock() if now is None else now

    def stop_charging(self) -> None:
        self._charging = False
        self._charging_started_at = None

    # --- Start delay / ramp-up -------------------------------------------

    def _ramp_integral(self, t: float) -> float:
        """Integral of the ramp factor from charging start to t seconds after it."""
        d, r = self._start_delay_s, self._ramp_up_s
        if t <= d:
            return 0.0
        if r > 0 and t < d + r:
            return (t - d) ** 2 / (2 * r)
        return r / 2 + (t - d - r)

    def ramp_factor(self, now: Optional[float] = None) -> float:
        """Fraction (0..1) of full power the car is drawing right now."""
        if not self._charging or self._charging_started_at is None:
            return 0.0
        t = (self._clock() if now is None else now) - self._charging_started_at
        d, r = self._start_delay_s, self._ramp_up_s
        if t < d:
            return 0.0
        if r > 0 and t < d + r:
            return (t - d) / r
        return 1.0

    def average_ramp_factor(self, t0: float, t1: float) -> float:
        """Mean ramp factor between two clock times, for energy integration.

        Keeps the energy register exact even when readings are far apart
        (e.g. a 60s meter interval spanning the whole delay and ramp).
        """
        if not self._charging or self._charging_started_at is None or t1 <= t0:
            return self.ramp_factor(t1)
        if self._start_delay_s == 0 and self._ramp_up_s == 0:
            return 1.0  # instant start: full power for the whole interval
        a = max(0.0, t0 - self._charging_started_at)
        b = max(0.0, t1 - self._charging_started_at)
        return (self._ramp_integral(b) - self._ramp_integral(a)) / (t1 - t0)

    @staticmethod
    def scale(reading: "ChargerReading", factor: float) -> "ChargerReading":
        """Return a copy of a reading with power/current scaled by factor."""
        if factor >= 1.0:
            return reading
        power_kw = round(reading.power_kw * factor, 2)
        return ChargerReading(
            power_kw=power_kw,
            voltage=reading.voltage,
            current_a=round((power_kw * 1000) / reading.voltage, 2) if power_kw > 0 else 0.0,
            frequency_hz=reading.frequency_hz,
            power_offered_kw=reading.power_offered_kw,
            current_offered_a=reading.current_offered_a,
        )

    @property
    def is_charging(self) -> bool:
        return self._charging

    def sample(self, now: Optional[float] = None) -> ChargerReading:
        """Realistic instantaneous reading, including start delay / ramp-up."""
        full = self.sample_full()
        if not self._charging:
            return full
        return self.scale(full, self.ramp_factor(now))

    def sample_full(self) -> ChargerReading:
        """Reading at full (post-ramp) power, ignoring start delay / ramp-up."""
        nominal = self.nominal_voltage
        voltage = round(random.uniform(nominal - 2.0, nominal + 2.0), 1)
        frequency = round(random.uniform(49.95, 50.05), 2)

        if not self._charging:
            return ChargerReading(
                power_kw=0.0,
                voltage=voltage,
                current_a=0.0,
                frequency_hz=frequency,
                power_offered_kw=0.0,
            )

        # Power based on current setting with realistic fluctuation
        mean_power = self.expected_power_kw
        spread = 0.08 * (self._current_amps / 32)  # scale fluctuation with current

        if random.random() < 0.1:
            # Occasional wider swing
            power_kw = round(random.uniform(mean_power - spread * 2, mean_power + spread * 2), 2)
        else:
            power_kw = round(random.gauss(mean_power, spread), 2)

        power_kw = max(0.1, min(self.rated_power_kw, power_kw))
        current_a = round((power_kw * 1000) / voltage, 2)

        return ChargerReading(
            power_kw=power_kw,
            voltage=voltage,
            current_a=current_a,
            frequency_hz=frequency,
            power_offered_kw=self.rated_power_kw,
            current_offered_a=self._current_amps,
        )


class ChargerReading:
    """Instantaneous reading from the simulated charger."""

    __slots__ = ("power_kw", "voltage", "current_a", "frequency_hz", "power_offered_kw", "current_offered_a")

    def __init__(
        self,
        power_kw: float,
        voltage: float,
        current_a: float,
        frequency_hz: float,
        power_offered_kw: float,
        current_offered_a: int = 32,
    ):
        self.power_kw = power_kw
        self.voltage = voltage
        self.current_a = current_a
        self.frequency_hz = frequency_hz
        self.power_offered_kw = power_offered_kw
        self.current_offered_a = current_offered_a
