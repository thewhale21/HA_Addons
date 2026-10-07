"""The SoC chart's points (src/soc_history.py)."""

from src.soc_history import KEEP_S, STEP_S, SocHistory


def test_points_on_change_and_every_few_minutes(tmp_path):
    h = SocHistory(str(tmp_path))
    h.add(1000, 60, 80, 40, "idle")
    h.add(1010, 60, 80, 40, "idle")  # nothing changed
    h.add(1020, 60, 80, 40, "discharge")  # the charger started
    h.add(1020 + STEP_S, 60, 80, 40, "discharge")  # a while on: kept anyway
    h.add(1030 + STEP_S, 59, 80, 40, "discharge")
    assert [p[0] for p in h.points] == [1000, 1020, 1020 + STEP_S, 1030 + STEP_S]
    h.save()
    assert SocHistory(str(tmp_path)).points == h.points


def test_old_points_go_and_history_fills_in_before(tmp_path):
    h = SocHistory(str(tmp_path))
    h.add(0, 50, 80, 40, "idle")
    h.add(KEEP_S + 100, 55, 80, 40, "idle")
    assert [p[0] for p in h.points] == [KEEP_S + 100]
    assert h.backfill([[KEEP_S, 54, None, None, "idle"], [KEEP_S + 200, 99, None, None, "idle"]]) == 1
    assert [p[0] for p in h.points] == [KEEP_S, KEEP_S + 100] and h.backfilled


def test_a_window_starts_with_where_the_line_was(tmp_path):
    h = SocHistory(str(tmp_path))
    h.add(1000, 50, 80, 40, "idle")
    h.add(9000, 52, 80, 40, "charge")
    w = h.window(1, 10000)  # the last hour: from 6400
    assert w[0] == [6400, 50, 80, 40, "idle"] and w[1][0] == 9000


def test_points_from_home_assistants_history():
    from src.ha_link import default_settings
    from src.manager import soc_points_from_history

    ent = default_settings()
    rs, soc = ent["running_state"], ent["vehicle_soc"]
    hist = {rs: [{"s": "Idle", "lu": 0}, {"s": "Occupied", "lu": 100}, {"s": "Discharging", "lu": 200}, {"s": "Occupied", "lu": 900}],
            soc: [{"s": "0", "lu": 0}, {"s": "62", "lu": 210}, {"s": "60", "lu": 800}, {"s": "0", "lu": 910}]}
    pts = soc_points_from_history(hist, ent, {})
    assert [(p[0], p[1], p[4]) for p in pts] == [(210, 62, "discharge"), (800, 60, "discharge"), (900, 60, "idle")]


def test_alarms_recorded_as_unplugged_are_put_right_once(tmp_path):
    h = SocHistory(str(tmp_path))
    h.add(1000, 60, 80, 40, "idle")
    h.add(1005, 60, 80, 40, "unplugged")  # really an alarm (seen a few seconds after HA)
    h.add(2000, 60, 80, 40, "idle")
    h.add(3000, 60, None, None, "unplugged")  # really unplugged
    hist = [[990, 60, None, None, "idle"], [1001, 60, None, None, "alarm"], [1999, 60, None, None, "idle"],
            [2999, 60, None, None, "unplugged"]]
    assert h.fix_alarms(hist) == 1
    assert [p[4] for p in h.points] == ["idle", "alarm", "idle", "unplugged"]
    assert SocHistory(str(tmp_path)).alarms_fixed


def test_the_integrations_alarm_state_is_an_alarm_not_unplugged():
    from src.manager import LIST_DEFAULTS, _in, soc_state

    lists = LIST_DEFAULTS
    for running in ("Alarm", "Fault"):
        assert _in(running, lists["alarm_states"]) and not _in(running, lists["plugged_states"])
        assert soc_state(False, False, running, False, True) == "alarm"
