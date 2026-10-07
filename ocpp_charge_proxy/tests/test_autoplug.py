"""Auto plug-in decision logic (no Home Assistant needed)."""

from src.autoplug import AutoPlug, CarConnected


def _run(auto_plug, readings):
    plugged, fired = False, []
    for soc, action in readings:
        if action == "unplug":
            plugged = False
        fire = auto_plug.should_plug(soc, plugged)
        plugged = plugged or fire
        fired.append(fire)
    return fired


def test_fires_once_when_soc_drops_below_threshold():
    assert _run(AutoPlug(True, 30), [(40, None), (31, None), (29, None), (20, None)]) == [False, False, True, False]


def test_no_replug_after_manual_unplug_until_recovered():
    readings = [(40, None), (29, None), (25, "unplug"), (20, None), (35, None), (28, None)]
    assert _run(AutoPlug(True, 30), readings) == [False, True, False, False, False, True]


def test_low_first_reading_does_not_fire():
    assert _run(AutoPlug(True, 30), [(20, None), (15, None)]) == [False, False]


def test_disabled_or_unknown_soc_never_fires():
    assert _run(AutoPlug(False, 30), [(40, None), (20, None)]) == [False, False]
    assert _run(AutoPlug(True, 30), [(None, None), (20, None)]) == [False, False]


def _follow(readings):
    car, plugged, fired = CarConnected(), False, []
    for state, action in readings:
        if action == "unplug":
            plugged = False
        fire = car.should_plug(state, plugged)
        plugged = plugged or fire
        fired.append(fire)
    return fired


def test_car_connected_plugs_on_off_to_on_only():
    assert _follow([("off", None), ("on", None), ("on", None)]) == [False, True, False]


def test_car_connected_first_reading_on_does_not_plug():
    assert _follow([("on", None), ("on", None)]) == [False, False]


def test_car_connected_manual_unplug_not_undone():
    # plugged in by the sensor, unplugged by hand while the cable is still in
    assert _follow([("off", None), ("on", None), ("on", "unplug"), ("on", None)]) == [False, True, False, False]


def test_car_connected_ignores_unavailable_between():
    assert _follow([("off", None), ("unavailable", None), ("on", None)]) == [False, False, True]
    assert _follow([("on", None), ("unavailable", None), ("on", None)]) == [False, False, False]


def test_car_connected_never_unplugs_and_skips_if_plugged():
    car = CarConnected()
    car.should_plug("off", True)
    assert car.should_plug("on", True) is False  # already plugged in
