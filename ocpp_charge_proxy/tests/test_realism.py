"""Things that would show the charger isn't a real one."""
from pathlib import Path

from src.charger_sim import ChargerSimulator


def test_power_reads_to_the_watt_not_whole_tens():
    sim = ChargerSimulator(current_amps=6)
    sim.start_charging()
    watts = [round(sim.sample_full().power_kw * 1000) for _ in range(200)]
    assert any(w % 10 for w in watts)  # not always 1450, 1490, 1500...


def test_no_python_user_agent_on_the_connection():
    main = (Path(__file__).parent.parent / "src" / "__main__.py").read_text(encoding="utf-8")
    assert '_NO_USER_AGENT["user_agent_header"] = None' in main and "**_NO_USER_AGENT" in main
