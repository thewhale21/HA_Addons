# Home Assistant Add-on: Octopus Charge Pack

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

Reads your Octopus Intelligent **planned flex dispatches** (Charge Pack
sessions) for a device, and makes them Home Assistant sensors: the planned
dispatches, and the next charge and discharge with their date and times. It replaces the REST and template sensors that did this, with the
same entity IDs, so anything using them (e.g. Predbat's
`rates_export_override`) carries on unchanged. You only enter your API key.

[Full documentation][docs] (also the add-on's **Documentation** tab).

---

## What you need

- Home Assistant OS or Supervised (add-ons need the Supervisor).
- An Octopus Energy account with a device on Octopus Intelligent flex
  dispatches, and your **API key** (Octopus account › Personal details ›
  API access).

## Install

1. Add this repository to Home Assistant:
   **Settings › Add-ons › Add-on store › ⋮ › Repositories**, and add
   `https://github.com/thewhale21/HA_Addons`.
2. Find **Octopus Charge Pack** in the store and click **Install**.
3. **Start** it, turn on **Show in sidebar**, and open it.

## Configuration (add-on options)

| Option | What to put |
| --- | --- |
| `api_key` | Your Octopus API key (`sk_live_...`). Hidden, and never shown on the page or in diagnostics |

Restart the add-on after changing it.

The **device** and **how often to read** are picked on the add-on's
**Settings** tab, in the Device card: a drop-down of the devices on your
account (name · type · provider) and a read interval from 30 seconds to an
hour. Both apply at once, with no restart. With one device on the account
it's used until you pick one.

## Set it up

1. **Remove the old REST and template sensors** from your YAML (the Kraken
   token, Octopus Planned Dispatches, Next Charge/Discharge Dispatch Start
   and End, and Next Discharge Dispatch Date / Start Time / End Time), and
   restart Home Assistant. The add-on uses the same entity IDs, so both
   can't run at once.
2. Enter your API key on the add-on's **Configuration** tab, then start
   the add-on.
3. Open it and pick your device (for Charge Pack, the battery) in the
   **Settings** tab's Device card.
4. The **Overview** shows the status, then the next discharge and charge,
   each with its planned dispatches; **Diagnostics › Health** lists its sensors.

## Its Home Assistant entities

| Entity | |
| --- | --- |
| `sensor.octopus_charge_pack_status` | OK, or what's wrong (attributes: `error`, `device_id`, `last_update`) |
| `sensor.octopus_charge_pack_now` | What Octopus has the battery doing now: `charging`, `discharging`, `idle` or `none` (attributes: `start`, `end`, `energy_kwh`, `minutes_left`) |
| `calendar.octopus_charge_pack` | The planned charges and discharges as calendar events (a Local Calendar the add-on makes; can be turned off on the Settings tab). Use it in calendar triggers, e.g. 15 minutes before a discharge |
| `sensor.octopus_planned_dispatches` | How many dispatches are planned; attribute `flexPlannedDispatches` (start, end, type, energyAddedKwh) |
| `sensor.next_charge_dispatch_start` / `_end` | The next charge dispatch (timestamps) |
| `sensor.next_discharge_dispatch_start` / `_end` | The next discharge dispatch (timestamps) |
| `sensor.next_*_dispatch_start_date` / `_end_date` | Its local start and end dates, `YYYY-MM-DD`, or `1999-01-01` when none is planned. One that runs past midnight ends on the next day's date |
| `sensor.next_*_dispatch_start_time` / `_end_time` | Its local start and end times, `HH:MM:SS` (the real end time, also past midnight). When none is planned the start time keeps the last one and the end time is the start time |
| `sensor.next_*_dispatch_date` | The start date again, under the old single date sensor's ID, for existing configs |

`*` is `charge` or `discharge`: each has the same set.

A dispatch with `energyAddedKwh` above 0 counts as a discharge and below 0
as a charge, as the template sensors did.

## Troubleshooting

- **Status says "API key refused":** check the key on the Configuration
  tab (Octopus account › Personal details › API access) and restart.
- **Status says to pick your device:** your account has more than one
  device; pick the right one in the **Settings** tab's Device card.
- **The dot by the title is amber or red:** **Diagnostics › Health** says
  why.
- **Asking for help:** **Diagnostics › Debug** has the log and a
  diagnostics bundle to download. Attach it to a
  [GitHub issue](https://github.com/thewhale21/HA_Addons/issues).

[docs]: https://github.com/thewhale21/HA_Addons/blob/main/octopus_charge_pack/DOCS.md
[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
