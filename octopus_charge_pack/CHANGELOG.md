# Changelog

## 0.9.3 — Each tab from the top

- **Change:** switching tab goes back to the top of the page, instead of
  staying as far down as you'd scrolled on the last one.

## 0.9.2 — Just the one date sensor

- **Change:** the `_start_date` and `_end_date` sensors are gone, for all
  six charges and discharges (e.g. `sensor.next_charge_dispatch_start_date`,
  `sensor.next_discharge_dispatch_3_end_date`); `sensor.next_*_dispatch_date`
  (the start date) stays, with the start and end times. The old ones are
  taken out of Home Assistant when the add-on starts.

## 0.9.1 — Plan changes in the log

- **Change:** the History tab's **Plan changes** card is gone. Each change
  is still logged, now at Debug (with what it was before a change), and
  kept in the diagnostics bundle for 7 days.

## 0.9.0 — The last 7 days

- **New:** the History tab has a chart of the last 7 days: each day's kWh
  discharged to the left of a centre line and charged to the right,
  counting only the sessions that really moved your home battery (with its
  SoC sensor picked; otherwise every completed session), and how many of
  the day's sessions did (✓) or didn't (✕). Click a day to show only its
  sessions in the list below; again, or **Show all**, to show them all.

## 0.8.1 — Completed sessions at a glance

- **Change:** on the Overview's **Today and tomorrow**, a completed charge
  or discharge shows a green tick, or a red cross when your home battery's
  SoC shows it didn't charge or discharge (Settings › Your home battery),
  centred in its block. Completed blocks are paler, so the mark stands out.

## 0.8.0 — Three charges, and the banner theme

- **New:** sensors for the 2nd and 3rd planned charge, like the
  discharges: `sensor.next_charge_dispatch_2_date`, `..._2_start_time`,
  `..._2_end_time`, `..._3_start` and so on (`1999-01-01` and `00:00:00`
  when there isn't one), e.g. for more `rates_import_override` entries in
  Predbat.
- **New:** the page has the same look as the other add-ons: a coloured
  banner at the top of each tab, from blue to Octopus purple (Overview:
  what's happening now; History: the completed sessions' totals;
  Settings; Diagnostics › Health: **All good**, or orange or red when
  something needs attention).
- **New:** Settings › **Appearance**: **Colourful** (the banners) or
  **Basic** (plain cards), saved in each browser.

## 0.7.1 — Plan changes without idle slots

- **Change:** Plan changes leaves out idle dispatches (0 kWh): only charges
  and discharges added, moved or taken off are listed (an idle slot that
  becomes a charge or discharge shows as added). Idle ones already listed
  are cleared.

## 0.7.0 — Did the battery really discharge?

- **Feature:** pick your home battery's SoC sensor on the Settings tab
  (Your home battery). Each completed session then shows its SoC from start
  to end, and whether it really discharged (or charged): 2% or more the
  right way counts. Earlier sessions are checked too, as far back as Home
  Assistant keeps history.
- **Improvement:** the History tab's completed sessions are redesigned:
  totals across the top (sessions, kWh discharged and charged, and how many
  really moved the battery), and each session as a row with its times,
  planned kWh, a SoC bar and the result.

## 0.6.3 — A calendar each for charges and discharges

- **Change:** two calendars instead of one: Octopus Charge Pack Charge
  (`calendar.octopus_charge_pack_charge`) and Octopus Charge Pack Discharge
  (`calendar.octopus_charge_pack_discharge`), made the first time. The
  0.6.0 calendar (`calendar.octopus_charge_pack`) is no longer updated: delete
  it in Settings > Devices & services > Local Calendar if you don't want it.

## 0.6.2 — A History tab and a clearer timeline

- **Change:** Completed sessions and Plan changes move to a new History
  tab, and the Idle card is gone from the Overview (idle time still shows
  on the timeline).
- **Improvement:** the Today and tomorrow timeline is easier to read:
  taller rows with the day and date, hour gridlines and times every 3
  hours, charges and discharges as labelled blocks (times and kWh when they
  fit) with a tick once completed, idle time as a soft band, the past
  dimmed and a marker for now.

## 0.6.1 — The 2nd and 3rd discharges

- **Feature:** sensors for the 2nd and 3rd planned discharges, the same set
  as the next one: `sensor.next_discharge_dispatch_2_date`, `_2_start_date`,
  `_2_end_date`, `_2_start_time`, `_2_end_time`, `_2_start`, `_2_end`, and
  the same with `_3` (`1999-01-01` and `00:00:00` when there isn't one).
  Add them to Predbat's `rates_export_override` like the first (README).

## 0.6.0 — Now, a calendar, plan changes and a timeline

- **Feature:** `sensor.octopus_charge_pack_now`: what Octopus has the
  battery doing now (charging, discharging, idle or none), with the
  dispatch's start, end, energy and minutes left. Also on the Overview.
- **Feature:** a calendar of the planned charges and discharges
  (`calendar.octopus_charge_pack`, a Local Calendar the add-on makes), kept
  in step with the plan, for HA's calendar and calendar triggers. On by
  default; a switch on the Settings tab.
- **Feature:** a Plan changes card: what Octopus added, moved or took off
  the plan, and when (the last 7 days).
- **Feature:** a timeline of today and tomorrow on the Overview: charges,
  discharges and idle time, completed ones outlined, and now.

## 0.5.2 — Its own icon

- **Change:** a Charge Pack icon and logo in the add-on store (a battery
  with a lightning bolt) instead of the template's puzzle piece, and a home
  battery icon in the sidebar.

## 0.5.1 — Idle dispatches shown

- **Fix:** the Overview only listed dispatches with energy (charges and
  discharges); the ones Octopus plans with 0 kWh were left out. They're now
  listed in their own Idle card, so every planned dispatch shows. They
  aren't counted as completed sessions.

## 0.5.0 — Completed sessions

- **Feature:** a Completed sessions card on the Overview: the charge and
  discharge sessions of the last 30 days that actually happened, with
  their date, times, type and energy. A dispatch counts as completed if it
  was still in Octopus's plan when it ended (within two reads); one taken
  off the plan earlier doesn't. Kept across restarts.

## 0.4.1 — Tidier Settings tab

- **Change:** the Settings tab's Octopus card (device ID, read interval and
  last read) is gone: the Device card's drop-downs already show them. Its
  API key note moves into the Device card.

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
