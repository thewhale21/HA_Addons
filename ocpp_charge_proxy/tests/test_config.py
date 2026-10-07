import os
from unittest.mock import patch

from src.config import Config, load_config


def test_load_config_from_env():
    env = {
        "IO_SERVER_HOSTNAME": "ocpp.example.com",
        "IO_CHARGEPOINT_ID": "CP001",
        "IO_PASSWORD": "secret",
        "IO_CHARGER_MODEL": "PLP2-0-2-2",
        "IO_CHARGER_VENDOR": "Wall Box Chargers",
    }
    with patch.dict(os.environ, env, clear=False):
        cfg = load_config()

    assert cfg.server_hostname == "ocpp.example.com"
    assert cfg.chargepoint_id == "CP001"
    assert cfg.password == "secret"


def test_config_websocket_url():
    cfg = Config(
        server_hostname="ocpp.example.com",
        chargepoint_id="CP001",
        password="secret",
        charger_model="PLP2-0-2-2",
        charger_vendor="Wall Box Chargers",
        charger_serial="",
        firmware_version="6.11.16",
        initial_energy_wh=0,
    )
    assert cfg.websocket_url == "wss://CP001:secret@ocpp.example.com/CP001"


def test_config_redacted_url():
    cfg = Config(
        server_hostname="ocpp.example.com",
        chargepoint_id="CP001",
        password="secret",
        charger_model="PLP2-0-2-2",
        charger_vendor="Wall Box Chargers",
        charger_serial="",
        firmware_version="6.11.16",
        initial_energy_wh=0,
    )
    assert "secret" not in cfg.redacted_url
    assert "CP001" in cfg.redacted_url

