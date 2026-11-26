# Handover notes

Context for picking this repository up in a new Claude session or
subscription. `CLAUDE.md` has the working rules; this file has the
background: what each add-on does, how the owner uses them, what was
decided and why, and what's still open.

**Last updated:** 26 Nov 2026 (neighbourhood_view 0.7.0).

**Keep this file current.** Whoever changes the repository (any AI agent
or person) updates this file in the same commit when the change affects
anything below, and bumps the "Last updated" line.

## The owner and how they work

- Matt runs everything inside **Home Assistant** (HA OS, add-ons from this
  repository: `https://github.com/thewhale21/HA_Addons`). Windows PC; the
  repo lives at `C:\Users\Matthew\VScodeRepo\HA_Addons`.
- **The owner pushes.** Commit and tag each release, then give one
  paste-ready PowerShell line, starting
  `cd C:\Users\Matthew\VScodeRepo\HA_Addons;`, with every tag not yet
  pushed: `git push origin main <tags>`.
- PowerShell must be paste-ready (pasted straight into a window, not saved
  as a .ps1).
- Writing style on pages, docs, changelogs and logs: plain British English,
  short sentences, no jargon, "you/your". Examples with real times
  (e.g. "15:30–21:30 with an 18:00–19:00 session: 14:30–18:00 and
  19:00–21:30"). Match the existing tone of DOCS.md and the page's notes.
- Never put credentials in code, the repo, logs or the page (the owner
  once pasted an Octopus API key in chat; it must never be written
  anywhere). Add-ons take keys from their options only.
- The owner often asks follow-up questions mid-task ("question, not an
  ask"): answer questions without changing code unless asked.

## Home energy setup (what the add-ons serve)

- **Octopus Energy, Intelligent Octopus Go (IOG):** off-peak 23:30–05:30
  (about 7p); dispatches at the off-peak rate; Octopus's limit is 6 hours
  of smart charging in any day, resetting at 12:00. Export on Agile
  Outgoing (rates out about 16:00 for the next day).
- **Sigenergy:** two inverters, a house battery and a V2G/DC car charger
  (the EVDC), run by **Predbat** in Home Assistant.
- **The OCPP Charge Proxy is a virtual charger** (reports as a Wallbox
  Pulsar Plus, PLP2) connected to Octopus as the IOG device. Octopus
  dispatches to it; the real batteries/car charge from those cheap slots
  through Predbat. Max current is set to 6 A (the lowest a real Wallbox
  goes; below 6 A was discussed and rejected).
- **Predbat** (upstream, `apps.yaml` with `num_cars: 3`): car 0 is the OCPP
  virtual charger (IOG slots, `octopus_intelligent_slot`, a car charging
  rate cap of 0.1 kW so it adds no load), car 1 a Hypervolt, car 2 the
  Sigenergy EVDC. Predbat plans the house battery around the dispatches
  (confirmed working: dispatch 12:30–14:00, battery charged to 100%).
- **Free electricity sessions** come from the Octopus Energy integration's
  Power Up calendar (`calendar.octopus_energy_<account>_octoplus_power_up`,
  disabled in HA until enabled); saving sessions from its Power Down
  calendar. Axle Energy's sensors exist but have been unavailable.
- **Coming soon:** an Octopus **Cosy** heat pump (see "Ideas" below).

## Add-ons in this repository

| Folder | Version | Notes |
|---|---|---|
| `ocpp_charge_proxy` | 2.120.1 | The main one: below. |
| `octopus_charge_pack` | 0.10.8 | Octopus API helpers; 0.10.8 drops old `device_id`/`poll_seconds` options via the Supervisor API (`POST http://supervisor/addons/self/options`). |
| `sigenergy_evdc_soc_range_manager` | 0.44.0 | "SigEnergy DC Charger": keeps the EVDC car between limits on a weekly schedule. Limits are named **Maximum charge** and **Keep at least**; an entry can be Maximum charge / Keep at least / Both / Charge only / Discharge only (one-way entries stay within the limits); entries may overlap; start == end means 24 hours; the week view has three lanes (one-way entries in the middle). The Overview's Car SoC chart shows charge/discharge only as a coloured strip along the bottom (0.43.0; points in `soc_history.json` carry a 6th value, "charge"/"discharge", only then). Notifications (0.44.0): the notify service box suggests HA's notify services (`/api/notify_services`) with a Test button; **What to send** (`notify_level`: info = everything incl. starts/stops, warning, error, none; default info); warnings/errors in its log are sent too (`src/log_notify.py`, ported from OCPP's). about 105 tests (test_api needs pytest-asyncio; one notify test needs aiohttp). |
| `tigo_solar` | 0.7.0 | Tigo panel data: roof view (reclaimed in brackets), drag-to-select chart, quick-select per string, per-panel estimates every minute (system power shared by interpolated reading shares), backfill of real 15-minute per-panel readings via Tigo's `lastvalue` (`resourceId=lastValue-{date}-{pin|reclaimedPower}-{HH:MM}`, about 2 requests per slot, 3 s apart; trusted after 3 answers within 35%/30 W of system power, off after 3 misses), fixed scale, hover tooltip, reclaimed %, "By the time of day" and "Through the year" heatmap / 3D surface with Month/Year and 3D zoom. 22 tests. |
| `neighbourhood_view` | 0.7.0 | New (26 Nov 2026): an isometric SVG drawing of the streets (150 m by default, a setting) around your home from OpenStreetMap (postcodes.io for the postcode, Overpass for buildings/roads/areas/trees and the house-number lookup), as the add-on's page and a dashboard card. See "Neighbourhood View" below. |
| `heat_loss_calculator`, `predbat_dashboard`, `stellantis_ev_stats` | 0.7.1, 0.3.2, 0.3.2 | Not worked on recently. |
| `addon_template` | 0.1.7 | Start new add-ons with `python scripts/new_addon.py`. |

## OCPP Charge Proxy: how it fits together

`ocpp_charge_proxy/src/`:

- `client.py` (OCPP 1.6 charge point talking to Octopus), `charger_sim.py`
  (simulated power; `VALID_CURRENT_SETTINGS` 6–32 A), `charging_profile.py`.
- `automation.py` (about 3,800 lines): the plug-in **schedule** (weekly and
  one-off times, skips), auto re-plug, auto plug-in / Charge now / car
  plugged in charges, **off-peak times**, **saving and free sessions**
  (`sync_saving_sessions`, `_apply_sessions`, `_move_for_session`), the
  **automatic schedule** (`sync_auto_schedule`, `set_export_rates`).
- `auto_schedule.py`: the planner itself, pure (no I/O). Modes:
  `cheapest` (where exporting pays least), `before` (before the high
  exports), `value` ("Where it earns the most", `best_value` dynamic
  programme).
- `saving_sessions.py`: calendar/sensor parsing (saving, free, Axle).
- `ha_link.py`: Home Assistant websocket, settings (`validate_settings`,
  `default_settings`, saved in `/data/sensors.json`), reading calendars
  (`read_saving_sessions`, `read_free_sessions`, `read_axle_sessions`).
- `__main__.py`: the loops (`saving_sessions_loop` reads the three session
  sources every 5 minutes; `auto_schedule_loop`; log notifications).
- `log_notify.py`: Settings › Notifications › "Problems in the log".
- `static/index.html`: the whole web page (one big file, about 5,500 lines).
- **Bump `AUTO_PLAN_VERSION` in `automation.py` (now 17) whenever the
  planner's rules change**, so existing plans are planned again.

### Recent behaviour worth knowing (2.98–2.107)

- **Saving sessions:** hatched in the supplier's colour (Octopus purple,
  EDF yellow, E.ON red, else violet). "No charging during a session" moves
  your slots before it (keeping their end); "Plug in before" adds a charge.
- **Free electricity sessions** (2.100): records are kept in
  `saving_sessions` with `"kind": "free"` and ids prefixed `free-`; always
  off-peak times. **Your slots in a session**: Before / After / **Bank it**
  (2.107: just cut the session out of the slot, nothing moved, leaving the
  time free in the 6-hour limit). The automatic schedule always plans
  around them in the next best half hours. Plugged in by hand as one
  starts, it unplugs (as at an off-peak time). Green hatching.
- **Axle Energy** (2.101): its own card. Export events = saving sessions,
  import events = free sessions (optional). Unavailable sensors keep
  already-found events (`unread` by supplier name "Axle Energy").
  Import events follow the free sessions' Before/After/Bank setting
  (2.103.1; a separate Axle setting was added in 2.103.0 and removed).
- **Where it earns the most** (value mode): every charge costs the
  cheapest import rate (right for IOG); export rates only count when the
  battery sells. Off-peak times and free sessions count as filling the
  battery (2.104). It **looks back** (setting "Look back", default 6 h,
  2.105) from empty, replaying what really ran and the best exports since,
  instead of starting empty now. It doesn't read the real SoC (on purpose:
  stable plans) and doesn't count house use unless a house load sensor is set (2.114).
- **High export half hours** are only marked where they pay more than the
  day's lowest (2.105.1). Before mode gives no charge before a run that
  straight follows an off-peak time or free session.
- **Over the daily limit** (start or end of the next slot): auto plug-in's
  setting covers auto plug-in and Charge now; the car plugged in sensor has
  its own (2.106, `plug_trim_from`).
- **Populate schedule** was renamed **Populate schedule from load**.
- **The plan as a table** (2.110; on the card from 2.112): Automations › Automatic schedule › Plan is a fold-out text table of the plan, half hour by half hour (`Automation._plan_table`, kept in `auto_plan["table"]` and saved with it in automation.json (2.112.1: before, a restart left it empty until the next plan); `GET /api/auto_table`; the page reads it again when `planned_at` changes or a minute on). It replaced the Charging / Your slots / High export / Off-peak lists. Battery % and actions come from `best_value(..., trace=True)` (value mode only). Half hours of your slots (entries with no source, skips ignored) that aren't plugged in are tagged "your slot, skipped".
- **The estimate's 23:00 gap** (2.112.2): HA's export rates for today start at midnight while Octopus's run 23:00–23:00, so a copy of the day before had nothing for 23:00–00:00. `auto_schedule._copy_of` now falls back to `_rates_seen` (yesterday's, remembered 2 days), then the half hour before's.
- **Plan again now** (2.111): a button above the automatic schedule's plan (`Automation.request_replan`, `POST /api/auto_replan`). It clears the plan key and wakes the auto loop, which reads the rates again and plans. If a block is running it waits until the block ends (the answer gives `waits_until`).
- **Tomorrow's rates from the wholesale prices** (2.109): until Octopus publishes tomorrow's export rates (~16:00), the automatic schedule estimates them from Nord Pool's N2EX UK day-ahead prices (~10:00; `src/future_rates.py`, setting `auto_future_url`, default the same URL as Predbat's `futurerate_url`, DATE = day; empty = copy of today's). `auto_schedule.fit_wholesale` fits today's real export rates to today's wholesale (a × wholesale + b, + c 16:00–19:00; needs 12+ half hours, a in 0.2–3), `estimate_wholesale` applies it; falls back to a copy. On the owner's real 22 Nov data the fit was within ~0.5p on average. The estimate is hashed into the plan key (`how["est"]`), so new wholesale prices trigger a replan. Import rates (IOG) are still copied.
- **Splits at the 12:00 reset** (2.108): with Force schedule on supplier, every slot across the limit's reset is split there (unplug and plug back in, each part with its own ready time), not only slots longer than 6 h. As one charge, Octopus planned it all in the day it started (the owner lost 30 min of 11:00–12:30 when that day had 1 h left).

### Known limitations (deliberate, or left for now)

- **Automatic schedule card layout** (2.120): status line `#as-sum` + Plan again now, the table fold `#as-plan`, then `details.sec` sections (`#as-sec-charge`, `-batt`, `-house`, `-rates`, `-show`), each with a summary line filled by `asSummaries()` (called from `drawAutoSched`); open state in localStorage. `drawAutoSched` returns until both `sim.edit` and `auto.data` are in (2.120.1: else on page load it looked off and wrote "Off: reading the rates…" over the table); with no plan it resets `planTableAt` so the table is read again when one comes. New settings go in the matching section, with a short note and detail behind `details.more`.
- **Axle export event bonus** (2.119): setting `auto_axle_bonus_p` (default 100p/kWh) → `Automation.axle_bonus_p`; `_with_axle` adds it to the export rates (known and estimated, after the estimate is made) in Axle's export events (`saving_sessions` with supplier starting "Axle", not free). In the plan key (`how["axle"]`).
- **Slot moved to have started** (2.117): `set_schedule` / `set_skips` (un-skip) note `in_plug_window()` before the change; if after it there's a window that wasn't (`_note_started`), `started_now` is set and `automation_loop` plugs in (and sets the ready time), as `turned_on` does. The slot's plug key goes in `auto_plan["yours"]` so the automatic schedule doesn't skip it again. An edit to a slot already going doesn't trigger it (so a hand unplug stays). 2.118: the reverse, `ended_now`: a change that ends the window going (end before now, skipped, deleted) unplugs at once unless a charge window is going.
- **House load** (2.114): settings `auto_load_entity`, `auto_battery_kwh`, `auto_battery_entity` (2.115: the size from a sensor, read every 5 min via `all_states`, used while it reads, else the typed size; `house_load.battery_kwh`), `auto_load_drain`, `auto_load_kw` (2.116: an average typed in, flat all day, used without the sensor or while it can't be; `house_load.choose`). `src/house_load.py` reads 7 days of hourly statistics into 48 half-hour kW averages (every 6 h, in the auto loop); `Automation.house_profile`/`battery_kwh`/`load_drain`, hashed into the plan key (`how["house"]`). `best_value(house=, unit_kwh=, drain=)`: an empty `dear` half hour costs kWh × import p (score: ÷ kWh per unit); with drain the battery runs in quarter units and the house takes its use first. Trace rows are (t, act, %, house p); the table's row index 9 is house p. The owner earlier declined a flat "% an hour" drain; this sensor-based one was asked for.
- Value mode ties (2.113): `best_value`'s score is (earned, -half hours empty in `dear`, -charges, -separate charges); `dear` = half hours still to come that aren't forced (not off-peak/free session/plugged in). So of equal plans it keeps the battery from sitting at 0% where the house would import at the peak rate. Only a tie-break: it never costs earnings (a real house-use cost was declined earlier).
- Ties in value mode fall arbitrarily (e.g. charging 07:30 vs 05:30 earned
  the same); on a **flat export rate** slots can shift on each replan.
- Value mode cycles the battery whenever export beats about 7.8p (no
  battery wear or house use modelled).
- The planner's "Automatic schedule planned" log line doesn't say why it
  planned again (offered, not done).

## Neighbourhood View (new)

`neighbourhood_view/` (from `addon_template/`). The owner asked for: Settings with postcode + house
number; an Overview drawing the surrounding streets with the house in the middle, in the style of a
low-poly isometric map; and a dashboard card that's the only card on a page and scales to any
device. Choices the owner made: OpenStreetMap data, a fixed isometric picture (not 3D/rotatable;
quarter turns are allowed), about 250 m around, add-on and card together.

- `src/scene.py` (pure): Overpass queries, projection to metres (x east, y north) around the home,
  clipping to a 500 m square, building kinds/heights (houses get a gable roof on their min-area
  rectangle), roads/rails/areas/water, synthetic trees (parks, woods, residential streets; seeded
  by position so they don't move), `find_address` (house number + postcode within 400 m),
  `pick_home`. `tests/osm_sample.py` is a made-up neighbourhood in Overpass's form.
- `src/places.py`: postcodes.io + Overpass (two servers), `SceneStore` (/data/scene.json, made
  again after 30 days, on an address change or Refresh), `picked_home` (a building clicked on the
  Overview: saved as `picked` {id, lat, lon} in app settings; the map is re-centred on it).
- `src/static/neighbourhood-view-card.js`: the renderer (`window.NeighbourhoodView.render/draw/fit`,
  axonometric: yaw 30° + quarter turns, 35° elevation, painter's order by depth) and the card
  `custom:neighbourhood-view-card`. The page loads it from `./card.js`. `fit()` zooms in around
  the pin (up to 2.4×) when the box's shape is far from the drawing's (phones upright).
- The card reads `api/scene` through ingress: `supervisor/api` websocket calls for `/addons`
  (slug ending `_neighbourhood_view`), `/addons/<slug>/info` (ingress_url) and `/ingress/session`
  (cookie `ingress_session`, path /api/hassio_ingress/), so it needs an admin user. Config
  options: `label`, `height`, `addon`, `url`. In a panel view (`isPanel`) it fills
  100vh minus the header.
- `src/card_install.py`: writes the card to `/homeassistant/www/neighbourhood-view/` (config.yaml
  maps `homeassistant_config` rw) and adds/updates the Lovelace resource
  (`/local/neighbourhood-view/neighbourhood-view-card.js?v=<version>`) over the websocket.
- Not tested against the real services (the cloud sandbox couldn't reach postcodes.io or
  Overpass); the UI was checked with a stub server and Playwright. Icons are still the template's.
- 0.2.0 ("like a video game", the owner's aim: replicate their reference image with their street):
  per-building looks seeded by OSM id in the renderer (`rnd(id, salt)`): house wall/roof palettes,
  gable or hip roofs, chimneys, windows per storey + a door; blocks with window grids, shop fronts
  (glass + coloured fascia), rooftop boxes. Python: house storeys by id hash when untagged
  (`HOUSE_STOREYS`), tree sizes 0.6-1.8, parked cars (`_cars`, `scene["cars"]`: x, y, angle, colour).
  Renderer: pavements (`PAVE` 2.8 m each side + kerb) and centre lines, three tree kinds,
  `box()` helper, zoom (+/−, `NeighbourhoodView.zoom`, steps 1-6x around the pin; the pin keeps
  its screen size).
- 0.3.0: the board is a chunk torn out of the ground: `outline(H, seed)` in the renderer (a rounded
  square, R 34 m, inset by smooth noise + jitter + the odd bite; per-point earth depth and soil
  share; seeded by the scene's lat/lon), drawn as turf/soil/rock side faces (visible ones, back
  first) under a top polygon with a turf stroke; it's also the clipPath, and buildings with any
  corner outside it (and trees/cars outside) aren't drawn (never the home).
- 0.4.0 (after the owner's first real map, RG31: terraces looked like fins, and it wanted to be
  closer): `_face_streets` turns each gable rect so the ridge runs along the nearest street
  (within 40 m, grid of 40 m cells); zoom starts at 2.6× (`ZOOM_DEFAULT`, key
  `neighbourhood-view-zoom2`, steps to 9×), and the box-shape zoom is √'d on top of it (max 10×).
- 0.5.0 ("more green"): base ground is lawn (`C.ground`), landuse retail/commercial/industrial
  etc. → area kind `yard` (hard standing); `_garden_trees` (16 m jittered grid, 33%, off roads +
  pavements, buildings, paved/yard/water/pitch areas); a grass verge on minor streets.
- 0.6.0: weather + people + night. `ha_link.ENTITY_KEYS` = `weather_entity` and `person_1`..`person_6`
  (the template's example entity is gone); `sun.sun` always watched under HA. `src/live.py`
  `compute()` → `state.live` {night, weather, people} for the page; `/api/scene` also returns
  `entities` so the card builds the same itself (`liveFrom(hass.states)`, redrawn when it changes;
  card options `weather`, `people`). Renderer: `CTX` (night, per-building lit share, smoke);
  night = regex tint of every #rrggbb except the lit-window colours `LIGHT`/`LIGHT2`; faces of
  who's home above the pin; HTML overlays (`overlays()`: rain/snow/fog/cloud/sun/flash CSS layers
  and chips). The owner's day-time idea was open: chimney smoke + faces were chosen.
- 0.7.0: map size setting `radius` (default 150 m, was 250; 50-500); `SceneStore.fits` compares
  `half`, so a saved map of another size is made again. Other places: settings `places` = up to 6
  `{zone, side (left/right/up/down), radius 30-400}`; `__main__.make_places` reads zones from HA
  states and `places.fetch_area` makes each scene (no house), kept in `/data/places.json`
  (`PlaceStore`, keyed by zone; refetched when the zone moves, its radius changes or after 30 days).
  `/api/scene` returns `places: [{zone, side, name, scene}]`; `/api/places` (POST) and `/api/zones`.
  Renderer: `island()` draws one scene, `draw()` composes home + places (left/right in columns as
  tall as home, up/down in rows as wide, scaled down to share), `whereabouts()` places people (home
  → GPS on any island → zone name = their state → away), tapping an island (`.nvisl`) focuses
  `fit()` on it. People's `lat`/`lon` added to live.
- Ideas not done: road names, building colours from OSM tags, live overlays (e.g. the car, the
  battery).

## Testing and environment notes

- Tests: `cd ocpp_charge_proxy && python -m pytest tests/` (about 560;
  needs `pip install -r requirements-dev.txt`: `ocpp`, `websockets`,
  `aiohttp`, `pytest-asyncio`, `pytest-aiohttp`). In the last sessions the
  cloud sandbox couldn't install `ocpp`/`websockets`, so `test_client.py`,
  `test_integration.py`, `test_api.py` and one app-settings test were not
  run; everything else passed. Run the full suite locally when you can.
- The page has no tests: check its script parses (e.g. with node, `new
  Function()` over each `<script>`), and look at it in a browser.
- Simulation scripts used to check the planner against many rate shapes
  were throwaway (not committed); `tests/test_auto_schedule.py` has the
  real-rate cases (the owner's Sunday morning, a 16:00–19:00 peak, etc.).

## Open ideas and offers (not started)

- **Cosy heat pump add-on, local control.** No documented local API. Two
  routes researched: (1) the Cosy Hub's **installer-mode web page** (could
  be driven like a browser once its requests are known: capture a HAR file
  and check whether it's reachable from the home network); (2) **read-only
  RS485 sniffing** of the Hub-to-outdoor-unit Modbus bus (19200 8N1),
  as `github.com/stuartj1-1981/CosyLocal` does. The owner has an
  **M5StickC** (ESP32) from an ESPAltherma project: add an RS485 unit on
  the Grove port (RX G33, no TX) and run ESPHome with
  `oxan/esphome-stream-server` on port 8899 as a listen-only bridge. Not
  started; waiting for the heat pump to be installed.
- Value mode: a tie-break that keeps charging out of high export half hours
  when it earns the same; a house-use drain setting.
- Log the reason for each automatic-schedule replan.
- Tigo: a "partly estimated" label, per-day backfill log lines, a faster
  backfill gap, a data retention setting.
- Sigenergy: switch the "Discharge only" quick hold to the new
  direction-only mode.
- Predbat: the owner went back to upstream Predbat (see below); possible
  upstream suggestion: an option to ignore Octopus's dispatch kWh for a car.

## Predbat fork (separate repository)

`C:\Users\Matthew\VScodeRepo\batpred` is a fork of
`springfall2008/batpred` on branch `feature/iog-pv10-dispatch-gone-switch`
(adds `switch.predbat_octopus_intelligent_pv10_dispatch_gone`; on = the
18 Oct upstream behaviour). It's about 430 commits behind upstream. The
owner now runs **upstream Predbat** with the virtual-car setup above, so
the fork is parked. Recommended Predbat settings discussed: pv_metric10
weight about 0.15, losses about 4%, metric_min_improvement 0,
car_charging_from_battery on, ignore_unplugged off; check
`car_charging_energy` sensors (a per-session Hypervolt counter caused big
negative load-forecast slots) and move plain-text keys in `apps.yaml` to
`!secret`.
