# SigEnergy EVDC SoC Range Manager

Keeps your car's state of charge (SoC) between a low and a high limit while
a Sigenergy DC charger (EVDC) is in V2X mode. It does this by pressing the
charger's **Start** and **Stop** buttons. Once the charger is started,
Sigenergy decides whether the car charges or discharges; this add-on only
decides when it may run.

## What it does

It only acts while the car is plugged in, the V2X mode entity says V2X (or
is on) and the car's SoC is known. Then, in this order:

| | When | It |
| --- | --- | --- |
| 1 | The house needs power (home battery discharging, or importing from the grid) and the car is above the low limit | starts the charger, so the car can discharge |
| 2 | There's spare power (exporting for 10 s, or a charge signal such as Predbat charging) and the car is below the high limit | starts the charger, so the car can charge |
| 3 | The car is at or above the high limit, isn't discharging and the house doesn't need power | stops the charger |
| 4 | The car is at or below the low limit and is discharging (and no charge signal is on) | stops the charger |
| 5 | The car is between the limits | starts the charger |

So between the limits the charger always runs. At the high limit it only
runs to discharge, and at the low limit only to charge.

After the charger stops, for whatever reason, it isn't started again for
the **restart wait** (3 minutes). Some cars stop discharging now and then;
this stops the add-on restarting it over and over. It also never presses a
button within a minute of the last press.

It looks whenever one of your entities changes, and every few seconds anyway.

## Getting started

1. Install the add-on and start it, then open it from the sidebar.
2. **Settings** shows the entities it uses. They start as the Sigenergy
   integration's own, so most need no change. Check each shows a reading.
3. The first time it connects to Home Assistant it makes helpers for
   anything left empty (**Settings › Devices & services › Helpers**):
   - **EVDC SoC High Limit** and **EVDC SoC Low Limit** (input numbers, %).
     If you already have `input_number.v2x_cut_off_threshold_high` and
     `input_number.v2x_cut_off_threshold`, they start at the same values.
   - **EVDC Vehicle Battery Capacity** (kWh), for the energy sensors. It
     starts at your `input_number.vehicle_max_capacity` if you have one,
     otherwise 0 (set it to see the energy sensors).
   - **EVDC V2X Mode** (an on/off switch), unless you already have
     `input_select.sigenergy_evdc_charging_mode`, which is used instead
     (V2X = manage the charger).

   You can point any of these at a helper you already have instead.
4. Optional: a **charge signal**, e.g. `binary_sensor.predbat_charging`.
   While it's on, the car is charged if there's room, and isn't stopped at
   the low limit.
5. If you've been doing this with an automation, turn **Watch only** on
   (Settings) at first: the add-on logs what it would do without pressing
   anything, so you can compare. Then turn your automation off and Watch
   only off.

The **Overview** shows what it's doing and why, the car's SoC against the
limits (set them there too), the power readings it decides from, the
energy in the car and the recent starts and stops. **Start charger** and
**Stop charger** press the buttons by hand.

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| Restart wait | 180 s | After the charger stops, how long before it may be started again |
| House needs power: battery | 0.1 kW | Home battery discharging faster than this |
| House needs power: grid | 0.1 kW | Importing more than this |
| Spare power: export | 0.5 kW | Exporting more than this… |
| Spare power: for | 10 s | …for at least this long |
| Margin | 0% | Starts need the SoC this far inside the limits (stops are at the limits). 1 or 2 stops it bouncing at a limit |
| Between button presses | 60 s | At least this long between presses |
| Watch only | off | Decide and log, but don't press anything |
| Notify service | none | e.g. `notify.mobile_app_your_phone`: told on every start and stop |

**Advanced** has the words the charger uses for its running states (which
mean plugged in, running and discharging), the V2X mode states, and the EMS
modes in which exporting isn't spare power (Command Discharging). Only
change these if your set-up reports different words.

Power sensors can be in W or kW.

## Its own entities

| Entity | |
| --- | --- |
| `sensor.evdc_soc_range_status` | What it's doing, with the reason as an attribute |
| `sensor.evdc_soc_range_last_action` | Started, Stopped, Would start (watch only) or Failed to…, with when, why and the SoC |
| `sensor.evdc_soc_range_vehicle_soc` | The car's last known SoC (kept while the charger reports 0 or nothing, and after a restart) |
| `binary_sensor.evdc_soc_range_plugged_in` | Car plugged in |
| `binary_sensor.evdc_soc_range_charger_running` | Charger running (charging, discharging or preparing) |
| `sensor.evdc_soc_range_available_energy` | kWh the car can give before the low limit |
| `sensor.evdc_soc_range_window_energy` | kWh between the low and high limits |
| `sensor.evdc_soc_range_window_percent` | How full that window is |
| `sensor.evdc_soc_range_presses_today` | Button presses today |

The energy sensors read 0.01 when the car isn't plugged in or isn't in V2X
mode. They show as unavailable while the add-on is stopped.

## Diagnostics

**Diagnostics › Health** shows the link to Home Assistant and anything
needing attention (also the coloured dot by the title). **Diagnostics ›
Debug** has the log level, recent log lines, a diagnostics bundle to
download and a restart button.

## For developers

Started from the repository's add-on template. The decision is in
`src/controller.py` (no I/O, fully tested), the reading of Home Assistant
and the button presses in `src/manager.py`, the helpers in `src/helpers.py`
and the sensors in `src/ha_entities.py`. Tests: `python -m pytest tests/`.

To release a change: bump `version` in `config.yaml`, add a `CHANGELOG.md`
entry, commit, tag `sigenergy_evdc_soc_range_manager-X.Y.Z` and push the
branch and the tag.
