# Changelog

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
