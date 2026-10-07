from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    server_hostname: str
    chargepoint_id: str
    password: str
    charger_model: str
    charger_vendor: str
    charger_serial: str
    firmware_version: str
    initial_energy_wh: int
    use_tls: bool = True

    @property
    def websocket_url(self) -> str:
        scheme = "wss" if self.use_tls else "ws"
        return f"{scheme}://{self.chargepoint_id}:{self.password}@{self.server_hostname}/{self.chargepoint_id}"

    @property
    def redacted_url(self) -> str:
        scheme = "wss" if self.use_tls else "ws"
        return f"{scheme}://{self.chargepoint_id}:***@{self.server_hostname}/{self.chargepoint_id}"


def load_config() -> Config:
    return Config(
        server_hostname=os.environ["IO_SERVER_HOSTNAME"],
        chargepoint_id=os.environ["IO_CHARGEPOINT_ID"],
        password=os.environ["IO_PASSWORD"],
        charger_model=os.environ.get("IO_CHARGER_MODEL", "PLP2-0-2-2"),
        charger_vendor=os.environ.get("IO_CHARGER_VENDOR", "Wall Box Chargers"),
        charger_serial=os.environ.get("IO_CHARGER_SERIAL", ""),
        firmware_version=os.environ.get("IO_FIRMWARE_VERSION", "6.11.16"),
        initial_energy_wh=int(os.environ.get("IO_INITIAL_ENERGY_WH", "0")),
        use_tls=os.environ.get("IO_USE_TLS", "true").lower() != "false",
    )


DEFAULT_CURRENT_AMPS = 32


def starting_current_amps(persistence) -> int:
    """The max current set last time (web page or Home Assistant), else 32 A."""
    from src.charger_sim import VALID_CURRENT_SETTINGS
    saved = persistence.load_current_setting()
    try:
        amps = int(saved["amps"]) if saved else DEFAULT_CURRENT_AMPS
    except (TypeError, ValueError, KeyError):
        amps = DEFAULT_CURRENT_AMPS
    return amps if amps in VALID_CURRENT_SETTINGS else DEFAULT_CURRENT_AMPS
