# Home Assistant Add-on: Tigo Solar

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

Your Tigo solar panels in Home Assistant: a view of your roof where you
click panels in and out of the charts, production by day, week, month and
year, how much the Tigo optimisers reclaim, and sensors for each panel and
the whole system. It logs in to the Tigo portal itself, so the free Tigo
plan is enough and no integration is needed.

[Full documentation][docs] (also the add-on's **Documentation** tab).

---

## What you need

- Home Assistant OS or Supervised (add-ons need the Supervisor).
- A Tigo system with a Tigo cloud account (the free plan works).

## Install

1. Add this repository to Home Assistant:
   **Settings › Add-ons › Add-on store › ⋮ › Repositories**, and add
   `https://github.com/thewhale21/HA_Addons`.
2. Find **Tigo Solar** in the store and click **Install**.
3. Fill in its **Configuration** (below), then **Start** it, turn on
   **Show in sidebar**, and open it.

## Configuration (add-on options)

| Option | What to put |
| --- | --- |
| `username` | The email address you log in to the Tigo portal with |
| `password` | Your Tigo password (only sent to Tigo) |
| `system_id` | Your system's number on Tigo (`system_id=` in the portal's address, or the Tigo integration's settings) |

## Its Home Assistant entities

| Entity | |
| --- | --- |
| `sensor.tigo_solar_power` | The system's power now (W) |
| `sensor.tigo_solar_reclaimed_power` | Of which reclaimed by the optimisers (W) |
| `sensor.tigo_solar_energy_today` | Energy today (kWh, for the Energy dashboard) |
| `sensor.tigo_solar_reclaimed_energy_today` | Reclaimed energy today (kWh) |
| `sensor.tigo_solar_energy_month`, `_energy_year`, `_energy_lifetime` | Energy this month, this year and ever (kWh) |
| `sensor.tigo_solar_panel_<label>_power`, `_reclaimed_power`, `_energy_today` | Each panel (e.g. `sensor.tigo_solar_panel_a1_power`) |
| `sensor.tigo_solar_status` | What it's doing |

## Troubleshooting

- **The dot by the title is amber or red:** **Diagnostics › Health** says
  why (e.g. Tigo refused the login).
- **Asking for help:** **Diagnostics › Debug** has the log and a
  diagnostics bundle to download (your password is hidden). Attach it to a
  [GitHub issue](https://github.com/thewhale21/HA_Addons/issues).

[docs]: https://github.com/thewhale21/HA_Addons/blob/main/tigo_solar/DOCS.md
[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
