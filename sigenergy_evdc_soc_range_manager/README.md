# Home Assistant Add-on: SigEnergy EVDC SoC Range Manager

Keeps an EV's state of charge between a high and a low limit in V2X mode,
by starting and stopping a Sigenergy DC charger.

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

- Between the limits the charger runs; at the high limit it only runs to
  discharge into the house, at the low limit only to charge from spare power.
- A restart wait for cars that stop discharging now and then.
- Makes its own limit helpers, works from the Sigenergy integration's
  entities, and posts status, SoC, energy and V2X battery rate sensors.
- A web page in the sidebar: what it's doing and why, the limits, recent
  starts and stops, a watch-only mode for trying it out, and battery
  statistics: usable capacity over time and conversion losses.

See [DOCS.md](DOCS.md).

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
