"""The Octopus Energy API (GraphQL): a Kraken token from the API key, and the
planned flex dispatches for a device, with its status and live readings (an
inverter's telemetry, see src/telemetry.py). Optionally finds the device ID.

The token lasts an hour: it's renewed every TOKEN_RENEW_S, and straight away
if the API says it's expired or not valid.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

API_URL = "https://api.octopus.energy/v1/graphql/"
TOKEN_RENEW_S = 45 * 60
TIMEOUT_S = 30

TOKEN_QUERY = ("mutation krakenTokenAuthentication($apiKey: String!) "
               "{ obtainKrakenToken(input: { APIKey: $apiKey }) { token } }")
DISPATCHES_QUERY = ("query getPlanned($deviceId: String!) "
                    "{ flexPlannedDispatches(deviceId: $deviceId) { start end type energyAddedKwh } }")
# The plan with the device's status and readings, in one go (the readings only come for inverters)
DEVICE_QUERY = ("query getDevice($deviceId: String!, $accountNumber: String!) { "
                "flexPlannedDispatches(deviceId: $deviceId) { start end type energyAddedKwh } "
                "devices(accountNumber: $accountNumber, deviceId: $deviceId) { id status { current currentState isSuspended } "
                "... on SmartFlexInverter { telemetry { inverter { connectionStatus powerInKw } "
                "battery { connectionStatus powerInKw stateOfCharge } solar { powerInKw } grid { powerInKw } "
                "site { consumptionInKw exportInKw } } details { solar { peakSolarPowerInKw } } } } }")
ACCOUNTS_QUERY = "query { viewer { accounts { number } } }"
DEVICES_QUERY = ("query devices($accountNumber: String!) "
                 "{ devices(accountNumber: $accountNumber) { id name deviceType provider } }")


class OctopusError(Exception):
    pass


class AuthError(OctopusError):
    """The API key or token was refused."""


def _errors(body: dict) -> Optional[str]:
    errors = (body or {}).get("errors") or []
    if not errors:
        return None
    return "; ".join(str(e.get("message") or e) for e in errors)


def _is_auth(message: str) -> bool:
    text = message.lower()
    return any(w in text for w in ("token", "authenticat", "unauthor", "api key", "jwt", "expired"))


class OctopusClient:
    def __init__(self, api_key: str, session=None) -> None:
        self.api_key = api_key
        self._session = session  # an aiohttp.ClientSession (made on first use if not given)
        self._token: Optional[str] = None
        self._token_at = 0.0

    async def _post(self, query: str, variables: Optional[dict] = None, token: Optional[str] = None) -> dict:
        import aiohttp

        if self._session is None:
            self._session = aiohttp.ClientSession()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = token
        async with self._session.post(API_URL, json={"query": query, "variables": variables or {}},
                                      headers=headers, timeout=aiohttp.ClientTimeout(total=TIMEOUT_S)) as resp:
            if resp.status in (401, 403):
                raise AuthError(f"Octopus refused it (HTTP {resp.status})")
            if resp.status >= 400:
                raise OctopusError(f"Octopus API error (HTTP {resp.status})")
            return await resp.json(content_type=None)

    async def token(self, force: bool = False) -> str:
        """A Kraken token, renewed when it's old (or `force`)."""
        if self._token and not force and time.time() - self._token_at < TOKEN_RENEW_S:
            return self._token
        if not self.api_key:
            raise AuthError("No API key: set it on the add-on's Configuration tab")
        body = await self._post(TOKEN_QUERY, {"apiKey": self.api_key})
        token = (((body or {}).get("data") or {}).get("obtainKrakenToken") or {}).get("token")
        if not token:
            raise AuthError(_errors(body) or "No token in Octopus's reply: check the API key")
        self._token, self._token_at = token, time.time()
        logger.info("Got a new Kraken token")
        return token

    async def query(self, query: str, variables: Optional[dict] = None) -> dict:
        """Run a query with the token; on an auth error, once more with a new token."""
        for attempt in (0, 1):
            token = await self.token(force=attempt == 1)
            try:
                body = await self._post(query, variables, token)
            except AuthError:
                if attempt == 0:
                    continue
                raise
            message = _errors(body)
            if message and _is_auth(message) and attempt == 0:
                continue
            if message and not (body or {}).get("data"):
                raise OctopusError(message)
            return (body or {}).get("data") or {}
        raise AuthError("Octopus refused the token")

    async def planned_dispatches(self, device_id: str) -> list:
        data = await self.query(DISPATCHES_QUERY, {"deviceId": device_id})
        return list(data.get("flexPlannedDispatches") or [])

    async def read_device(self, device_id: str, account: Optional[str]) -> tuple[list, Optional[dict]]:
        """The planned dispatches and the device itself ({id, status, telemetry, details}, None if not
        sent). Without the account number, only the dispatches."""
        if not account:
            return await self.planned_dispatches(device_id), None
        data = await self.query(DEVICE_QUERY, {"deviceId": device_id, "accountNumber": account})
        device = next((d for d in data.get("devices") or [] if isinstance(d, dict) and d.get("id") == device_id), None)
        return list(data.get("flexPlannedDispatches") or []), device

    async def find_devices(self) -> list:
        """The devices on the account(s) the API key is for: [{id, name, deviceType, provider, account}]."""
        data = await self.query(ACCOUNTS_QUERY)
        out = []
        for account in ((data.get("viewer") or {}).get("accounts") or []):
            number = account.get("number")
            if not number:
                continue
            devices = (await self.query(DEVICES_QUERY, {"accountNumber": number})).get("devices") or []
            out.extend({**d, "account": number} for d in devices if isinstance(d, dict))
        return out

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
