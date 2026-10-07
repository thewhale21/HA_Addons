"""The car's battery statistics (src/stats.py)."""

import datetime

from src.manager import samples_from_history
from src.ha_link import default_settings
from src.stats import Sample, StatsRecorder

T0 = datetime.datetime(2026, 10, 7, 1, 0).timestamp()  # 1 am local


def charge_session(rec, start, soc_from, soc_to, kwh_per_pct=0.6, step_s=60, pv=0.0, batt=0.0, eff=0.92,
                   direction="charge", e0=1000.0, settings=None):
    """A session ticking the SoC by 1% each step, with the inverter's AC side at `eff`."""
    now, soc, e = start, soc_from, e0
    sign = 1 if direction == "charge" else -1
    car_kw = kwh_per_pct * 3600 / step_s  # 1% per step
    ac = -(car_kw / eff) if direction == "charge" else car_kw * eff
    ac += pv - batt  # whatever solar and the home battery hand the inverter goes out too (lossless here)
    while True:
        rec.feed(Sample(now, direction, soc, e if direction == "charge" else 0.0,
                        e if direction == "discharge" else 0.0, car_kw * sign, pv, batt, ac), settings)
        if soc == soc_to:
            break
        now += step_s
        soc += sign
        e += kwh_per_pct
    rec.feed(Sample(now + 1, None, 0.0, None, None, 0.0, pv, batt, pv - batt), settings)
    return now + 1


def test_capacity_and_efficiency_from_a_clean_overnight_charge(tmp_path):
    rec = StatsRecorder(str(tmp_path))
    charge_session(rec, T0, 40, 80)  # 40% of 60 kWh, at 92% from the grid
    (sess,) = rec.sessions
    assert sess["direction"] == "charge" and sess["soc_start"] == 40 and sess["soc_end"] == 80
    assert abs(sess["capacity_kwh"] - 60.0) < 0.01  # 0.6 kWh per %
    assert sess["clean"] and abs(sess["efficiency"] - 0.92) < 0.005
    s = rec.summary(nominal_kwh=64.0, now=T0 + 3 * 3600)
    assert s["capacity_kwh"] == 60.0 and s["health_pct"] == 93.8
    assert s["charge_efficiency"]["median"] and s["discharge_efficiency"]["sessions"] == 0
    day = s["days"][-1]
    assert abs(day["car_in_kwh"] - 24.0) < 0.01  # from the charger's counter
    assert abs(day["car_loss_kwh"] - 24.0 * (1 / 0.92 - 1)) < 0.1  # ~2.1 kWh lost getting it in
    again = StatsRecorder(str(tmp_path))
    rec.save()
    assert len(StatsRecorder(str(tmp_path)).sessions) == 1 and again is not None


def test_discharge_efficiency_and_short_spans_give_no_capacity(tmp_path):
    rec = StatsRecorder(str(tmp_path))
    charge_session(rec, T0, 70, 50, direction="discharge", eff=0.9)
    charge_session(rec, T0 + 7200, 45, 50, direction="charge")  # only 5%: no capacity from it
    dis, short = rec.sessions
    assert dis["direction"] == "discharge" and abs(dis["capacity_kwh"] - 60) < 0.01
    assert abs(dis["efficiency"] - 0.9) < 0.005
    assert short["capacity_kwh"] is None and short["efficiency"]


def test_solar_and_home_battery_share_the_loss_and_spoil_a_clean_reading(tmp_path):
    rec = StatsRecorder(str(tmp_path))
    charge_session(rec, T0, 40, 60, pv=5.0)  # charging from solar as well
    (sess,) = rec.sessions
    assert not sess["clean"] and sess["efficiency"] is None
    assert sess["car_loss_kwh"] > 0  # still gets its share of the loss


def test_a_switch_from_charging_to_discharging_is_two_sessions(tmp_path):
    rec = StatsRecorder(str(tmp_path))
    rec.feed(Sample(T0, "charge", 50, 10.0, 5.0, 3, 0, 0, -3.3))
    rec.feed(Sample(T0 + 600, "charge", 51, 10.6, 5.0, 3, 0, 0, -3.3))
    rec.feed(Sample(T0 + 660, "other", 51, 10.6, 5.0, 0, 0, 0, 0))  # preparing: same session
    rec.feed(Sample(T0 + 700, "discharge", 51, 10.6, 5.0, -3, 0, 0, 2.7))
    rec.feed(Sample(T0 + 1300, "discharge", 50, 10.6, 5.6, -3, 0, 0, 2.7))
    rec.feed(Sample(T0 + 1400, None, 0, 10.6, 5.6, 0, 0, 0, 0))
    assert [(s["direction"], s["energy_kwh"]) for s in rec.sessions] == [("charge", 0.6), ("discharge", 0.6)]


def test_capacity_trend_needs_two_months(tmp_path):
    rec = StatsRecorder(str(tmp_path))
    for n in range(8):
        charge_session(rec, T0 + n * 12 * 86400, 30, 70, kwh_per_pct=0.62 - n * 0.002, e0=1000 + n * 50)
    s = rec.summary(nominal_kwh=62.0, now=T0 + 90 * 86400)
    assert s["trend"] and s["trend"]["kwh_per_year"] < 0 and s["trend"]["days"] >= 60
    assert s["estimate_count"] == 8


def test_history_is_replayed_once_and_only_before_live_recording(tmp_path):
    ent = default_settings()
    rs, soc = ent["running_state"], ent["vehicle_soc"]
    cin, cout = ent["charged_energy"], ent["discharged_energy"]
    t = T0 - 3 * 86400
    hist = {rs: [{"s": "Occupied", "lu": t}, {"s": "Charging", "lu": t + 60}, {"s": "Occupied", "lu": t + 60 * 50}],
            soc: [{"s": "0", "lu": t}] + [{"s": str(30 + n), "lu": t + 120 + n * 60} for n in range(41)],
            cin: [{"s": str(500 + n * 0.6), "lu": t + 120 + n * 60} for n in range(41)],
            cout: [{"s": "200", "lu": t}]}
    samples = samples_from_history(hist, ent, {})
    assert samples and samples[0].direction is None and any(x.direction == "charge" for x in samples)
    rec = StatsRecorder(str(tmp_path))
    rec.feed(Sample(T0, None, 0, 525, 200, 0, 0, 0, 0))  # live recording started
    assert rec.backfill(samples) == 1
    (sess,) = rec.sessions
    assert sess["source"] == "history" and abs(sess["capacity_kwh"] - 60) < 0.01 and sess["car_loss_kwh"] is None
    assert rec.backfilled and rec.backfill(samples) == 0  # already there
