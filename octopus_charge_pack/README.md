# Home Assistant Add-on: Octopus Charge Pack

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

Reads your Octopus Intelligent **planned flex dispatches** (Charge Pack
sessions) for a device, and makes them Home Assistant sensors: the planned
dispatches, the next charge and discharge, and the next discharge's date and
times. It replaces the REST and template sensors that did this, with the
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
| `device_id` | The device whose dispatches to read. Leave empty to find it: with one device on the account it's used; with more, the Settings tab lists them |
| `poll_seconds` | How often to read them: 60 by default (30 to 3600) |

Restart the add-on after changing them.

## Set it up

1. **Remove the old REST and template sensors** from your YAML (the Kraken
   token, Octopus Planned Dispatches, Next Charge/Discharge Dispatch Start
   and End, and Next Discharge Dispatch Date / Start Time / End Time), and
   restart Home Assistant. The add-on uses the same entity IDs, so both
   can't run at once.
2. Enter your API key on the add-on's **Configuration** tab (and the device
   ID if you know it), then start the add-on.
3. The **Overview** shows the next discharge and charge and the planned
   dispatches; **Diagnostics › Health** lists its sensors.

## Its Home Assistant entities

| Entity | |
| --- | --- |
| `sensor.octopus_charge_pack_status` | OK, or what's wrong (attributes: `error`, `device_id`, `last_update`) |
| `sensor.octopus_planned_dispatches` | How many dispatches are planned; attribute `flexPlannedDispatches` (start, end, type, energyAddedKwh) |
| `sensor.next_charge_dispatch_start` / `_end` | The next charge dispatch (timestamps) |
| `sensor.next_discharge_dispatch_start` / `_end` | The next discharge dispatch (timestamps) |
| `sensor.next_discharge_dispatch_date` | Its local date, `YYYY-MM-DD`, or `1999-01-01` when none is planned |
| `sensor.next_discharge_dispatch_start_time` | Its local start, `HH:MM:SS`; keeps the last one when none is planned |
| `sensor.next_discharge_dispatch_end_time` | Its local end, `HH:MM:SS`; `23:59:59` if it ends the next day; the start time when none is planned |

A dispatch with `energyAddedKwh` above 0 counts as a discharge and below 0
as a charge, as the template sensors did.

## Troubleshooting

- **Status says "API key refused":** check the key on the Configuration
  tab (Octopus account › Personal details › API access) and restart.
- **Status says to set device_id:** your account has more than one device;
  copy the right ID from the Settings tab into `device_id` and restart.
- **The dot by the title is amber or red:** **Diagnostics › Health** says
  why.
- **Asking for help:** **Diagnostics › Debug** has the log and a
  diagnostics bundle to download. Attach it to a
  [GitHub issue](https://github.com/thewhale21/HA_Addons/issues).

[docs]: https://github.com/thewhale21/HA_Addons/blob/main/octopus_charge_pack/DOCS.md
[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
