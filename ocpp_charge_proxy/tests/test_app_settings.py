import logging

from src.app_settings import AppSettings
from src.config import starting_current_amps
from src.persistence import Persistence


def test_defaults_saved_and_reloaded(tmp_path):
    p = Persistence(data_dir=str(tmp_path))
    s = AppSettings(p)
    assert s.log_level == "info" and s.continue_session is True
    seen = []
    s.on_change = seen.append
    assert s.update({"continue_session": False, "log_level": "DEBUG"}) == {"log_level": "debug", "continue_session": False}
    assert seen == [{"log_level": "debug", "continue_session": False}]
    again = AppSettings(Persistence(data_dir=str(tmp_path)))
    assert again.log_level == "debug" and again.continue_session is False
    for bad in ({"log_level": "loud"}, {"continue_session": "yes"}, {}, []):
        try:
            s.update(bad)
            raise AssertionError("should have refused %r" % (bad,))
        except ValueError:
            pass


def test_log_level_applied():
    root = logging.getLogger()
    old = root.level
    try:
        s = AppSettings()
        s.update({"log_level": "warning"})
        s.apply_log_level()
        assert root.level == logging.WARNING
    finally:
        root.setLevel(old)


def test_max_current_kept_from_the_web_page(tmp_path):
    from src.client import ChargePoint
    p = Persistence(data_dir=str(tmp_path))
    assert starting_current_amps(p) == 32  # fresh install
    cp = ChargePoint(id="CP", connection=None, persistence=p, current_amps=32)
    cp.set_max_current(16)
    assert starting_current_amps(p) == 16  # restart: kept
    p.save_current_setting({"amps": 99})
    assert starting_current_amps(p) == 32  # not a valid setting
