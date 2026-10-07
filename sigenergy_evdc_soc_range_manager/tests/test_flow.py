"""The power flow diagram's sums (src/flow.py)."""

from src.flow import flows, house_load


def test_solar_feeds_the_house_then_the_battery_then_the_grid():
    f = flows(pv=6.0, grid=-1.0, batt=2.0, car=0.0, house=3.0)
    assert f == {"solar_house": 3.0, "solar_battery": 2.0, "solar_grid": 1.0}


def test_the_car_discharging_covers_the_house_and_exports_the_rest():
    f = flows(pv=0.0, grid=-1.5, batt=0.0, car=-3.0, house=1.5)
    assert f == {"house_grid": 1.5}  # the house side had 1.5 kW spare


def test_night_import_charges_the_car_and_the_battery():
    f = flows(pv=0.0, grid=10.0, batt=3.0, car=6.5, house=0.5)
    assert f == {"grid_house": 7.0, "grid_battery": 3.0}


def test_house_load_from_the_balance_when_not_measured():
    assert house_load(5.0, -1.0, 2.0, 0.0) == 2.0
    assert house_load(0.0, 0.2, -1.0, -3.0) == 4.2  # battery and car discharging into the house
    assert house_load(1.0, 0.0, 0.0, 0.0, measured=0.4) == 0.4
    assert house_load(None, 0.0, 0.0, 0.0) is None
