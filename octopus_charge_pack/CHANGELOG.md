# Changelog

## 0.4.0 — Overview layout

- **Change:** the Overview has the status full width across the top, then
  the next discharge and next charge side by side, each listing its own
  planned dispatches. The separate Planned dispatches card is gone.
- **Change:** the Device card (device and read interval) moves to the
  Settings tab.

## 0.3.1 — Charge and discharge chips

- **Improvement:** the Overview marks dispatches with a coloured chip,
  Discharge or Charge, on the next discharge and charge cards and on each
  row of the planned dispatches (Octopus's own type is shown beside it).

## 0.3.0 — Device and interval on the Overview

- **Feature:** the device is a drop-down on the Overview, listing the
  devices on your account (re-read every 6 hours). The pick applies at
  once.
- **Feature:** the read interval is picked on the Overview too (30 seconds
  to an hour), and applies at once, with no restart.
- **Change:** `device_id` and `poll_seconds` are no longer add-on options.
  Values you had set are copied over once, so nothing changes until you
  pick something else.
- **Change:** the Settings tab no longer lists the devices.

## 0.2.0 — Start and end dates, and the charge's too

- **Feature:** start and end date sensors for the next dispatch:
  `sensor.next_discharge_dispatch_start_date` and `..._end_date`, and the
  same for the charge.
- **Feature:** the next charge dispatch gets the same date and time
  sensors as the discharge: `sensor.next_charge_dispatch_start_date`,
  `_end_date`, `_start_time`, `_end_time` and `_date`.
- **Change:** a dispatch that runs past midnight now ends on the next day's
  end date at its real end time, instead of the end time showing 23:59:59.
  `sensor.next_*_dispatch_date` stays, as the start date.
- **Improvement:** the Overview's next charge shows its dates, times and
  kWh, like the discharge.

## 0.1.0 — First version

- **Feature:** reads your Octopus Intelligent planned flex dispatches
  (Charge Pack sessions) with your API key, and posts them as Home
  Assistant sensors: the planned dispatches, the next charge and discharge
  start and end, and the next discharge's date, start time and end time,
  with the same entity IDs and logic as the REST and template sensors they
  replace.
- **Feature:** finds the device from your account when `device_id` is left
  empty.
- **Feature:** a web page with the next discharge and charge, the planned
  dispatches and the status.
