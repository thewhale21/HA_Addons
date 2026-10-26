# Home Assistant Add-on: OCPP Charge Proxy

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

Get your smart tariff's cheap charging slots **without a compatible
charger**. The add-on pretends to be a smart charger (an OCPP 1.6
chargepoint) and connects to your energy supplier. When your supplier
schedules a charge, the add-on tells Home Assistant, and your automations
switch on whatever actually charges the car: a smart plug, a charger with
its own integration, a granny lead on a relay.

Works with **Octopus Energy** (Intelligent Octopus), **EDF Energy** and
**E.ON Next**, and any other OCPP 1.6J back office.

- **Plugged In** switch, schedule, **Charge now**, auto plug-in on low SoC
  or when the car's cable is connected, and auto re-plug if the supplier
  doesn't start a session.
- Sets your supplier's **ready time** for you, keeps within Octopus's 6
  hours a day, and checks the supplier's plan matches your schedule.
- Reports real power and your car's SoC to the supplier if you have the
  sensors, otherwise simulates a car charging.
- Rides out restarts and dropped connections like a real charger.
- A web page in the sidebar: live status, the supplier's planned slots,
  charts, session history, the schedule and diagnostics.

[Full documentation][docs] (also the add-on's **Documentation** tab).

---

## How it works, in one minute

```
 Your supplier  ⇄  OCPP Charge Proxy  →  Home Assistant  →  your charger / smart plug
 (schedules         (a virtual           (sensor.ocpp_charge_proxy_
  charging)          chargepoint)          status = Charging)
```

1. You **plug in** (the Plugged In switch, the schedule, or automatically).
2. The add-on tells your supplier a car is waiting.
3. Your supplier plans its cheap slots and starts a charging session.
4. The add-on's status becomes **Charging** and its power rises above 0.
5. **Your automation** turns the real charger on, and off again when the
   session ends.

The add-on never switches anything itself: step 5 is up to you (see the
example automation below).

## What you need

- Home Assistant OS or Supervised (add-ons need the Supervisor).
- OCPP connection details from your supplier: a **server hostname**, a
  **chargepoint ID** and a **password**. Your supplier gives you these when
  you register a charger with its smart tariff; its app or help pages say
  how.
- Something Home Assistant can switch to charge the car.
- Optional, but recommended:
  - your supplier's integration (e.g. **Octopus Energy** from HACS), so the
    add-on can see the planned slots and set the ready time;
  - a sensor for your car's **SoC** (%), from the car's integration;
  - a **power** sensor (W or kW) for what the car really draws;
  - a **car plugged in** binary sensor (e.g. the car's "cable connected").

## Install

1. Add this repository to Home Assistant:
   **Settings › Add-ons › Add-on store › ⋮ › Repositories**, and add
   `https://github.com/thewhale21/HA_Addons`.
2. Find **OCPP Charge Proxy** in the store and click **Install**.
3. On the **Configuration** tab, fill in your supplier's details (below)
   and click **Save**.
4. **Start** the add-on and turn on **Show in sidebar**.
5. Open it from the sidebar. The header's dot goes green once it's
   connected to your supplier.

## Configuration (add-on options)

Only the first three are needed.

| Option | What to put |
| --- | --- |
| `server_hostname` | Your supplier's OCPP server hostname |
| `chargepoint_id` | Your chargepoint ID |
| `password` | Your OCPP password |
| `charger_model` / `charger_vendor` | What charger to report. The defaults (a Wallbox Pulsar Plus) work with Octopus; change them only if your supplier wants a different model |
| `charger_serial` | Leave empty: one is made up the first time it starts |
| `firmware_version` | The firmware to report (leave as it is) |
| `initial_energy_wh` | Moving from another charger? Its meter reading in Wh, so the energy total carries on. Used once |

Everything else is set on the add-on's web page and saved as you change it.

## Set it up on the web page

Work through the tabs once, top to bottom.

**Settings tab**

1. **Controls:** your charger's **max current** (A), so the power reported
   is about right. Leave **Continue session after a restart** on.
2. **Sensors:** pick your car's **SoC sensor** (sent to the supplier, and
   the session pauses when the car's full) and a **power sensor** if you
   have one (otherwise power is simulated).
3. **Voltage:** a voltage sensor, or your supply voltage (230 V if left
   alone).
4. **Your supplier:** usually found by itself from your supplier's
   integration. Check it shows your supplier's smart charging sensor and
   ready time; pick them here if not.

**Automations tab** (all optional; pick what suits how you charge)

| Feature | Use it if… |
| --- | --- |
| **Schedule** | You plug in at set times, e.g. every night 23:30–05:30. Click or drag across a day to add a slot |
| **Random start delay** | You'd rather your slots didn't plug in at exactly the same time every day: each plugs in up to the minutes you set after it starts |
| **Force schedule on supplier** | You want the supplier's ready time set to the schedule's unplug time for you. It also keeps the schedule within your supplier's daily limit, if it has one (Octopus: 6 hours from 12:00 to 12:00) |
| **Charge now** | You want a charge straight away for 1–12 hours |
| **Auto plug-in** | You want it to plug in when the car's SoC drops below a level |
| **Car plugged in** | You have a "cable connected" sensor and want it to plug in when you connect the car. Its switch turns it off without forgetting the sensor |
| **Auto re-plug** | Your supplier sometimes doesn't start a session (Octopus does this): it unplugs and plugs back in for you |
| **Off-peak times** | Times nothing should be scheduled, e.g. off-peak hours when the car charges anyway |
| **Saving sessions** | You take part in saving sessions (Octopus, E.ON Next, EDF): it reads them from a calendar, keeps charging out of them (starting slots earlier) and can charge for a few hours before each |

## Make it switch your charger

The add-on reports what your supplier wants; an automation does the
switching. Replace `switch.car_charger` with your charger or smart plug:

```yaml
alias: Car charger follows the supplier
triggers:
  - trigger: state
    entity_id: sensor.ocpp_charge_proxy_status
    to: Charging
    id: "on"
  - trigger: state
    entity_id: sensor.ocpp_charge_proxy_status
    from: Charging
    id: "off"
actions:
  - action: "switch.turn_{{ trigger.id }}"
    target:
      entity_id: switch.car_charger
mode: queued
```

## Its Home Assistant entities

| Entity | |
| --- | --- |
| `input_boolean.ocpp_charge_proxy_plugged_in` | **Plugged In**: turn on to plug in, off to unplug (use it on a dashboard or in automations) |
| `input_button.ocpp_charge_proxy_charge_now_1h` … `_12h` | **Charge now** for 1, 2, 3, 4, 6, 8 or 12 hours: press one (or `input_button.press` it from an automation) to do what the web page's Charge now button does |
| `sensor.ocpp_charge_proxy_status` | Available, Preparing, **Charging**, Scheduled, Waiting for supplier… |
| `sensor.ocpp_charge_proxy_power` | Power now (kW): simulated, or your own power sensor's reading |
| `sensor.ocpp_charge_proxy_energy` | Energy total (kWh), for the Energy dashboard |
| `sensor.ocpp_charge_proxy_current` | Current (A) |
| `sensor.ocpp_charge_proxy_current_limit` | The current in use, with your max and the supplier's limit |

For example, charge for 2 hours when you get home:

```yaml
action: input_button.press
target:
  entity_id: input_button.ocpp_charge_proxy_charge_now_2h
```

## Troubleshooting

- **The dot is red / it won't connect:** check the three connection
  options for typos (Configuration tab), then **Diagnostics › Health** for
  the reason, and **Diagnostics › Debug** for the log.
- **Plugged in but no charge:** the Overview's **Smart charging** card
  shows whether your supplier has planned a slot. Octopus can take a few
  minutes, and only starts at the hour or half hour; turn on **Auto
  re-plug** if it often doesn't start at all.
- **The supplier's slots or ready time aren't found:** install your
  supplier's integration, or pick its sensors under Settings › Your
  supplier.
- **Asking for help:** **Diagnostics › Debug › Diagnostics bundle**
  downloads one file with everything needed (your password and most of
  the chargepoint ID are hidden). Attach it to a
  [GitHub issue](https://github.com/thewhale21/HA_Addons/issues).

[docs]: https://github.com/thewhale21/HA_Addons/blob/main/ocpp_charge_proxy/DOCS.md
[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
