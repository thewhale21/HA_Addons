"""The connection password your supplier may set (src/auth_key.py)."""
from unittest.mock import MagicMock

from src.auth_key import AuthKey, refused_status
from src.config import Config


def _config(password="mine"):
    return Config(server_hostname="ocpp.example", chargepoint_id="CP1", password=password,
                  charger_model="m", charger_vendor="v", charger_serial="s", firmware_version="f",
                  initial_energy_wh=0)


class _Store:
    def __init__(self):
        self.v = None

    def load_auth_key(self):
        return self.v

    def save_auth_key(self, v):
        self.v = v


def test_uses_the_new_password_and_keeps_it():
    store = _Store()
    a = AuthKey(store, "mine")
    assert a.url(_config()) == "wss://CP1:mine@ocpp.example/CP1" and not a.rotated
    a.set_new("n3w/key")
    assert a.rotated and a.url(_config()) == "wss://CP1:n3w%2Fkey@ocpp.example/CP1"
    assert AuthKey(store, "mine").rotated  # (after a restart)
    assert "mine" not in str(store.v)  # (only a fingerprint of the old one)


def test_refused_falls_back_then_drops_it():
    store = _Store()
    a = AuthKey(store, "mine")
    a.set_new("newkey")
    a.refused()
    assert a.password() == "mine"
    a.connected()
    assert store.v is None and not a.rotated


def test_changing_the_option_wins():
    store = _Store()
    AuthKey(store, "mine").set_new("newkey")
    b = AuthKey(store, "changed-by-you")
    assert b.password() == "changed-by-you" and store.v is None


def test_refused_status():
    assert refused_status(MagicMock(status_code=401))
    assert refused_status(MagicMock(spec=[], response=MagicMock(status_code=403))) is True
    assert not refused_status(MagicMock(status_code=500))
    assert not refused_status(OSError("down"))
