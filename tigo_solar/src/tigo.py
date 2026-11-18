"""The Tigo cloud: logs in to the Tigo portal (ei.tigoenergy.com) as you and reads your
system's data, as its web pages do. Works on the free plan (panel power, reclaimed
power and energy); the premium plan's readings (voltages, temperature...) aren't used.

The login and the retries are based on the Tigo integration for Home Assistant by
Martin Stoffel (https://github.com/MartinStoffel/tigo, MIT licence): the login page's
CSRF token, then the form, then the wssJwt cookie as a bearer token.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

TIGO_URL = "https://ei.tigoenergy.com"
# Tigo's servers often answer with a server error (5xx) and succeed a few seconds
# later. Its own portal retries after 5 seconds too.
RETRIES = 2
RETRY_DELAY_S = 5
TIMEOUT_S = 30


class TigoError(Exception):
    """Talking to the Tigo cloud failed."""


class TigoAuthError(TigoError):
    """The Tigo cloud refused the login."""


class TigoClient:
    def __init__(self, username: str, password: str, system_id: str, session=None) -> None:
        self._username = username
        self._password = password
        self.system_id = str(system_id).strip()
        self._session = session  # aiohttp.ClientSession: made on first use if not given
        self._own_session = session is None
        self._token: Optional[str] = None
        self._valid_till = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
        self.requests = 0  # (for Diagnostics)

    async def close(self) -> None:
        if self._own_session and self._session is not None:
            await self._session.close()
            self._session = None

    def _get_session(self):
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT_S))
        return self._session

    def forget_login(self) -> None:
        self._valid_till = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

    async def _login(self) -> str:
        now = datetime.datetime.now(datetime.timezone.utc)
        if self._token and self._valid_till > now:
            return self._token
        session = self._get_session()
        # An empty jar, or the cookie of an earlier login would hide a refused one
        session.cookie_jar.clear()
        async with session.get(TIGO_URL) as resp:
            if resp.status != 200:
                raise TigoError(f"The Tigo login page answered {resp.status}")
            text = await resp.text()
        csrf = next((line.split('"')[1] for line in text.split("\n")
                     if "TIGO_CSRF_TOKEN" in line and line.count('"') >= 2), None)
        if csrf is None:
            raise TigoError("No CSRF token on the Tigo login page")
        form = {"_csrf": csrf, "LoginFormModel[login]": self._username,
                "LoginFormModel[password]": self._password, "LoginFormModel[remember_me]": "0"}
        async with session.post(TIGO_URL, data=form) as resp:
            status = resp.status
        cookie = next((c for c in session.cookie_jar if c.key == "wssJwt"), None)
        if cookie is None:
            if status in (200, 401, 403):  # (a refused login shows the form again)
                raise TigoAuthError("Tigo refused the login: check the username and password")
            raise TigoError(f"The Tigo login answered {status}")
        try:
            seconds = int(cookie["max-age"])
        except (KeyError, TypeError, ValueError):
            seconds = 3600 * 6
        self._token = cookie.value
        self._valid_till = now + datetime.timedelta(seconds=max(60, seconds - 3600))
        logger.info("Logged in to Tigo")
        return self._token

    async def get_json(self, path: str) -> Any:
        """GET a portal path as JSON, logged in; retried on a server error, logged in again
        once if the login has run out."""
        relogged = False
        last = None
        for attempt in range(1 + RETRIES):
            if attempt:
                await asyncio.sleep(RETRY_DELAY_S)
            token = await self._login()
            self.requests += 1
            async with self._get_session().get(
                    TIGO_URL + path, headers={"accept": "application/json", "Authorization": f"Bearer {token}"}) as resp:
                last = resp.status
                if resp.status == 200:
                    return await resp.json(content_type=None)
                if resp.status in (401, 403) and not relogged:
                    self.forget_login()
                    relogged = True
                    continue
                if resp.status < 500:
                    break
        raise TigoError(f"Tigo answered {last} for {path.split('?')[0]}")

    # --- the system's data ------------------------------------------------------------

    async def config(self) -> Any:
        return await self.get_json(f"/system/summary/config?system_id={self.system_id}&resourceId=config&v=0.1.0&_=0")

    async def systeminfo(self, date: str) -> Any:
        return await self.get_json(f"/system/summary/systeminfo?system_id={self.system_id}&date={date}"
                                   f"&resourceId=dateinfo-{date}&v=0.1.0&_=0")

    async def aggenergy(self, date: str) -> Any:
        """Each panel's energy on `date` (YYYY-MM-DD)."""
        return await self.get_json(f"/api/v4/system/summary/aggenergy?system_id={self.system_id}&date={date}")

    async def lastvalue(self, date: str, value: str, hhmm: str) -> Any:
        """Each panel's reading of `value` (pin, reclaimedPower) at `hhmm` (the latest
        reading's time) on `date`."""
        return await self.get_json(f"/api/v4/system/summary/lastvalue?system_id={self.system_id}"
                                   f"&resourceId=lastValue-{date}-{value}-{hhmm}&v=0.1.0&_=0")

    async def aggregate(self, agg: str, start: str, end: str, line: bool = False) -> Any:
        """The system's production: agg "minute" (power, W, a line), "hour", "day", "month"
        or "year" (energy, Wh, bars), with base and reclaimed."""
        return await self.get_json(f"/api/v4/data/aggregate?systemId={self.system_id}&view=gen&output=echart"
                                   f"&type={'line' if line else 'bar'}&agg={agg}&start={start}&end={end}&reclaimed=true")

    async def lifetime(self) -> Any:
        return await self.get_json(f"/fleet/system/overview/data-lifetime?sysid={self.system_id}&range=lifetime")
