from src.persistence import Persistence


def test_load_energy_register_default(tmp_path):
    p = Persistence(data_dir=str(tmp_path))
    assert p.load_energy_register_wh() == 0


def test_save_and_load_energy_register(tmp_path):
    p = Persistence(data_dir=str(tmp_path))
    p.save_energy_register_wh(12345)
    assert p.load_energy_register_wh() == 12345


def test_load_corrupt_file_returns_default(tmp_path):
    p = Persistence(data_dir=str(tmp_path))
    path = tmp_path / "energy_register.json"
    path.write_text("not json{{{")
    assert p.load_energy_register_wh() == 0


def test_serial_number_generated_and_persisted(tmp_path):
    p = Persistence(data_dir=str(tmp_path))
    serial = p.load_serial_number()
    assert len(serial) == 6
    assert serial.isdigit()
    # Second call returns same value
    assert p.load_serial_number() == serial


def test_seed_energy_register_applies_when_higher(tmp_path):
    p = Persistence(data_dir=str(tmp_path))
    p.save_energy_register_wh(1000)
    assert p.seed_energy_register_wh(6582198) is True
    assert p.load_energy_register_wh() == 6582198


def test_seed_energy_register_ignored_when_lower_or_equal(tmp_path):
    """A stale seed must never move the meter backwards."""
    p = Persistence(data_dir=str(tmp_path))
    p.save_energy_register_wh(6583000)
    assert p.seed_energy_register_wh(6582198) is False
    assert p.seed_energy_register_wh(6583000) is False
    assert p.load_energy_register_wh() == 6583000


def test_seed_energy_register_on_fresh_install(tmp_path):
    p = Persistence(data_dir=str(tmp_path))
    assert p.seed_energy_register_wh(500) is True
    assert p.load_energy_register_wh() == 500


def test_offline_queue_round_trip(tmp_path):
    p = Persistence(data_dir=str(tmp_path))
    assert p.load_offline_queue() == []
    p.save_offline_queue([{"seq": 1, "action": "StopTransactionPayload", "payload": {"meter_stop": 1}}])
    assert Persistence(data_dir=str(tmp_path)).load_offline_queue()[0]["payload"]["meter_stop"] == 1


def test_active_transaction_round_trip(tmp_path):
    p = Persistence(data_dir=str(tmp_path))
    assert p.load_active_transaction() is None
    p.save_active_transaction({"transaction_id": 7, "energy_wh": 100})
    assert Persistence(data_dir=str(tmp_path)).load_active_transaction()["transaction_id"] == 7
    p.save_active_transaction(None)
    assert p.load_active_transaction() is None


# --- 0.9.4: crash-safe writes ---


def test_write_is_atomic_and_keeps_backup(tmp_path):
    p = Persistence(data_dir=str(tmp_path))
    p.save_energy_register_wh(1000)
    assert not (tmp_path / "energy_register.json.tmp").exists()
    assert not (tmp_path / "energy_register.json.bak").exists()  # nothing to back up yet
    p.save_energy_register_wh(2000)
    assert p.load_energy_register_wh() == 2000
    assert '"energy_wh": 1000' in (tmp_path / "energy_register.json.bak").read_text()


def test_corrupt_register_falls_back_to_backup_not_zero(tmp_path):
    """A power cut mid-write must never reset the meter to 0."""
    p = Persistence(data_dir=str(tmp_path))
    p.save_energy_register_wh(6612327)
    p.save_energy_register_wh(6612437)
    (tmp_path / "energy_register.json").write_text('{"energy_wh": 66')  # torn write
    assert Persistence(data_dir=str(tmp_path)).load_energy_register_wh() == 6612327


def test_missing_main_file_uses_backup(tmp_path):
    p = Persistence(data_dir=str(tmp_path))
    p.save_energy_register_wh(10)
    p.save_energy_register_wh(20)
    (tmp_path / "energy_register.json").unlink()
    assert p.load_energy_register_wh() == 10


def test_corrupt_main_never_overwrites_good_backup(tmp_path):
    p = Persistence(data_dir=str(tmp_path))
    p.save_energy_register_wh(10)
    p.save_energy_register_wh(20)  # backup = 10
    (tmp_path / "energy_register.json").write_text("garbage")
    p.save_energy_register_wh(30)
    assert '"energy_wh": 10' in (tmp_path / "energy_register.json.bak").read_text()
    assert p.load_energy_register_wh() == 30


def test_plugged_in_round_trip(tmp_path):
    p = Persistence(data_dir=str(tmp_path))
    assert p.load_plugged_in() is False
    p.save_plugged_in(True)
    assert Persistence(data_dir=str(tmp_path)).load_plugged_in() is True
    p.save_plugged_in(False)
    assert p.load_plugged_in() is False
