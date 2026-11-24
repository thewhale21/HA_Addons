"""Tomorrow's export rates, estimated before they're out (Automations › Automatic schedule ›
Tomorrow's rates from): the day-ahead wholesale prices (Nord Pool's N2EX auction for the UK,
published about 10:00 for the next day) are read from a URL, and auto_schedule.estimate_wholesale
turns them into export rates the way today's real rates compare with today's wholesale prices.
Until Octopus publishes tomorrow's (about 16:00) the automatic schedule plans on those, not on a
copy of today's.

The URL has DATE in it, for the day (YYYY-MM-DD): today's and tomorrow's are read. The answer
is Nord Pool's data portal JSON: {"multiAreaEntries": [{"deliveryStart", "deliveryEnd",
"entryPerArea": {"UK": £/MWh}}]}; nothing published yet is an empty answer (HTTP 204).
"""
from __future__ import annotations

import datetime
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_URL = ("https://dataportal-api.nordpoolgroup.com/api/DayAheadPrices?date=DATE"
               "&market=N2EX_DayAhead&deliveryArea=UK&currency=GBP")
RETRY_S = 15 * 60  # a day not published yet: looked for again this often (09:00-17:00; hourly otherwise)
REFRESH_S = 6 * 3600  # a day that's been read: read again after this long
TIMEOUT_S = 30


def _when(text) -> Optional[datetime.datetime]:
    try:
        t = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def parse(data) -> list:
    """The data portal's answer -> [(start, end, p/kWh)] (aware, UTC): £/MWh / 10."""
    out = []
    for e in (data or {}).get("multiAreaEntries") or [] if isinstance(data, dict) else []:
        if not isinstance(e, dict):
            continue
        a, b = _when(e.get("deliveryStart")), _when(e.get("deliveryEnd"))
        prices = [v for v in (e.get("entryPerArea") or {}).values() if isinstance(v, (int, float))]
        if a is None or b is None or b <= a or not prices:
            continue
        out.append((a, b, round(prices[0] / 10, 3)))
    return sorted(out)


class FutureRates:
    """Today's and tomorrow's wholesale prices from the URL, read when they're due (refresh())."""

    def __init__(self) -> None:
        self._days: dict = {}  # "YYYY-MM-DD" -> {"at": monotonic, "prices": [...] or [] (not out yet)}
        self._url: Optional[str] = None
        self.status: dict = {"url": None, "error": None, "read_at": None, "days": {}}

    @property
    def prices(self) -> list:
        return sorted(p for d in self._days.values() for p in d["prices"])

    def _due(self, day: str, now_local: datetime.datetime) -> bool:
        d = self._days.get(day)
        if d is None:
            return True
        age = time.monotonic() - d["at"]
        if d["prices"]:
            return age >= REFRESH_S
        return age >= (RETRY_S if 9 <= now_local.hour < 17 else 3600)

    async def refresh(self, url: Optional[str], now_local: datetime.datetime, session) -> bool:
        """Read today's and tomorrow's if they're due (`session`: an aiohttp ClientSession).
        Returns whether the prices changed. No URL: none (and the estimate is a copy of today's)."""
        if url != self._url:
            self._days, self._url = {}, url
            self.status = {"url": url, "error": None, "read_at": None, "days": {}}
            if not url:
                return True
        if not url:
            return False
        before = self.prices
        today = now_local.date()
        for day in (today, today + datetime.timedelta(days=1)):
            key = day.isoformat()
            if not self._due(key, now_local):
                continue
            try:
                async with session.get(url.replace("DATE", key), timeout=TIMEOUT_S) as r:
                    if r.status == 204:
                        prices = []
                    elif r.status != 200:
                        raise RuntimeError(f"HTTP {r.status}")
                    else:
                        prices = parse(await r.json(content_type=None))
            except Exception as err:
                msg = f"{key}: {err or type(err).__name__}"
                if self.status.get("error") != msg:
                    logger.warning("Tomorrow's rates: couldn't read the wholesale prices for %s", msg)
                self.status["error"] = msg
                # (looked for again after RETRY_S, keeping what was read before)
                self._days[key] = {"at": time.monotonic(), "prices": (self._days.get(key) or {}).get("prices") or []}
                continue
            had = (self._days.get(key) or {}).get("prices")
            self._days[key] = {"at": time.monotonic(), "prices": prices}
            self.status.update(error=None, read_at=time.time())
            self.status["days"][key] = len(prices)
            if prices and not had:
                logger.info("Tomorrow's rates: wholesale prices for %s read (%d)", key, len(prices))
        # (days gone: forgotten)
        for key in [k for k in self._days if k < today.isoformat()]:
            del self._days[key]
            self.status["days"].pop(key, None)
        return self.prices != before
