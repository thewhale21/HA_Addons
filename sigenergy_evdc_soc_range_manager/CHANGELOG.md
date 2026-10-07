# Changelog

## 0.5.0 — Limit schedule, round trip, costs and dropouts

- **Feature:** a limit schedule on the Overview: change the high and/or
  low limit for a while, every week (e.g. Tue and Thu 23:00–08:00 high
  50%) or once (e.g. tomorrow 06:00–10:00 low 95%). The everyday limits
  (the helpers) come back afterwards; one-off entries tidy themselves
  away. Pause, resume or delete entries.
- **Feature:** the round trip from the SoC: the kWh it takes to put 1%
  into the car against the kWh back for 1% out, from each charge and
  discharge (the median of the last 10 of each). The Statistics tab's
  losses now come from this, with the inverter's measured figures beside
  it when its sensors are there.
- **Feature:** Is it paying? Import and export rate pickers (the Octopus
  Energy integration's current rate sensors are found by themselves); what
  charging cost and discharging was worth over 30 days, the margin on each
  kWh out after the losses, the break-even price and what the losses cost.
  An inverter AC ↔ DC efficiency setting (96%) covers the charger counting
  DC.
- **Feature:** discharge dropouts: each time the car stops discharging by
  itself (not a stop from here, not unplugging) is logged on the Overview
  and counted on the Statistics tab, with a sensor and an optional
  notification after so many in a day.
- **Fix:** the loss chart's axis showed 0.0 for small values.

## 0.4.0 — Virtual battery on the Overview

- **Feature:** a Virtual battery card on the Overview: the car between its
  limits as one battery (as Predbat sees it), with how full it is, kWh
  stored of the window, what it's doing now and roughly when it'll be
  full or empty, its maximum rate (and the home battery's and plant's),
  today's kWh in and out, and the car's battery capacity and health. It
  replaces the Energy in the car card.

## 0.3.0 — Battery statistics

- **Feature:** a Statistics tab for the car's battery:
  - **Usable capacity:** each charge or discharge that moves the SoC 10% or
    more gives an estimate (kWh at the charger ÷ SoC moved, measured
    between the SoC's tick-overs). The latest is the median of the last
    10, compared with the capacity helper, with a trend (kWh and % a year)
    once there are 6 estimates over 2 months.
  - **Conversion losses:** the inverter's DC side (solar, home battery,
    car) against its AC side, every few seconds; the car gets its share of
    the loss by its share of the DC flow. The last 30 days by day, and the
    charging (AC → car) and discharging (car → AC) efficiency from clean
    sessions.
  - **Sessions:** every charge and discharge with its SoC, energy,
    capacity estimate, efficiency and loss.
- **Feature:** the last 30 days of Home Assistant's history are read once,
  so the capacity estimates and sessions start with something in them
  (losses are recorded from now on).
- **Feature:** sensors for the capacity estimate, battery health, charge
  and discharge efficiency and today's conversion loss.
- **Feature:** pickers for the charger's power and total charged and
  discharged energy, solar power and the inverter's AC power (Sigenergy's
  by default), and settings for the capacity span, what counts as a clean
  session, and flipping the inverter power's sign.

## 0.2.0 — Charging mode select and battery rate sensors

- **Feature:** battery rate sensors, as the "V2X Battery Rate", "Rate Car"
  and "Rate House" template sensors did:
  `sensor.evdc_soc_range_battery_rate`, `..._battery_rate_car` and
  `..._battery_rate_house`. Their fixed figures (8 and 12.5 kW, 95%, the
  4.5 kW home battery and 8 kW car top rates) are settings, and they read
  the Sigenergy plant's available power, battery SoC and rated capacity.
- **Change:** without a charging mode select, it now makes
  `input_select.sigenergy_evdc_charging_mode` (V2X, Solar Surplus, Fast
  Charging) rather than an on/off switch. It manages the charger only in
  V2X.
- **Change:** the energy sensors also count Solar Surplus mode, as the
  V2X SoC template sensors did.

## 0.1.0 — First version

- **Feature:** keeps the car's SoC between a low and a high limit in V2X
  mode by starting and stopping a Sigenergy DC charger, following the
  "V2X SOC Range Manager" automation's rules: start when the house needs
  power (above the low limit), when there's spare power (below the high
  limit) or when between the limits; stop at the high limit when not
  discharging and at the low limit when discharging.
- **Feature:** a restart wait (3 minutes) after the charger stops for any
  reason, and at least a minute between button presses.
- **Feature:** works out "plugged in", "running" and "discharging" from
  the charger's running state, and keeps the car's last known SoC itself
  (also after a restart).
- **Feature:** makes its high and low limit, battery capacity and V2X mode
  helpers when they aren't set, starting from existing V2X helpers'
  values; uses `input_select.sigenergy_evdc_charging_mode` as the V2X mode
  if it's there.
- **Feature:** an optional charge signal (e.g. Predbat charging), an
  optional notify service, a margin to stop it bouncing at a limit, and
  Watch only (decides and logs, presses nothing).
- **Feature:** sensors for its status, last action, the car's SoC,
  plugged in, charger running, the energy above the low limit and between
  the limits, and button presses today.
- **Feature:** a web page: status and reason, the SoC against the limits
  (set them there), power readings, energy, recent starts and stops,
  Start/Stop buttons, the entity pickers and settings, and diagnostics.
