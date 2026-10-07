from src.charger_sim import ChargerReading
from src.meter_values import build_charging_meter_values, build_idle_meter_values


def _make_reading(**kwargs) -> ChargerReading:
    defaults = dict(
        power_kw=7.27, voltage=230.0, current_a=31.61,
        frequency_hz=50.01, power_offered_kw=7.4, current_offered_a=32,
    )
    defaults.update(kwargs)
    return ChargerReading(**defaults)


def test_idle_meter_values_single_entry():
    mv = build_idle_meter_values(energy_register_wh=10500)
    assert len(mv) == 1


def test_idle_meter_values_has_four_measurands():
    mv = build_idle_meter_values(energy_register_wh=10500)
    measurands = {sv["measurand"] for sv in mv[0]["sampledValue"]}
    assert measurands == {
        "Power.Active.Import", "Power.Active.Export",
        "Energy.Active.Import.Register", "Energy.Active.Export.Register",
    }


def test_idle_power_is_zero():
    mv = build_idle_meter_values(energy_register_wh=10500)
    power_sv = [sv for sv in mv[0]["sampledValue"] if sv["measurand"] == "Power.Active.Import"][0]
    assert power_sv["value"] == "0.0"
    assert power_sv["unit"] == "W"


def test_idle_export_is_zero():
    mv = build_idle_meter_values(energy_register_wh=10500)
    export_sv = [sv for sv in mv[0]["sampledValue"] if sv["measurand"] == "Power.Active.Export"][0]
    assert float(export_sv["value"]) == 0.0
    assert export_sv["unit"] == "W"
    export_energy_sv = [sv for sv in mv[0]["sampledValue"] if sv["measurand"] == "Energy.Active.Export.Register"][0]
    assert float(export_energy_sv["value"]) == 0.0
    assert export_energy_sv["unit"] == "Wh"


def test_idle_energy_register():
    mv = build_idle_meter_values(energy_register_wh=10500)
    energy_sv = [sv for sv in mv[0]["sampledValue"] if sv["measurand"] == "Energy.Active.Import.Register"][0]
    assert energy_sv["value"] == "10500.0"
    assert energy_sv["unit"] == "Wh"


def test_idle_meter_values_have_metadata():
    mv = build_idle_meter_values(energy_register_wh=10500)
    for sv in mv[0]["sampledValue"]:
        assert sv["format"] == "Raw"
        assert sv["location"] == "Outlet"
        assert sv["context"] == "Sample.Periodic"


def test_charging_meter_values_single_entry():
    mv = build_charging_meter_values(
        reading=_make_reading(), energy_register_wh=10500,
    )
    assert len(mv) == 1


def test_charging_meter_values_has_seven_measurands():
    """Real Wallbox reports 7 measurands (no SoC)."""
    mv = build_charging_meter_values(
        reading=_make_reading(), energy_register_wh=10500,
    )
    measurands = {sv["measurand"] for sv in mv[0]["sampledValue"]}
    assert measurands == {
        "Power.Active.Import", "Power.Active.Export",
        "Frequency", "Current.Offered", "Power.Offered",
        "Energy.Active.Import.Register", "Energy.Active.Export.Register",
    }


def test_charging_uses_reading_values():
    reading = _make_reading(power_kw=7.25, current_a=31.52, frequency_hz=50.03)
    mv = build_charging_meter_values(
        reading=reading, energy_register_wh=10500,
    )
    samples = {sv["measurand"]: sv["value"] for sv in mv[0]["sampledValue"]}
    assert samples["Power.Active.Import"] == "7250.0"  # W not kW
    assert samples["Current.Offered"] == "32"
    assert samples["Frequency"] == "50.03"
    assert samples["Power.Offered"] == "7400"  # W not kW


def test_charging_units_are_watts():
    mv = build_charging_meter_values(
        reading=_make_reading(), energy_register_wh=10500,
    )
    samples = {sv["measurand"]: sv for sv in mv[0]["sampledValue"]}
    assert samples["Power.Active.Import"]["unit"] == "W"
    assert samples["Power.Active.Export"]["unit"] == "W"
    assert samples["Power.Offered"]["unit"] == "W"
    assert samples["Energy.Active.Import.Register"]["unit"] == "Wh"
    assert samples["Energy.Active.Export.Register"]["unit"] == "Wh"
    assert samples["Current.Offered"]["unit"] == "A"


def test_charging_export_is_zero():
    mv = build_charging_meter_values(
        reading=_make_reading(), energy_register_wh=10500,
    )
    samples = {sv["measurand"]: sv["value"] for sv in mv[0]["sampledValue"]}
    assert samples["Power.Active.Export"] == "0"
    assert samples["Energy.Active.Export.Register"] == "0"


def test_charging_meter_values_have_metadata():
    mv = build_charging_meter_values(
        reading=_make_reading(), energy_register_wh=10500,
    )
    for sv in mv[0]["sampledValue"]:
        assert sv["format"] == "Raw"
        assert sv["location"] == "Outlet"
        assert sv["context"] == "Sample.Periodic"


def test_charger_sim_steady_state():
    from src.charger_sim import ChargerSimulator
    sim = ChargerSimulator()
    sim.start_charging()
    readings = [sim.sample().power_kw for _ in range(100)]
    assert all(0.1 <= r <= 7.5 for r in readings)
    mean = sum(readings) / len(readings)
    assert 7.15 <= mean <= 7.40  # should cluster around 7.27


def test_charger_sim_idle():
    from src.charger_sim import ChargerSimulator
    sim = ChargerSimulator()
    reading = sim.sample()
    assert reading.power_kw == 0.0
    assert reading.current_a == 0.0
    assert reading.power_offered_kw == 0.0


# --- Clock-aligned / filtered meter values ---

from src.meter_values import build_meter_values


def test_build_meter_values_filters_and_orders():
    mv = build_meter_values(
        reading=_make_reading(), energy_register_wh=10500, context="Sample.Clock",
        measurands=["Power.Active.Import", "Energy.Active.Import.Register"],
    )
    svs = mv[0]["sampledValue"]
    assert [sv["measurand"] for sv in svs] == [
        "Power.Active.Import", "Energy.Active.Import.Register",
    ]
    assert all(sv["context"] == "Sample.Clock" for sv in svs)


def test_build_meter_values_skips_unavailable():
    """SoC has no source; Frequency isn't available while idle."""
    mv = build_meter_values(
        reading=None, energy_register_wh=10500, context="Sample.Clock",
        measurands=["Energy.Active.Import.Register", "SoC", "Frequency"],
    )
    assert [sv["measurand"] for sv in mv[0]["sampledValue"]] == [
        "Energy.Active.Import.Register",
    ]


def test_build_meter_values_default_measurand():
    mv = build_meter_values(
        reading=None, energy_register_wh=10500, context="Sample.Clock", measurands=[],
    )
    svs = mv[0]["sampledValue"]
    assert len(svs) == 1
    assert svs[0]["measurand"] == "Energy.Active.Import.Register"
    assert svs[0]["value"] == "10500.0"


def test_build_meter_values_uses_given_timestamp():
    mv = build_meter_values(
        reading=None, energy_register_wh=1, context="Sample.Clock",
        timestamp="2026-10-01T15:15:00Z",
    )
    assert mv[0]["timestamp"] == "2026-10-01T15:15:00Z"

# --- Start delay / ramp-up ---


class _FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def _ramp_sim(clock, delay=3.0, ramp=5.0):
    from src.charger_sim import ChargerSimulator
    return ChargerSimulator(current_amps=32, start_delay_s=delay, ramp_up_s=ramp, clock=clock)


def test_charger_sim_no_power_during_start_delay():
    clock = _FakeClock()
    sim = _ramp_sim(clock)
    sim.start_charging()
    clock.t += 2.9
    reading = sim.sample()
    assert reading.power_kw == 0.0
    assert reading.current_a == 0.0
    assert reading.power_offered_kw > 0  # charger is offering, car not drawing yet


def test_charger_sim_ramps_linearly_then_full():
    clock = _FakeClock()
    sim = _ramp_sim(clock)
    sim.start_charging()
    clock.t += 3.0 + 2.5  # halfway through the ramp
    assert sim.ramp_factor() == 0.5
    mid = [sim.sample().power_kw for _ in range(100)]
    assert 3.4 <= sum(mid) / len(mid) <= 3.9
    clock.t += 10
    assert sim.ramp_factor() == 1.0
    full = [sim.sample().power_kw for _ in range(100)]
    assert 7.15 <= sum(full) / len(full) <= 7.40


def test_charger_sim_average_ramp_factor():
    clock = _FakeClock(0.0)
    sim = _ramp_sim(clock)
    sim.start_charging()
    # Delay only -> 0; delay+ramp (8s) -> area 2.5s; 60s -> area 2.5 + 52
    assert sim.average_ramp_factor(0.0, 3.0) == 0.0
    assert abs(sim.average_ramp_factor(0.0, 8.0) - 2.5 / 8) < 1e-9
    assert abs(sim.average_ramp_factor(0.0, 60.0) - 54.5 / 60) < 1e-9
    assert sim.average_ramp_factor(100.0, 160.0) == 1.0


def test_charger_sim_restart_repeats_delay_but_not_while_charging():
    clock = _FakeClock()
    sim = _ramp_sim(clock)
    sim.start_charging()
    clock.t += 20
    sim.start_charging()  # already charging: no reset
    assert sim.ramp_factor() == 1.0
    sim.stop_charging()
    sim.start_charging()  # resume after pause: delay again
    assert sim.ramp_factor() == 0.0


def test_charger_sim_zero_delay_and_ramp_is_instant():
    clock = _FakeClock()
    sim = _ramp_sim(clock, delay=0, ramp=0)
    sim.start_charging()
    assert sim.ramp_factor() == 1.0
    assert sim.sample().power_kw > 6.5


# --- 0.9.4: SoC ---


def test_soc_reported_when_requested_and_known():
    mv = build_meter_values(
        reading=_make_reading(), energy_register_wh=1, context="Sample.Periodic",
        measurands=["Energy.Active.Import.Register", "SoC"], soc=79.6,
    )
    soc = [sv for sv in mv[0]["sampledValue"] if sv["measurand"] == "SoC"][0]
    assert soc["value"] == "80"
    assert soc["unit"] == "Percent"
    assert soc["location"] == "EV"


def test_soc_skipped_without_value():
    mv = build_meter_values(
        reading=_make_reading(), energy_register_wh=1, context="Sample.Periodic",
        measurands=["Energy.Active.Import.Register", "SoC"],
    )
    assert [sv["measurand"] for sv in mv[0]["sampledValue"]] == ["Energy.Active.Import.Register"]
