"""The connection password, as your supplier may change it.

OCPP 1.6 (security extension): the server can set a new password with
ChangeConfiguration AuthorizationKey; a charger keeps it and uses it from the
next connection. Here it's kept in the add-on's data (never logged or shown),
used instead of the one in the add-on's options, and:
- if the server refuses it (HTTP 401/403), the add-on's own password is tried
  again; if that's accepted, the new one is dropped
- if you change the password in the add-on's options, yours is used again
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


def _fp(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


class AuthKey:
    def __init__(self, persistence, configured: str):
        self._persistence = persistence
        self._configured = configured
        self._key: Optional[str] = None
        self._fallback = False  # the new key was refused: trying the configured one
        try:
            saved = persistence.load_auth_key()
        except Exception:
            saved = None
        if isinstance(saved, dict) and isinstance(saved.get("key"), str) and saved["key"]:
            if saved.get("replaced") == _fp(configured):
                self._key = saved["key"]
            else:
                logger.info("The password in the add-on's options has changed: using it, not the one your supplier set")
                self._save(None)

    @property
    def rotated(self) -> bool:
        """Is the add-on using a password your supplier set?"""
        return self._key is not None and not self._fallback

    def password(self) -> str:
        return self._key if self._key is not None and not self._fallback else self._configured

    def url(self, config) -> str:
        """The connection URL with the password in use."""
        if not self.rotated:
            return config.websocket_url
        scheme = "wss" if config.use_tls else "ws"
        return (f"{scheme}://{config.chargepoint_id}:{quote(self._key, safe='')}"
                f"@{config.server_hostname}/{config.chargepoint_id}")

    def set_new(self, key: str) -> None:
        """The server set a new password (ChangeConfiguration AuthorizationKey)."""
        self._key = key
        self._fallback = False
        self._save(key)
        logger.info("Your supplier set a new connection password: it's used from the next connection")

    def refused(self) -> None:
        """The server refused the connection (401/403)."""
        if self._key is not None and not self._fallback:
            logger.warning("Your supplier refused the password it set: trying the one in the add-on's options")
            self._fallback = True

    def connected(self) -> None:
        if self._key is not None and self._fallback:
            logger.warning("The add-on's own password was accepted: dropping the one your supplier set")
            self._key = None
            self._fallback = False
            self._save(None)

    def _save(self, key: Optional[str]) -> None:
        try:
            self._persistence.save_auth_key({"key": key, "replaced": _fp(self._configured)} if key else None)
        except Exception:
            logger.warning("Couldn't save the connection password your supplier set", exc_info=True)


def refused_status(err) -> bool:
    """Was a failed connection refused for its password (HTTP 401 or 403)?"""
    status = getattr(err, "status_code", None)
    if status is None:
        status = getattr(getattr(err, "response", None), "status_code", None)
    return status in (401, 403)
