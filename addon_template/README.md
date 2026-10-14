# Home Assistant Add-on: Add-on Template

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

A starting point for a Home Assistant add-on with its own web page. It
runs as is: install it to see the web page in the sidebar, pick an entity
on the Settings tab and watch it on the Overview.

To start a new add-on from it, run `python scripts/new_addon.py` at the top
of the repository (see the repository's README), then fill in this README:
it's the add-on's Info page in Home Assistant, and the issue triage reads
it. Replace each part below with your add-on's own.

[Full documentation][docs] (also the add-on's **Documentation** tab).

---

## What you need

- Home Assistant OS or Supervised (add-ons need the Supervisor).
- *(The integrations, devices or sensors your add-on works with.)*

## Install

1. Add this repository to Home Assistant:
   **Settings › Add-ons › Add-on store › ⋮ › Repositories**, and add
   `https://github.com/thewhale21/HA_Addons`.
2. Find **Add-on Template** in the store and click **Install**.
3. **Start** it, turn on **Show in sidebar**, and open it.

## Configuration (add-on options)

| Option | What to put |
| --- | --- |
| `example_option` | Any text: it's shown on the Overview |

Everything else is set on the add-on's web page and saved as you change it.

## Set it up

1. **Settings tab:** pick an entity (type to search). Its reading shows on
   the Overview and updates live.
2. *(Your add-on's own steps.)*

## Its Home Assistant entities

| Entity | |
| --- | --- |
| `sensor.addon_template_status` | What it's doing |
| `sensor.addon_template_ticks` | The example's counter (replace with your own) |

## Troubleshooting

- **The dot by the title is amber or red:** **Diagnostics › Health** says
  why.
- **Asking for help:** **Diagnostics › Debug** has the log and a
  diagnostics bundle to download. Attach it to a
  [GitHub issue](https://github.com/thewhale21/HA_Addons/issues).

[docs]: https://github.com/thewhale21/HA_Addons/blob/main/addon_template/DOCS.md
[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
