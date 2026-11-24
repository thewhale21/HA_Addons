"""Tomorrow's export rates from the day-ahead wholesale prices (src/future_rates.py,
auto_schedule.fit_wholesale / estimate_wholesale)."""
import asyncio
import datetime

from src import auto_schedule as A
from src.future_rates import DEFAULT_URL, FutureRates, parse

TZ = datetime.timezone.utc
D = datetime.datetime(2026, 11, 22, tzinfo=TZ)


def at(h, m=0, day=0):
    return D + datetime.timedelta(days=day, hours=h, minutes=m)


# The user's N2EX answer for 22 Nov (£/MWh, hourly)
WHOLESALE = [176.95, 179.50, 168.89, 164.29, 159.60, 159.48, 159.55, 159.59, 159.46, 164.91, 166.46, 173.57,
             177.79, 177.00, 181.76, 191.06, 192.56, 203.69, 210.01, 203.80, 195.78, 187.31, 178.97, 170.00]


def answer(day=0, prices=WHOLESALE):
    start = D + datetime.timedelta(days=day) - datetime.timedelta(hours=1)  # (CET day: 23:00 UTC the day before)
    return {"multiAreaEntries": [{"deliveryStart": (start + datetime.timedelta(hours=k)).isoformat().replace("+00:00", "Z"),
                                  "deliveryEnd": (start + datetime.timedelta(hours=k + 1)).isoformat().replace("+00:00", "Z"),
                                  "entryPerArea": {"UK": p}} for k, p in enumerate(prices)]}


def agile_out(w_p, t):
    """A made-up export tariff from the wholesale p/kWh: 0.9 x + 1p, 5p more 16:00-19:00."""
    return round(0.9 * w_p + 1.0 + (5.0 if 16 <= t.hour < 19 else 0.0), 2)


def test_parse_the_data_portal_answer():
    p = parse(answer())
    assert len(p) == 24 and p[0] == (at(-1), at(0), 17.695) and p[-1][2] == 17.0
    assert parse(None) == [] and parse({"multiAreaEntries": [{"deliveryStart": "x"}]}) == []


def _today_rates():
    w = parse(answer())
    out = []
    for k in range(46):  # (00:00-23:00: the 23:00 hour is in the next day's answer, CET)
        t = at(0, 30 * k)
        wp = next(p for a, b, p in w if a <= t < b)
        out.append((t, t + A.HH, agile_out(wp, t), False))
    return out


def test_tomorrow_estimated_from_the_wholesale_prices_as_today_compares():
    today = _today_rates()
    tomorrow_w = [x * 1.1 for x in WHOLESALE]  # (tomorrow a bit dearer)
    wholesale = parse(answer()) + parse(answer(1, tomorrow_w))
    fit = A.fit_wholesale(today, wholesale)
    assert abs(fit["a"] - 0.9) < 0.01 and abs(fit["b"] - 1.0) < 0.1 and abs(fit["c"] - 5.0) < 0.1 and fit["n"] == 46
    est, fit2, used = A.estimate_wholesale(today, wholesale, at(0, 0, 2))
    # (23:00 today to 23:00 tomorrow from the wholesale prices; the last hour, not in them, a copy)
    assert used == 48 and len(est) == 50 and fit2 == fit
    t = at(17, 0, 1)  # tomorrow's peak: 1.1 x 210.01 £/MWh (17:00-18:00 UTC)
    want = agile_out(21.001 * 1.1, t)
    assert abs(dict((a, p) for a, _, p, _ in est)[t] - want) < 0.1
    # (no wholesale prices for tomorrow yet: a copy of today's, as before)
    est3, _, used3 = A.estimate_wholesale(today, parse(answer()), at(0, 0, 2))
    assert used3 == 0 and est3 == A.estimate(today, at(0, 0, 2))


def test_no_fit_when_too_few_or_off():
    today = _today_rates()[:8]
    assert A.fit_wholesale(today, parse(answer())) is None
    flat = [(t, e, 15.0, f) for t, e, _, f in _today_rates()]  # (a fixed export rate: nothing to follow)
    assert A.fit_wholesale(flat, parse(answer())) is None


class _Resp:
    def __init__(self, status, data):
        self.status, self._data = status, data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self, content_type=None):
        return self._data


class _Session:
    def __init__(self):
        self.asked, self.tomorrow = [], None

    def get(self, url, timeout=None):
        self.asked.append(url)
        if "2026-11-23" in url:
            return _Resp(204, None) if self.tomorrow is None else _Resp(200, self.tomorrow)
        return _Resp(200, answer())


def test_read_today_and_tomorrow_and_again_until_tomorrows_are_out(monkeypatch):
    import src.future_rates as F
    clock = [1000.0]
    monkeypatch.setattr(F.time, "monotonic", lambda: clock[0])
    f, s = FutureRates(), _Session()
    now = datetime.datetime(2026, 11, 22, 9, 30)
    assert asyncio.run(f.refresh(DEFAULT_URL, now, s))
    assert [u.split("date=")[1][:10] for u in s.asked] == ["2026-11-22", "2026-11-23"]
    assert len(f.prices) == 24 and f.status["days"] == {"2026-11-22": 24, "2026-11-23": 0}
    clock[0] += 60
    assert not asyncio.run(f.refresh(DEFAULT_URL, now, s)) and len(s.asked) == 2  # (not due)
    s.tomorrow = answer(1)
    clock[0] += F.RETRY_S
    assert asyncio.run(f.refresh(DEFAULT_URL, now.replace(hour=10, minute=0), s))
    assert len(f.prices) == 48 and s.asked[-1].endswith("2026-11-23&market=N2EX_DayAhead&deliveryArea=UK&currency=GBP")
    # no address: none (a copy of today's)
    assert asyncio.run(f.refresh(None, now, s)) and f.prices == []


def test_a_failure_is_said_and_tried_again(monkeypatch, caplog):
    import src.future_rates as F
    monkeypatch.setattr(F.time, "monotonic", lambda: 5000.0)

    class Bad(_Session):
        def get(self, url, timeout=None):
            return _Resp(500, None)

    f = FutureRates()
    asyncio.run(f.refresh(DEFAULT_URL, datetime.datetime(2026, 11, 22, 11), Bad()))
    assert "HTTP 500" in f.status["error"] and f.prices == [] and "couldn't read" in caplog.text


def test_the_automatic_schedule_plans_again_when_tomorrows_wholesale_prices_come():
    from src.automation import Automation, ReplugOptions

    class Clock:
        dt = at(12, 25)

    a = Automation(None, ReplugOptions(), now=lambda: Clock.dt, clock=lambda: Clock.dt.timestamp(),
                   localize=lambda naive: naive.replace(tzinfo=TZ))
    a.limit_reset = "12:00"
    today = _today_rates()
    assert a.sync_auto_schedule([], today, 6, cap_min=360, mode="cheapest")
    assert any("day before's are used" in n for n in a.auto_plan["notes"])
    assert not a.sync_auto_schedule([], today, 6, cap_min=360, mode="cheapest")
    a.wholesale = parse(answer()) + parse(answer(1, [x * 0.5 if 2 <= k < 6 else x for k, x in enumerate(WHOLESALE)]))
    assert a.sync_auto_schedule([], today, 6, cap_min=360, mode="cheapest")  # (planned again on them)
    assert any("day-ahead wholesale prices" in n and "0.90 × wholesale" in n for n in a.auto_plan["notes"])
    # tomorrow's cheapest (half price 01:00-05:00 UTC) is where it goes, in tomorrow's limit day
    charge = [(A._when(x), A._when(y)) for x, y in a.auto_plan["charge"]]
    assert any(x >= at(1, 0, 1) and y <= at(5, 0, 1) for x, y in charge)


def test_the_url_setting():
    import pytest
    from src.ha_link import validate_settings
    assert validate_settings({})["auto_future_url"] == DEFAULT_URL
    assert validate_settings({"auto_future_url": ""})["auto_future_url"] == ""
    for bad in ("ftp://x/DATE", "https://example.com/no-date", "not a url DATE"):
        with pytest.raises(ValueError):
            validate_settings({"auto_future_url": bad})
