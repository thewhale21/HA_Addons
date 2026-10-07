# Changelog

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
