# Home Assistant Add-on: OCPP Charge Proxy

## How to use

This add-on acts as a virtual OCPP 1.6 chargepoint and connects to any
OCPP 1.6J server. When the server sends charge scheduling commands, the add-on
updates its state so Home Assistant automations can respond.

## Prerequisites

- An OCPP 1.6J compatible supplier account (or any CSMS that accepts OCPP 1.6
  chargepoint connections)
- OCPP connection credentials (server hostname, chargepoint ID, password)
  from your supplier

## Configuration

### Required options

| Option | Description |
|--------|-------------|
| `server_hostname` | Your supplier's OCPP server hostname |
| `chargepoint_id` | Your chargepoint ID for authentication |
| `password` | Your OCPP password |

### Optional options

| Option | Default | Description |
|--------|---------|-------------|
| `charger_model` | `PLP2-0-2-2` | Charger model reported in BootNotification |
| `charger_vendor` | `Wall Box Chargers` | Charger vendor reported in BootNotification |
| `charger_serial` | Auto-generated | Charger serial number (generated on first boot if empty) |
| `firmware_version` | `6.11.16` | Firmware version reported in BootNotification |
| `initial_energy_wh` | `0` | Seed the energy register (Wh). Set to your old charger's meter reading when migrating. Only applied if higher than the stored register (the meter never goes backwards); cleared after first boot. |

The max current and **Continue session after a restart** are set on the web
page's Settings tab (Controls), and the log level on Diagnostics › Debug.
They used to be add-on options; they're kept across restarts and updates.
OCPP messages are logged at `info`, except Heartbeats and periodic meter
readings (in a session or not), which only show at `debug`. Clock-aligned
readings stay at `info` during a session (outside one, they're `debug` too).

### Controlling your charger

Use the **Power** sensor (`sensor.ocpp_charge_proxy_power`) to trigger automations when
your supplier starts or stops charging: with the simulated power, it's above
0 while the charger is charging. For example, turn on a smart plug when it
rises above 0 and off when it drops back to 0.

### Power entity

You can optionally pick a Home Assistant power sensor (W or kW) on the
add-on's **Settings** tab. The proxy will report this real power value to your
supplier instead of simulating power delivery. The value is capped at what the
virtual chargepoint could physically deliver at its current setting.

If not configured, the proxy uses a realistic power simulation.

### SoC sensor for reporting

You can also pick a **SoC sensor** on the Settings tab, for example from
your car's own integration, reporting 0–100%. When set:

- The car's state of charge is sent to your supplier whenever it asks for
  `SoC` in its meter values (Octopus does), while a car is plugged in.
- **Car full:** when the sensor reads 100% during a session, the charger
  reports `SuspendedEV` and stops drawing power, as a real car does when its
  battery is full. The session stays open; if the SoC drops below 100%,
  charging resumes. A charging-profile pause (`SuspendedEVSE`) takes priority.

Leave it unset (or clear it) and no SoC is reported and car-full never
triggers. If the sensor becomes unavailable, SoC reporting pauses until it
comes back.

### Auto plug-in, the car plugged in sensor and Charge now

**Auto plug-in** (Automations tab) switches Plugged In on once when the SoC
drops below the level you set. With **Automatically adjust schedule to fit
auto plug-in** on, it also adds the charge to the schedule as a one-off,
for the hours you choose (**Charge for**, 0.5 to 12). The **Car plugged in**
sensor (Automations tab) can do the same when it plugs in: turn on **Add a
charge to the schedule** and set its own **Charge for**. **Charge now**
works the same way. In each case:

- The slot runs from plugging in to the first ready time your supplier
  accepts at least that long away (rounded up to the half hour; with EDF,
  the next time between 04:00 and 11:00). It unplugs then, after the
  supplier stops the session or the unplug wait (60 s by default).
- **No-charging times** (below) are left out: it unplugs at the start of
  one and plugs back in at its end, and the charge still ends when it would
  have. If it happens during one, it isn't plugged in then, only at its end
  if the charge would still be running. For example, 12 hours from 21:30
  with 23:30–05:30 blocked: 21:30–23:30, then 05:30–09:30.
- Octopus Energy, with Force schedule on supplier on: only the daily limit
  (6 hours, in each day from 12:00 unless changed on the Settings tab) is scheduled, the earliest first, so up to 12 hours can be
  chosen but a longer charge stops after 6 plugged-in hours (e.g. 12 hours
  from 16:30 with 23:30–05:30 blocked: 16:30–22:30). If it puts more than 6 hours in any 24 (counting the previous
  24 hours too), the next scheduled slot starts later, by whole half hours,
  just enough to get back to 6; if skipping it isn't enough, the slot after
  it is trimmed too, and so on, for that day only. For example, 4 hours scheduled 23:30–03:30 and a 3-hour
  auto plug-in at 18:00: that night's slot starts at 00:30. With it off
  there's no 6-hour limit, for auto plug-in, Charge now or the schedule.
  Hours are real hours, as Octopus counts them: the night the clocks go
  back, 23:30–05:30 is 7 hours (and 5 the night they go forward), so that
  night's slot shows in red; skip it and add a one-off 23:30–04:30, or
  leave it and Octopus schedules 6 of the 7.
- If it meets or overlaps the next scheduled slot, they become one slot,
  ending at the schedule's unplug.
- The supplier's ready time is set to the end of the slot (E.ON Next has
  none to set).
- Deleting the charge's slot puts back what it changed: a slot it trimmed
  or joined goes back to how it was.

The entries show on the Automations tab as orange **Auto plug-in**, pink
**Charge now** or brown **Car plugged in** slots, and run even with the
schedule off. A slot that was trimmed keeps its own colour.

### No-charging times

**No-charging times** are times nothing is scheduled in, on the days you
pick, e.g. your off-peak hours (23:30–05:30) when the car may well charge
anyway. They're part of the schedule on the Automations tab: add one as you
would a slot (click or drag across a day, or **+ Add a slot**) and choose
**No-charging time**; click one to change its times or days, or delete it. Slots can't be added in them (and one
can't be added over existing slots), and auto plug-in, the car plugged in
sensor and Charge now are planned around them (above). They're shown
hatched in blue-grey.

### Schedule, auto re-plug and start-up

- **Schedule** (**Automations** tab): the last 3 days and the next 7 are
  shown as slots, each running from a plug-in to its unplug, coloured by
  type: weekly (blue), one-off (teal), auto plug-in (orange) and Charge now
  (pink). **+ Add a slot** starts a new one from the next half hour. The
  last 3 days are for looking back: they show when the car was actually
  plugged in (coloured by what plugged it in: the schedule, auto plug-in,
  Charge now, or grey for another way such as by hand; hover for who
  unplugged it), not the schedule as it is now. A green line shows when it
  actually charged (hover for the session's energy, length and what ended
  it; click to open it on the Sessions tab), and your supplier's slots are
  outlined. Click or drag across a day to add a slot; click a slot to change its times, the days it repeats on
  (**Every week**) or its date (**Once**), turn it off, delete it, or skip
  it once (its plug-in and unplug both don't run; it shows hatched, and
  **Undo skip** puts it back). Changes are saved straight away. An unplug
  time with no plug-in before it (e.g. "unplug at 07:00 every day", to
  unplug anything left plugged in) shows as a small tick, and can be
  changed or deleted the same way. Times are in your Home Assistant time
  zone. A time missed while the add-on was stopped isn't run later.
  Unplugging during a session ends the session.
- **One-off slots:** a **Once** slot runs on its date only. Once it has
  run it's kept for 14 days: sessions on the **Sessions** tab that ran in
  a one-off slot are tagged **One-off** (or **Auto plug-in** / **Charge
  now**). A skipped unplug isn't used for the ready time.
- **Starting inside a scheduled stretch:** if the add-on starts (or
  restarts) while the schedule has the car plugged in, e.g. at 02:00 with
  plug in 23:30 and unplug 07:00, and Plugged In is off, it plugs in
  straight away (and with Force schedule on supplier, sets the ready time
  once Home Assistant is connected). It never unplugs at start-up.
- **Force schedule on supplier** (**Automations** tab, off by default):
  when the schedule plugs in, the add-on sets your supplier's smart
  charging ready-by time to the schedule's next unplug, for example plug in
  02:00 and unplug 04:00 sets 04:00; plug in 06:00 and unplug 08:00 sets
  08:00. Only at scheduled plug-ins. Ready times are in 30-minute steps:
  Octopus Energy accepts any time of day, EDF Energy 04:00 to 11:00. While
  it's on, unplug times in the schedule are limited to those (the slot
  editor only offers those). E.ON Next's integration
  has no ready time setting. While it's on, the Automations tab outlines
  the schedule's slots in grey, and with Octopus Energy the schedule can't plug in for more than
  6 hours in any 24 (Octopus's daily smart charging cap): slots that go
  over are marked in red, and a change that goes over isn't saved (nor is
  putting a skipped slot back if that would go over). Any 24 hours from the
  previous day on count, so a charge earlier in the day counts too; if
  that's already over (e.g. after **Charge anyway**), slots can still be
  changed as long as it doesn't get worse. If Force schedule on
  supplier can't be turned on because of this (or an unplug time your
  supplier doesn't accept), the reason stays in red under the switch, with
  the slots to change marked in red, until it's fixed. With Force schedule
  on supplier off (or **Scheduling guards** overridden, Diagnostics ›
  Debug), there's no limit.
  At a scheduled unplug during a charging session, it waits for your
  supplier to stop the session itself (so it ends cleanly), then unplugs;
  if the supplier hasn't stopped it in time, it unplugs anyway. The wait
  is set under the switch (**Wait for the supplier at unplug**, 60 s by
  default, 0 to unplug straight away). The Overview shows "Unplugging by …"
  meanwhile.
  **Supplier's plan**: while the schedule has the car plugged in,
  the add-on checks your supplier's planned slots up to the ready time it
  set against the schedule. With plug-ins 16:00–18:00 and 20:00–22:00, the
  first stretch is checked from 16:00 (slots up to 18:00) and the second
  from 20:00 (slots up to 22:00). It's flagged if a slot runs past the
  unplug, or if the supplier's ready time was changed (e.g. in its app)
  from the one the schedule set. The check starts 5 minutes after the
  plug-in, to give the supplier time to plan, and follows the plan as it
  changes. The result shows on the Overview's Smart charging card and the
  Automations tab; a mismatch also as a red chip on the Overview, and in the
  log. The supplier's planned slots are outlined in its colour on the
  Automations tab (whether or not this is on).
- **Back-to-back slots** (one ends as the next starts, e.g. 06:00–12:00 and
  12:00–18:00): at 12:00 it unplugs straight away (without waiting for your
  supplier) and plugs back in after the re-plug **Unplugged for** time, so
  each slot is its own charge with its own ready time (12:00, then 18:00).
  With Octopus resetting its limit at 12:00, that's 6 hours each side.
  With Force schedule on supplier on and a reset time, a slot longer than
  the daily limit across the reset time (e.g. 08:00–18:00) is split there
  when it's saved, into two slots that work this way; so is a charge from
  auto plug-in, the car plugged in sensor or Charge now (including one
  joined with a scheduled slot).
- **Auto re-plug** (**Automations** tab): Octopus sometimes doesn't start a session after you plug
  in. When Plugged In has been on for the set minutes (default 10) with no
  session and the add-on is connected, it unplugs, waits the set
  **Unplugged for** seconds (default 30) and
  plugs back in, up to the set number of tries (default 3). It then gives up
  until the car is next unplugged or a session starts, and the wait starts
  again after each re-plug. If your supplier's smart charging plan is found
  (see the Overview tab), a planned slot counts too: it only re-plugs when
  nothing has been scheduled after the set minutes, not while it waits for
  a slot later on. A slot that's running now with no session is different:
  the status shows **Waiting for supplier** (amber) instead of Scheduled,
  and since Octopus may only start a session at the next half hour (e.g.
  after the add-on restarted mid-slot), the wait counts from the next :00
  or :30: with no session the set minutes after that, it re-plugs.
- **Start delay and ramp-up** (**Settings** tab, Simulated car): after
  StartTransaction (or resuming after a charging-profile pause) the simulated
  car waits the start delay (default 3s) before drawing current, then ramps
  linearly to full power over the ramp-up (default 5s). 0 and 0 = full power
  straight away. Not applied when power comes from your power sensor.

The schedule and auto re-plug are saved in `/data/automation.json`, auto
plug-in and your sensors in `/data/sensors.json`.

## How it works

1. The add-on connects to your supplier's OCPP server via WebSocket
2. It registers as a chargepoint (BootNotification)
3. It sends periodic heartbeats and meter values
4. When you "plug in" (the Plugged In helper or the web page), it reports
   `Preparing`
5. Your supplier creates a charge schedule and sends `RemoteStartTransaction`
6. The proxy sends `StartTransaction`, reports `Charging`, and sends meter
   values while the simulated car ramps up to full power
7. When the supplier ends the session, it sends `RemoteStopTransaction`
8. The proxy reports `Finishing`, sends `StopTransaction`, then returns to
   `Preparing`

If the connection drops, the add-on reconnects automatically, retrying after 5, 10
and 30 seconds, then every minute.

### While offline

Like a real charger, a dropped connection doesn't stop the session. Charging,
the energy register and any charging profile carry on, and the transaction
stays open. StartTransaction, StopTransaction and the session's MeterValues are
held in order and sent once the server accepts the BootNotification on
reconnect. Status updates and heartbeats aren't held; the current status is
sent after reconnecting instead. Held messages are saved to
`/data/offline_queue.json`, so they also survive an add-on restart. Up to
1,000 messages are held, and the oldest meter readings are dropped first.

If the add-on is stopped without warning mid-charge (power cut, crash), the
open transaction is closed on the next start. A StopTransaction with reason
`PowerLoss` is sent, using the last meter reading saved before the
interruption.

When the add-on is restarted mid-charge (an update, a restart from Home
Assistant), it leaves the session open by default
(**Continue session after a restart**, Settings › Controls): no StopTransaction or Unavailable, just
the connection closing, as when a charger loses its connection. When it's
back (within 10 minutes, with Plugged In still on) it reports Charging and
carries on with the same transaction, energy and charging profile.
Otherwise, or with the option off, the session is stopped with reason
`Reboot`, and your supplier starts a new one (Octopus at the next hour or
half hour). If the supplier sends a new RemoteStart instead of carrying on,
the old session is stopped (`Reboot`) and the new one started straight
away.

### StopTransaction readings

StopTransaction can include `transactionData` with the session's readings.
Two configuration keys choose what's included. Both are empty by default, as
on a Wallbox Pulsar Plus, so nothing is added unless your supplier sets them
with ChangeConfiguration:

| Key | Default | Readings |
|-----|---------|----------|
| `StopTxnSampledData` | *(empty)* | At the start, every `MeterValueSampleInterval`, and at the stop |
| `StopTxnAlignedData` | *(empty)* | On each `ClockAlignedDataInterval` boundary |

Long sessions are thinned to at most 100 readings, and the first and last are
always kept.

## Home Assistant entities

The add-on creates its own entities (no integration needed):

| Entity | Type | Description |
|--------|------|-------------|
| `input_boolean.ocpp_charge_proxy_plugged_in` | Helper (toggle) | Plugged In: turn on/off to plug in or unplug. Kept in step with the add-on's own Plugged In |
| `sensor.ocpp_charge_proxy_power` | Sensor | Current power draw (kW) |
| `sensor.ocpp_charge_proxy_energy` | Sensor | Cumulative energy (kWh, works with the Energy dashboard) |
| `sensor.ocpp_charge_proxy_current` | Sensor | Current draw (A) |
| `sensor.ocpp_charge_proxy_status` | Sensor | OCPP state (Available, Preparing, Charging...), or Scheduled / Waiting for supplier while plugged in with a supplier slot planned / running |
| `sensor.ocpp_charge_proxy_current_limit` | Sensor | Current the charger uses (A), with your max (`max_amps`) and the supplier's limit (`provider_limit_amps`) as attributes |

- The sensors are posted by the add-on, so they can't be renamed in the UI and
  aren't grouped under a device. They show as unavailable while the add-on is
  stopped, and come back when it (or Home Assistant) restarts.
- The Plugged In helper is a normal helper. While the add-on is stopped,
  toggling it does nothing, and it's set back to the add-on's value when the
  add-on starts.
- If the old OCPP Charge Proxy integration (1.x) is still installed, the
  add-on leaves the sensors alone until you remove it (Settings > Devices &
  services). `sensor.ocpp_charge_proxy_energy` keeps its entity ID, so its
  Energy dashboard history carries on.
- Your power and SoC sensors are set up on the web page's **Settings**
  tab, and auto plug-in and the car plugged in sensor on the **Automations** tab; the add-on
  reads them through Home Assistant's API.

## Web page

Open the add-on from the sidebar (or **Open Web UI**). It updates live and
follows your Home Assistant theme. Settings save as soon as you change them.

- **Header:** a health dot left of the title (green / amber / red) that
  opens Diagnostics › Health.
- **Overview:** state, power, current, SoC and energy; the current session;
  **smart charging** (the charge slots your supplier plans, found
  automatically from the Octopus Energy, EDF Energy or E.ON Next integration, also
  shown along the top of the chart);
  and a chart of power, current (with your max and the supplier limit) or
  SoC over the last 30 minutes to 24 hours, or 14 days. Drag across the
  chart or scroll over it to zoom (double-click or **Reset zoom** to go
  back). The charts and the
  energy per day are read from Home Assistant's history of the add-on's
  sensors (keep them recorded): 10-second detail for 24 hours, then
  5-minute points while HA keeps them (10 days by default, `purge_keep_days`)
  and hourly beyond that.
- **Sessions:** energy and time spent charging per day for the last 14
  days (click a day to show only its sessions), and the last 20 charging
  sessions (energy, duration, peak power, what ended them; transaction ID
  and ID tag in the details; tagged with your supplier's name, e.g.
  **Octopus Energy slot**, when the whole session was in its dispatch
  slots, or **Partly Octopus Energy slot** when only some was), kept across restarts,
  and the last 20 plug-ins that never got a session: when, for how long, who
  plugged in, and whether auto re-plug gave up on it or it was unplugged
  first.
- **Automations:**
  - **Charge now** (at the top): click how long to plug in for (1, 2, 3, 4, 6, 8 or 12
    hours). It plugs in straight away and adjusts the schedule the same way
    auto plug-in does (see [Auto plug-in](#auto-plug-in)): a one-off slot
    in the schedule below, the ready time set to its end, and it unplugs
    then. With a daily limit (Octopus: 6 hours) and Force schedule on
    supplier on, if it would take any 24 hours (the previous 24 included)
    over the limit, it asks first, saying what would change; **Charge
    anyway** then goes ahead.
  - The plug-in schedule (see below), with the last 3 days and the next 7
    of when it has the car plugged in; Force schedule on supplier; auto
    plug-in, the car plugged in sensor and auto re-plug.
- **Settings:** controls for Plugged In, max current and **Continue session
  after a restart**; the simulated car's start delay and ramp-up; your
  power and SoC sensors, with their live values; the **Voltage** card (a
  voltage sensor, or a set supply voltage; 230 V if neither) used to turn
  amps into kW for the simulated power and the ~kW figures; and **Your
  supplier**, for when what's found automatically isn't right, or your
  supplier's rules change:
  - **Smart charging sensor:** the dispatching sensor with its planned
    slots (Octopus Energy / EDF Energy), or E.ON Next's schedule sensor.
  - **Ready time:** the target time entity Force schedule on supplier sets,
    and the **Ready times** it accepts (automatic: what the entity offers,
    any half hour for Octopus, 04:00–11:00 for the others).
  - **Daily limit:** the most hours of smart charging your supplier
    schedules in a day (automatic: 6 for Octopus Energy, none for the
    others; 0: no limit). Used for the schedule, auto plug-in and Charge now
    while Force schedule on supplier is on. **Resets** says when it starts
    again: every day at a set time (automatic for Octopus Energy: 12:00, so
    6 hours before midday and another 6 from midday are fine), or rolling
    (automatic for the others): no more than the limit in any period of the
    **Reset frequency** (24 hours unless changed, 1–168 hours). If a change
    means the schedule no longer fits, the card offers to clear the
    schedule's charging slots (no-charging times stay), put the setting
    back, or keep both and shorten the slots yourself. With a reset time, "any 24 hours" below means each day from
    that time, and a charge across it can be longer: 08:00 for 12 hours is
    08:00–18:00 (4 hours before 12:00, then 6 after).
  Each shows what's in use, and whether it was found or picked.
  The automatic values come from `src/suppliers.json` in the repository:
  for each supplier, its daily limit (`daily_limit_h`, null for none), when
  it resets (`limit_reset`: a time, or `"rolling"`), the ready times its
  app accepts (`ready_times` from / to) and how its smart charging sensor is
  found. Edit that file and rebuild the add-on if a supplier changes its
  rules; anything set on this tab still wins. If the file can't be read,
  the built-in values are used and the log says why.
- **Diagnostics**, in two parts:
  - **Health:** version, uptime, reconnects and the last drop's reason,
    heartbeat and clock offset, the Home Assistant link and the add-on's
    Home Assistant entities, and any held messages. At the bottom,
    **Supplier**: what your supplier has set: charging limits, charging
    profiles drawn as a timeline, the local authorisation list and every
    configuration key.
  - **Debug:** tools for testing and bug reports:
    - Test values: a power override (reported instead of the simulation)
      and a test SoC.
    - **Send a message** now as the charger: a StatusNotification (any
      status; it doesn't change the charger's own state), MeterValues, a
      Heartbeat or a BootNotification, with the supplier's reply.
    - **Drop the connection** for a number of seconds (charging carries on
      and transaction messages are held, as on a real dropout), or
      **restart the add-on** (through the Supervisor; a session carries on
      after it with **Continue session after a restart** on).
    - **Scheduling guards** (off by default): override them to let the
      schedule, auto plug-in and Charge now plug in for more than Octopus's
      6 hours a day while Force schedule on supplier is on.
    - **Logs:** the log level (Debug, Info, Warning), kept across
      restarts, and the last 300 OCPP messages both ways, kept across
      restarts (with a marker where the add-on restarted), with a filter,
      full JSON on click and a Copy button for sharing.
    - **Diagnostics bundle:** one JSON file with the state, schedule,
      sessions, supplier's plan and settings, health, recent messages, log
      lines and options (password and most of the chargepoint ID hidden).
    - **Clear data:** the session history or the message log.

Times on the page are 24-hour. Longer explanations are behind **More**
links.

## Getting your OCPP credentials

Your supplier will give you three values needed to connect:

- **Server hostname** — the OCPP WebSocket endpoint
- **Chargepoint ID** — your unique chargepoint identifier
- **Password** — authentication password

You may also need to set `charger_model` and `charger_vendor` to match a
charger model your supplier supports. The defaults work for suppliers that
accept Wallbox chargepoints.

Check your supplier's app or documentation for how to obtain these credentials.
