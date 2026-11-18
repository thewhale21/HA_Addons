# Tigo Solar

Your Tigo solar panels in Home Assistant: a view of your roof, charts of
what they make and what the Tigo optimisers reclaim, and sensors for each
panel and the whole system.

## Setting it up

1. In the add-on's **Configuration** tab, fill in your Tigo **username**
   (the email you log in to ei.tigoenergy.com with), **password** and
   **system ID** (the number after `system_id=` in the portal's address when
   you look at your system, or in the Tigo integration's settings). Save,
   then start the add-on.
2. Open it from the sidebar. Within a minute it has your panels and today's
   readings; then it reads your history from Tigo in the background (a few
   requests a minute, so a year takes about half an hour). **History** on
   the Overview shows how far it's got.

It reads the Tigo portal the way its web pages do, so the **free plan** is
enough: it has each panel's power, reclaimed power and energy, and the
system's power by the minute and energy by the day, month and year. The
free plan's data changes about every 15 minutes, so the add-on reads it
every 5 (every minute on the premium plan). The premium plan's extra
readings (voltages, current, temperature) aren't used.

## The Overview

- **Right now:** the system's power, how much of it the optimisers
  reclaimed, today's energy, this month's, this year's and the lifetime
  total, and the time of Tigo's latest reading.
- **Your roof:** your panels where Tigo's layout puts them (the one in the
  Tigo portal). **Power now** colours each by its power at the latest
  reading; **Energy** by what it made over the time the chart below shows,
  dark to yellow. Hover over a panel for its details.
  - **Click a panel** to take it out of the charts or put it back in;
    **All panels** and **None** choose all or none. The choice is kept in
    this browser.
  - **Move panels** lets you drag them to where they really are on your
    roof (saved as you drop each one; kept across updates).
    **Put back Tigo's layout** undoes all your moves.
- **Production:** the chart for a **Day** (power through the day), a
  **Week** (the 7 days to the day shown), a **Month** or a **Year** (energy
  by the day or month). ‹ and › go back and forward, **Today** comes back
  to today; click a day's bar to see that day. Below it: what was made then
  and what was reclaimed.
  - **The whole system** (all panels chosen): split into what the panels
    made on their own (dark green) and what the optimisers reclaimed (light
    green).
  - **Some panels chosen:** their energy added up. Tigo splits reclaimed
    energy off only for the whole system, so the bars are one colour. For a
    **Day**, their power through the day is only known from when the
    add-on started: Tigo keeps each panel's latest reading only, so the
    add-on records them every time it reads (the history from before then
    has each panel's energy by the day, not by the hour).
- **History:** how much of your history has been read from Tigo, since when
  each panel's power through the day has been recorded, and your Tigo plan.

## Its Home Assistant sensors

The add-on posts them itself (no integration needed). They show as
unavailable while it's stopped.

| Entity | |
| --- | --- |
| `sensor.tigo_solar_power` | The system's power at Tigo's latest reading (W) |
| `sensor.tigo_solar_reclaimed_power` | Of which reclaimed by the optimisers (W) |
| `sensor.tigo_solar_energy_today` | Energy today (kWh; for the Energy dashboard's solar production) |
| `sensor.tigo_solar_reclaimed_energy_today` | Reclaimed energy today (kWh) |
| `sensor.tigo_solar_energy_month` | Energy this month (kWh) |
| `sensor.tigo_solar_energy_year` | Energy this year (kWh) |
| `sensor.tigo_solar_energy_lifetime` | Energy ever (kWh) |
| `sensor.tigo_solar_panel_<label>_power` | Each panel's power (W), named after its label on Tigo (e.g. `..._panel_a1_power`) |
| `sensor.tigo_solar_panel_<label>_reclaimed_power` | Each panel's reclaimed power (W) |
| `sensor.tigo_solar_panel_<label>_energy_today` | Each panel's energy today (kWh) |
| `sensor.tigo_solar_status` | What the add-on is doing |

Moving from the Tigo integration: these replace its sensors, so you can
remove it once you've pointed your dashboards and the Energy dashboard at
these.

## Where it keeps things

In the add-on's own folder (kept across updates and in backups):
`tigo.db` (the history), `layout.json` (where you've moved panels) and
`settings.json` (the log level). Your Tigo password is only in the add-on's
options and only sent to Tigo.

## Troubleshooting

- **"Tigo refused the login"** (the dot by the title turns red): check the
  username and password in the Configuration tab, and that you can log in
  to ei.tigoenergy.com with them.
- **"Can't reach Tigo":** Tigo's servers often fail for a minute; the
  add-on tries again after 1, 2, 5 and then 10 minutes, and the history
  carries on where it stopped.
- **A panel shows —:** Tigo hasn't sent a reading for it yet (e.g. before
  sunrise).
- **Asking for help:** **Diagnostics › Debug** has the log level, recent log
  lines and a diagnostics bundle to download (your password is hidden).

## Thanks

The Tigo login is based on the Tigo integration for Home Assistant by
Martin Stoffel ([MartinStoffel/tigo](https://github.com/MartinStoffel/tigo),
MIT licence).
