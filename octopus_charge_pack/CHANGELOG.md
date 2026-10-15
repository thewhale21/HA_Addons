# Changelog

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
