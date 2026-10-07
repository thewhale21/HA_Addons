"""src/suppliers.json: each supplier's defaults, editable without code changes."""

import json

from src import suppliers


def test_the_shipped_file_loads():
    data = suppliers.load()
    names = [s["name"] for s in data["suppliers"]]
    assert names[:3] == ["Octopus Energy", "EDF Energy", "E.ON Next"]
    octopus = suppliers.by_name("Octopus Energy")
    assert octopus["daily_limit_h"] == 6 and octopus["limit_reset"] == "12:00"
    assert len(suppliers.ready_times(octopus)) == 48
    assert suppliers.ready_times(suppliers.by_name("EDF Energy"))[0] == "04:00"
    assert suppliers.daily_limit_min("Octopus Energy") == 360 and suppliers.daily_limit_min("EDF Energy") is None
    assert suppliers.limit_reset("Someone new") == "rolling"


def test_entities_are_matched_to_their_supplier():
    assert suppliers.for_entity("binary_sensor.octopus_energy_x_intelligent_dispatching")["name"] == "Octopus Energy"
    assert suppliers.for_entity("time.edf_energy_x_intelligent_target_time")["name"] == "EDF Energy"
    assert suppliers.for_entity("sensor.abc_smart_charging_schedule")["name"] == "E.ON Next"
    assert suppliers.for_entity("binary_sensor.other_dispatching")["name"] == "Your supplier"


def test_an_edited_file_changes_the_defaults(tmp_path):
    path = tmp_path / "suppliers.json"
    path.write_text(json.dumps({"suppliers": [
        {"name": "Octopus Energy", "dispatch_prefix": "binary_sensor.octopus_energy_",
         "ready_times": {"from": "00:00", "to": "23:30"}, "daily_limit_h": 8, "limit_reset": "00:00"}]}))
    data = suppliers.load(str(path))
    assert data["suppliers"][0]["daily_limit_h"] == 8 and data["suppliers"][0]["limit_reset"] == "00:00"
    assert data["other"]["name"] == "Your supplier"


def test_a_broken_file_falls_back_to_the_built_in_defaults(tmp_path):
    for content in ("{not json", json.dumps({"suppliers": [{"name": "X", "daily_limit_h": 30}]}),
                    json.dumps({"suppliers": [{"name": "X", "ready_times": {"from": "11:00", "to": "04:00"}}]}),
                    json.dumps({"nothing": []})):
        path = tmp_path / "bad.json"
        path.write_text(content)
        data = suppliers.load(str(path))
        assert data["suppliers"][0]["name"] == "Octopus Energy" and data["suppliers"][0]["daily_limit_h"] == 6
    assert suppliers.load(str(tmp_path / "missing.json"))["suppliers"][0]["name"] == "Octopus Energy"
