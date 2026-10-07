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
   - **SigEnergy EVDC Charging Mode** (`input_select.sigenergy_evdc_charging_mode`:
     V2X, Solar Surplus, Fast Charging), unless you already have it. It
     only manages the charger in V2X.

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
virtual battery and the recent starts and stops.

The **virtual battery** is the car between its limits seen as one
battery, the way Predbat sees it through the available energy, window and
battery rate sensors: how full it is, kWh stored of the window, what it's
doing now and roughly when it'll be full or empty at that rate, its
maximum rate, today's kWh in and out, and the car's capacity and health. **Start charger** and
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
| Battery rates | 8 and 12.5 kW, 95%, 4.5 kW home, 8 kW car | See [Battery rates](#battery-rates) |

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
| `sensor.evdc_soc_range_battery_rate` | The plant's charge/discharge rate with the car plugged in (kW) |
| `sensor.evdc_soc_range_battery_rate_car` | The car's share of it (kW) |
| `sensor.evdc_soc_range_battery_rate_house` | The home battery's share of it (kW) |
| `sensor.evdc_soc_range_presses_today` | Button presses today |

The energy sensors read 0.01 when the car isn't plugged in or isn't in V2X
or Solar Surplus mode. All of them show as unavailable while the add-on is
stopped.

### Battery rates

For Predbat or similar. With the car plugged in and in V2X or Solar
Surplus mode, the rate is the plant's available power, capped at
**Rate** (8 kW), or **Top rate** (12.5 kW) once the home battery is
**Nearly full** (95%). In Fast Charging it's the top rate; otherwise 0.

That's shared between the home battery and the car in proportion to their
sizes (the home battery's rated capacity, and the car's kWh between its
limits), each capped at its top rate (4.5 kW home, 8 kW car), and scaled
down together if that's more than the plant can do. Without the car it's
all the home battery's (up to its top rate). All the figures are on the
Settings tab, and the plant entities default to Sigenergy's
(`sensor.sigen_plant_available_max_active_power`,
`sensor.sigen_plant_battery_state_of_charge`,
`sensor.sigen_inverter_rated_battery_capacity`).

## Limit schedule

On the Overview, **Limit schedule** changes the high and/or low limit for
a while, every week or once:

- Every week: e.g. Tue and Thu 23:00–08:00, high 50% (an entry can run
  past midnight).
- Once: e.g. tomorrow 06:00–10:00, low 95% (the car isn't discharged
  below 95% that morning). One-off entries are removed once they've
  finished.

The limit helpers are your everyday limits and aren't changed; while an
entry is on, its limits are used instead (the Car card says so). Where
entries overlap, the one that started last wins. If a scheduled limit
crosses the other one, the other moves out of its way (a scheduled low of
95% with an everyday high of 80% makes the high 96%). The energy and rate
sensors use the scheduled limits too, so Predbat sees the change.

## Statistics

The **Statistics** tab is about the car's battery.

**Usable capacity.** Each charge or discharge that moves the SoC at least
10% gives an estimate: the kWh at the charger divided by the SoC moved.
It's measured between the moments the SoC ticks over, since it's only a
whole number. The figure shown is the median of the last 10, against your
battery capacity helper, and after 6 estimates over 2 months there's a
trend in kWh (and %) a year. It's a guess at degradation: the energy is
measured at the charger, so it includes the car's own charging losses,
and the car's SoC reading has its own quirks. Watch the trend rather than
any one figure. Fast charges from low to high give the best estimates.

**Round trip.** Each charge and discharge that moves the SoC far enough
gives the kWh per 1%: say 0.60 kWh to put 1% in, but only 0.54 kWh back
for 1% out, a 90% round trip. The median of the last 10 of each is used,
and the last 30 days' losses are the kWh out of the car × (1 ÷ round trip
− 1). This covers the charger and the car; the inverter's own AC ↔ DC
loss is on top.

**Is it paying?** With your import and export rate sensors set (the
Octopus Energy integration's current rate sensors are picked up by
themselves), every kWh into the car is priced at the import rate when
you're importing, otherwise at the export rate you gave up; every kWh out
at the import rate it saves, or the export rate when exporting. Over 30
days it shows what charging cost, what discharging was worth, the margin
on each kWh out after the losses, the break-even price a kWh out must be
worth, and what the losses cost. The charger counts DC energy and you pay
for AC, so the **Inverter AC ↔ DC efficiency** setting (96%, each way) is
applied. Prices are recorded from when they're set.

**Discharge dropouts.** Each time the car stops discharging by itself
(not a stop from here, and not unplugging) is logged on the Overview and
counted by day. **Dropout alert** (Settings) sends a notification after
so many in a day.

**Inverter losses.** Every few seconds it also compares the inverter's DC
side (solar in, home battery in or out, car in or out) with its AC side;
what goes in and doesn't come out is lost. The car is given its share of
that by its share of the DC flow at the time. Sessions with little solar
or home battery going at the same time ("clean" ones) give a straight
efficiency for charging (AC → car) and discharging (car → AC). If the
losses read large and negative, turn on **Flip the inverter's power**
(Settings): your inverter's power sensor reads the other way round.

It reads `sensor.sigen_inverter_dc_charger_total_charging_capacity` and
`..._total_discharging_capacity` (the car's energy),
`sensor.sigen_inverter_dc_charger_output_power`, `sensor.sigen_plant_pv_power`,
`sensor.sigen_inverter_active_power` and the home battery power. Change
any of them on the Settings tab. The first time it connects it reads the
last 30 days of these from Home Assistant's history for the sessions and
capacity estimates; the losses are recorded from then on.

| Entity | |
| --- | --- |
| `sensor.evdc_soc_range_capacity_estimate` | The car's usable capacity estimate (kWh) |
| `sensor.evdc_soc_range_battery_health` | ...as a % of the capacity helper |
| `sensor.evdc_soc_range_charge_efficiency` | AC → car (%) |
| `sensor.evdc_soc_range_discharge_efficiency` | Car → AC (%) |
| `sensor.evdc_soc_range_conversion_loss_today` | The car's share of today's inverter loss (kWh) |
| `sensor.evdc_soc_range_round_trip_efficiency` | kWh out per 1% ÷ kWh in per 1% (%) |
| `sensor.evdc_soc_range_dropouts_today` | Times the car stopped discharging by itself today |

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
