# Home Assistant Add-on: Stellantis EV Stats

Real-world range, efficiency by temperature and battery health for a
Stellantis electric car (Peugeot, Vauxhall/Opel, Citroën, DS, Fiat, Jeep…),
from the [Stellantis Vehicles](https://github.com/andreadegiovine/homeassistant-stellantis-vehicles)
integration.

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

- Every trip recorded with its energy, the outside temperature and the SoC.
- Efficiency (mi/kWh) and the real range at 100% in 5 °C bands, against the
  car's own estimate.
- The car's battery health figures over time, and the usable capacity
  measured from the car's own readings.
- Sensors for Home Assistant: real range at 100% and left now, efficiency,
  usable capacity, battery health.

See [DOCS.md](DOCS.md).

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
