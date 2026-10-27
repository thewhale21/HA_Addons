"""src/migrate.py: moving the settings (and history) to another install."""

import asyncio
import json
import os

import pytest

from src import migrate


def _old_install(path):
    path.mkdir()
    files = {
        "options.json": {"server_hostname": "ocpp.octopus.energy", "chargepoint_id": "CP123", "password": "secret",
                         "charger_model": "PLP2", "charger_vendor": "Wallbox", "charger_serial": "654321",
                         "firmware_version": "6.11.16", "initial_energy_wh": 0},
        "automation.json": {"schedule": {"enabled": True, "entries": [{"time": "23:30", "action": "plug"}]}},
        "sensors.json": {"soc_entity": "sensor.car_soc"},
        "settings.json": {"settings": {"log_level": "info"}},
        "serial_number.json": {"serial": "654321"},
        "energy_register.json": {"energy_wh": 5000000},
        "sessions.json": {"history": [{"start": "2026-10-20T23:30:00Z"}]},
        "messages.json": {"last_seq": 3, "messages": []},
        "active_transaction.json": {"transaction": {"id": 1}},  # only for the moment: not moved
    }
    for name, data in files.items():
        (path / name).write_text(json.dumps(data))
    return str(path)


def test_everything_moves_to_a_new_install(tmp_path):
    old = _old_install(tmp_path / "old")
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "suppliers.json").write_text(json.dumps({"suppliers": [{"name": "Octopus Energy", "daily_limit_h": 7}]}))
    bundle = json.loads(json.dumps(migrate.export(old, "2.53.2", suppliers_path=str(tmp_path / "cfg" / "suppliers.json"))))
    assert bundle["options"]["password"] == "secret" and "initial_energy_wh" not in bundle["options"]
    assert "active_transaction.json" not in bundle["files"] and "sessions.json" in bundle["files"]
    info = migrate.check(bundle)
    assert info["energy_wh"] == 5000000 and info["serial"] == "654321" and info["with_history"]
    assert any("Configuration tab" in i for i in info["items"]) and any("supplier changes" in i for i in info["items"])

    new = tmp_path / "new"
    new.mkdir()
    (new / "energy_register.json").write_text(json.dumps({"energy_wh": 10}))
    migrate.stage(str(new), bundle)
    done = migrate.apply_pending(str(new), str(tmp_path / "newcfg" / "suppliers.json"))  # (no folder: left out)
    assert done and done[0].startswith("imported")
    assert json.load(open(new / "automation.json"))["schedule"]["entries"][0]["time"] == "23:30"
    assert json.load(open(new / "energy_register.json")) == {"energy_wh": 5000000}
    assert json.load(open(new / "sessions.json"))["history"]
    assert not os.path.exists(new / migrate.PENDING) and os.path.exists(new / "import_done.json")
    assert migrate.apply_pending(str(new)) == []  # only once


def test_the_energy_register_never_goes_backwards(tmp_path):
    bundle = migrate.export(_old_install(tmp_path / "old"), "2.53.2")
    new = tmp_path / "new"
    new.mkdir()
    (new / "energy_register.json").write_text(json.dumps({"energy_wh": 9000000}))
    migrate.stage(str(new), bundle)
    done = migrate.apply_pending(str(new))
    assert json.load(open(new / "energy_register.json")) == {"energy_wh": 9000000}
    assert any("kept this install's energy register" in d for d in done)


def test_without_the_history_or_the_password(tmp_path):
    bundle = migrate.export(_old_install(tmp_path / "old"), "2.53.2", history=False, password=False)
    assert "sessions.json" not in bundle["files"] and "messages.json" not in bundle["files"]
    assert "password" not in bundle["options"] and not migrate.check(bundle)["with_password"]
    # the password already set here is kept
    assert migrate.options_after({"password": "mine", "chargepoint_id": "old"}, bundle)["password"] == "mine"


def test_other_files_are_refused(tmp_path):
    good = migrate.export(_old_install(tmp_path / "old"), "2.53.2")
    for bad in ({}, [], {"format": "something_else"}, {**good, "format_version": 99},
                {**good, "files": {"evil.json": {}}}, {**good, "files": {"sessions.json": "x"}},
                {**good, "options": {"server_hostname": {"x": 1}}}, {**good, "options": {"other": "x"}}):
        with pytest.raises(ValueError):
            migrate.check(bad)
    (tmp_path / "new").mkdir()
    with pytest.raises(ValueError):
        migrate.stage(str(tmp_path / "new"), {"format": "nope"})
    assert not os.path.exists(tmp_path / "new" / migrate.PENDING)


def test_a_broken_staged_file_changes_nothing(tmp_path):
    (tmp_path / migrate.PENDING).write_text("{oops")
    (tmp_path / "automation.json").write_text(json.dumps({"schedule": {}}))
    done = migrate.apply_pending(str(tmp_path))
    assert "nothing was changed" in done[0] and json.load(open(tmp_path / "automation.json")) == {"schedule": {}}


def test_importing_sets_the_options_and_restarts(tmp_path):
    bundle = migrate.export(_old_install(tmp_path / "old"), "2.53.2")
    new = tmp_path / "new"
    new.mkdir()
    (new / "options.json").write_text(json.dumps({"server_hostname": "", "chargepoint_id": "", "password": "",
                                                  "initial_energy_wh": 1234}))
    calls, restarted = [], []

    async def supervisor(method, path, body=None):
        calls.append((method, path, body))
        if path == "/addons/self/info":
            return {"slug": "abc123_ocpp_charge_proxy"}
        if path == "/addons":
            return {"addons": [{"slug": "abc123_ocpp_charge_proxy", "state": "started"},
                               {"slug": "def456_ocpp_charge_proxy", "name": "OCPP Charge Proxy (old)", "state": "started"}]}
        return {}

    async def restart():
        restarted.append(True)
        return {"restarting": True}

    mover = migrate.Mover(str(new), "2.54.0", supervisor, restart)
    checked = asyncio.run(mover.check(bundle))
    assert any("OCPP Charge Proxy (old) is still running" in w for w in checked["warnings"])
    assert asyncio.run(mover.import_now(bundle)) == {"restarting": True} and restarted
    sent = [b for m, p, b in calls if p == "/addons/self/options"][0]["options"]
    assert sent["chargepoint_id"] == "CP123" and sent["password"] == "secret" and sent["initial_energy_wh"] == 0
    assert os.path.exists(new / migrate.PENDING)


def test_if_home_assistant_refuses_the_options_nothing_changes(tmp_path):
    bundle = migrate.export(_old_install(tmp_path / "old"), "2.53.2")
    new = tmp_path / "new"
    new.mkdir()

    async def supervisor(method, path, body=None):
        raise RuntimeError("no")

    async def restart():
        raise AssertionError("not restarted")

    with pytest.raises(ValueError, match="nothing was changed"):
        asyncio.run(migrate.Mover(str(new), "2.54.0", supervisor, restart).import_now(bundle))
    assert not os.path.exists(new / migrate.PENDING)


def test_the_serial_from_the_configuration_tab_replaces_a_made_up_one(tmp_path):
    old = _old_install(tmp_path / "old")
    os.remove(os.path.join(old, "serial_number.json"))  # (entered on the Configuration tab only)
    bundle = migrate.export(old, "2.54.0")
    new = tmp_path / "new"
    new.mkdir()
    (new / "serial_number.json").write_text(json.dumps({"serial": "535252"}))  # made up on its first start
    migrate.stage(str(new), bundle)
    migrate.apply_pending(str(new))
    assert json.load(open(new / "serial_number.json")) == {"serial": "654321"}


def test_not_while_a_session_is_going(tmp_path):
    """Its meter readings (the energy register, the session so far) would be split between installs."""
    old = _old_install(tmp_path / "old")
    going = {"now": True}

    async def supervisor(method, path, body=None):
        return {}

    async def restart():
        return {}

    mover = migrate.Mover(old, "2.54.2", supervisor, restart, in_session=lambda: going["now"])
    with pytest.raises(ValueError, match="in progress"):
        mover.export(history=True, password=True)
    bundle = migrate.export(old, "2.54.2")
    with pytest.raises(ValueError, match="in progress"):
        asyncio.run(mover.check(bundle))
    with pytest.raises(ValueError, match="in progress"):
        asyncio.run(mover.import_now(bundle))
    assert not os.path.exists(os.path.join(old, migrate.PENDING))
    going["now"] = False
    assert mover.export(history=True, password=True)["files"]
