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


# --- 2.53.0: your changes in an override file; each kind of supplier ------------

def _write(path, data):
    path.write_text(json.dumps(data))
    return str(path)


def test_your_changes_override_the_defaults(tmp_path):
    over = _write(tmp_path / "over.json", {"suppliers": [
        {"name": "octopus energy", "daily_limit_h": 7, "planned_attribute": "planned_slots"},
        {"name": "New Supplier", "type": "kraken", "dispatch_prefix": "binary_sensor.new_supplier_", "colour": "#123456"}],
        "saving_sessions": {"words": ["flex_event"]}})
    data = suppliers.load(override=over)
    octopus = data["suppliers"][0]
    assert octopus["name"] == "Octopus Energy" and octopus["daily_limit_h"] == 7
    assert octopus["planned_attribute"] == "planned_slots" and octopus["limit_reset"] == "12:00"  # the rest kept
    new = data["suppliers"][-1]
    assert new["name"] == "New Supplier" and new["type"] == "kraken"
    assert new["dispatch_suffix"] == "dispatching" and new["ready_entity_suffix"] == "target_time"  # the kind's names
    assert data["saving_sessions"]["words"] == ["flex_event"] and data["saving_sessions"]["prefer"] == ["power_down"]
    assert suppliers.INFO["override"] == over and suppliers.INFO["override_error"] is None


def test_broken_changes_are_left_out(tmp_path):
    for content in ("{oops", json.dumps({"suppliers": [{"name": "Octopus Energy", "daily_limit_h": 99}]}),
                    json.dumps({"suppliers": [{"name": "X", "type": "carrier_pigeon"}]}),
                    json.dumps({"suppliers": [{"name": "X", "type": "kraken"}]})):  # (no dispatch_prefix)
        path = tmp_path / "over.json"
        path.write_text(content)
        data = suppliers.load(override=str(path))
        assert data["suppliers"][0]["daily_limit_h"] == 6 and suppliers.INFO["override_error"]


def test_changes_are_read_again_when_the_file_changes(tmp_path):
    import os
    import time
    path = tmp_path / "over.json"
    old = (suppliers.OVERRIDE_PATH, suppliers.DATA, suppliers._override_seen)
    try:
        suppliers.OVERRIDE_PATH = str(path)
        suppliers.refresh(force=True)
        assert suppliers.daily_limit_min("Octopus Energy") == 360
        _write(path, {"suppliers": [{"name": "Octopus Energy", "daily_limit_h": 5}]})
        assert suppliers.refresh() is False  # (looked at most every minute)
        suppliers._override_seen = (suppliers._override_seen[0], time.monotonic() - 120)
        assert suppliers.refresh() is True and suppliers.daily_limit_min("Octopus Energy") == 300
        os.remove(path)
        suppliers._override_seen = (suppliers._override_seen[0], time.monotonic() - 120)
        assert suppliers.refresh() is True and suppliers.daily_limit_min("Octopus Energy") == 360
    finally:
        suppliers.OVERRIDE_PATH, suppliers.DATA, suppliers._override_seen = old


def test_each_supplier_has_a_kind_and_a_colour():
    assert [s["type"] for s in suppliers.all_suppliers()] == ["kraken", "kraken", "schedule_sensor"]
    assert suppliers.colours()["Octopus Energy"].startswith("#")


def test_the_example_is_written_to_your_folder(tmp_path):
    path = suppliers.write_example(str(tmp_path))
    assert path and json.loads(open(path).read())["suppliers"][0]["name"] == "Octopus Energy"
    assert suppliers.write_example(str(tmp_path / "missing")) is None


# --- signs that a supplier's integration has changed -------------------------------

def test_a_sensor_without_its_slots_is_reported():
    from src.smart_charging import check_supplier, find_dispatch_sensors
    states = [{"entity_id": "binary_sensor.octopus_energy_a1_intelligent_dispatching", "state": "off",
               "attributes": {"planned_slots": []}}]
    assert find_dispatch_sensors(states) == []
    problems = check_supplier(states)
    assert any("has no planned_dispatches attribute" in p["text"] and p["level"] == "warn" for p in problems)


def test_slots_in_another_format_are_reported():
    from src.smart_charging import check_supplier
    eid = "binary_sensor.octopus_energy_a1_intelligent_dispatching"
    states = [{"entity_id": eid, "state": "off",
               "attributes": {"planned_dispatches": [{"from": "2026-10-26T10:00:00Z", "to": "2026-10-26T11:00:00Z"}]}}]
    problems = check_supplier(states, eid)
    assert any("aren't in the format expected" in p["text"] and "from, to" in p["text"] for p in problems)


def test_an_integration_with_no_smart_charging_sensor_is_mentioned():
    from src.smart_charging import check_supplier
    states = [{"entity_id": "sensor.octopus_energy_electricity_123_current_rate", "state": "0.25", "attributes": {}}]
    problems = check_supplier(states)
    assert problems and problems[0]["level"] == "info" and "Octopus Energy" in problems[0]["text"]
    assert check_supplier([{"entity_id": "sensor.x", "state": "1", "attributes": {}}]) == []


def test_a_renamed_ready_time_entity_is_followed_from_the_defaults(tmp_path):
    from src.ready_time import target_time_ids
    old = (suppliers.OVERRIDE_PATH, suppliers.DATA)
    try:
        suppliers.OVERRIDE_PATH = _write(tmp_path / "over.json", {"suppliers": [
            {"name": "Octopus Energy", "ready_entity_suffix": "ready_by"}]})
        suppliers.refresh(force=True)
        assert target_time_ids("binary_sensor.octopus_energy_a1_intelligent_dispatching") == [
            "time.octopus_energy_a1_intelligent_ready_by", "select.octopus_energy_a1_intelligent_ready_by"]
    finally:
        suppliers.OVERRIDE_PATH, suppliers.DATA = old


# --- the page and the code don't assume a supplier ---------------------------------

def test_the_page_has_no_supplier_built_in():
    """Supplier names, colours and limits come from the supplier defaults (the page gets them
    from /api/smart_charging), not the page's code: they can then change without a new page.
    Comments and help text examples ("Octopus: 6 hours") are fine."""
    import re
    page = open("src/static/index.html", encoding="utf-8").read()
    js = "\n".join(re.findall(r"<script>(.*?)</script>", page, re.S))
    code = re.sub(r"(^|[^:\\\\])//[^\n]*", r"\1", js)  # (comments out; not "https://")
    names = [s["name"] for s in suppliers.all_suppliers()]
    for name in names:
        assert not re.search(r"""['"`]""" + re.escape(name) + r"""['"`]""", code), f"{name} built into the page"
    assert re.search(r"const SUPPLIER_COLOURS = \{\};", code), "supplier colours built into the page"
    assert not re.search(r"\b360\b", code), "a 6-hour limit built into the page"


def test_the_code_has_no_supplier_built_in():
    """Outside src/suppliers.py, src/suppliers.json and src/supplier_types/, the code
    doesn't name a supplier's entities, attributes or integration (docstrings and
    comments can, as examples)."""
    import glob
    import io
    import re
    import tokenize
    pattern = re.compile(r"octopus_energy|edf_energy|eon_next|planned_dispatches|completed_dispatches|"
                         r"target_time|intelligent_|smart_charging_schedule|charge_in_kwh")
    found = []
    for path in sorted(glob.glob("src/*.py")):
        if path.endswith("suppliers.py"):
            continue
        prev = tokenize.NEWLINE
        for tok in tokenize.generate_tokens(io.StringIO(open(path, encoding="utf-8").read()).readline):
            if tok.type == tokenize.STRING and prev not in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.NL) \
                    and pattern.search(tok.string):
                found.append(f"{path}:{tok.start[0]} {tok.string[:60]}")
            if tok.type not in (tokenize.COMMENT, tokenize.NL):
                prev = tok.type
    assert found == []
