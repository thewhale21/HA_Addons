# Handover notes

Context for picking this repository up in a new Claude session or
subscription. `CLAUDE.md` has the working rules; this file has the
background: what each add-on does, how the owner uses them, what was
decided and why, and what's still open.

**Last updated:** 27 Nov 2026 (neighbourhood_view 0.22.0).

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
| `ocpp_charge_proxy` | 2.120.2 | The main one: below. |
| `octopus_charge_pack` | 0.10.8 | Octopus API helpers; 0.10.8 drops old `device_id`/`poll_seconds` options via the Supervisor API (`POST http://supervisor/addons/self/options`). |
| `sigenergy_evdc_soc_range_manager` | 0.44.0 | "SigEnergy DC Charger": keeps the EVDC car between limits on a weekly schedule. Limits are named **Maximum charge** and **Keep at least**; an entry can be Maximum charge / Keep at least / Both / Charge only / Discharge only (one-way entries stay within the limits); entries may overlap; start == end means 24 hours; the week view has three lanes (one-way entries in the middle). The Overview's Car SoC chart shows charge/discharge only as a coloured strip along the bottom (0.43.0; points in `soc_history.json` carry a 6th value, "charge"/"discharge", only then). Notifications (0.44.0): the notify service box suggests HA's notify services (`/api/notify_services`) with a Test button; **What to send** (`notify_level`: info = everything incl. starts/stops, warning, error, none; default info); warnings/errors in its log are sent too (`src/log_notify.py`, ported from OCPP's). about 105 tests (test_api needs pytest-asyncio; one notify test needs aiohttp). |
| `tigo_solar` | 0.7.0 | Tigo panel data: roof view (reclaimed in brackets), drag-to-select chart, quick-select per string, per-panel estimates every minute (system power shared by interpolated reading shares), backfill of real 15-minute per-panel readings via Tigo's `lastvalue` (`resourceId=lastValue-{date}-{pin|reclaimedPower}-{HH:MM}`, about 2 requests per slot, 3 s apart; trusted after 3 answers within 35%/30 W of system power, off after 3 misses), fixed scale, hover tooltip, reclaimed %, "By the time of day" and "Through the year" heatmap / 3D surface with Month/Year and 3D zoom. 22 tests. |
| `neighbourhood_view` | 0.22.0 | New (26 Nov 2026): an isometric SVG drawing of the streets (150 m by default, a setting) around your home from OpenStreetMap (postcodes.io for the postcode, Overpass for buildings/roads/areas/trees and the house-number lookup), as the add-on's page and a dashboard card. See "Neighbourhood View" below. |
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

- **Saving sessions vs the automatic schedule** (2.120.2): `_move_for_session` doesn't move a stretch whose plug-in has source `auto_schedule` (`replanned`): like "bank" it only takes the session's time out, adds no moved parts (no purple), and the auto plan (key reset by sync) plans again around the session. Owner had seen the hour before a session drawn purple (a moved part) with Plug in before a session off.
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
- 0.8.0: places only drawn while someone's there (`draw()` filters on `whereabouts`); `island()`
  returns `ends` (street points every 6 m on screen) and `nearestPair` + `bridge()` join home to
  each place (drawn after the islands). Focus is kept by zone (`data-k`, `el._nvFocus`), dropped
  when that island goes. Gap 0.025 × home width (was 0.06).
- 0.9.0 (owner: "as a game's graphic designer, make it look even better"): `render()` puts a CSS
  sky behind the SVG (`.nvsky` day/grey/night, `CLOUDS` puffs drifting, stars at night) and a
  vignette over it; the SVG is `position:relative`. In `island()`: shadows (`V.s` direction,
  `hull()` of footprint + shifted footprint, trees as ellipses; day only, one group at .2),
  street lamps (`lamp()`, every ~34 m on the pavement, light pools via a per-island
  radialGradient whose stops use `LIGHT` so the night tint leaves them), floating `shard()` rocks
  under the front edge (bob with animateTransform; `low` extends the box), water shimmer, a
  pulsing ring round home, pin label drop shadow.
- 0.10.0: zebra crossings (street segments intersected pairwise, with 1.5 m tolerance, so shared
  nodes, ends on another street and plain crossings all count; a junction needs 3+ legs; stripes
  w/2 + PAVE + 1.8 m back on each leg). Water areas: radialGradient fill, darker edge, animated
  ripples. Birds: two flocks in `draw()` crossing the whole box on a loop (SMIL, flapping by
  animating `d`), not at night or when wet. Seasons: `CTX.season` from the month (`opts.month`
  overrides, for tests), AUTUMN/WINTER/BLOSSOM tree palettes (conifers stay green), duller ground
  in winter; `CTX.snow` (weather snowy / snowy-rainy) whitens roofs, ground, grass areas, verges
  and trees via `snowy()`.
- 0.10.1 (owner: bridges stood out; make them S-shaped): `island().ends` carry the street's screen
  direction [x, y, dx, dy]; `bridge()` is a cubic Bézier leaving each end along its street (70%
  street, 30% towards the other end), arching 2.6 m, 3.6 m half-width, in kerb/road colours with
  slim sides and low rails.
- 0.11.0 (owner: weather on the map, e.g. puddles; autumn leaves falling): `island()` now wraps
  `islandDrawn()` and darkens `C.road/pave/kerb/path` while wet (restored in `finally`). CTX flags
  `wet`, `hail`, `windy`, `leaves` (a budget of 90 falling leaves a map). Puddles every 16-38 m by
  kerbs/pavements/paths (blobs + highlight, some with SMIL ripples); 70 splashes (or hailstones)
  over everything. `tree()`: autumn thinning (35% of turned) and winter bare (turn < .4) as branch
  paths; leaf litter; falling leaves/petals (translate + rotate SMIL). Wind: trees wrapped in
  `.nvsway` (CSS, transform-box fill-box). Shadow opacity .07 under a grey sky; none for bare trees.
- 0.11.1 (owner: road sizes should line up at both ends): `ends` carry the street's width
  [x, y, dx, dy, w]; `bridge()` tapers road half-width w/2 and kerbs (+ PAVE + .3) from one end's
  street to the other's (times each map's scale), and leaves along the street (eased towards the
  other end only when the street runs nearly across the gap).
- 0.12.0 (owner: the map as a screensaver; tap → a dashboard, theirs or one made from chosen HA
  areas, themed like the map; back to the map when idle): `src/screen.py` (pure `area_entities`,
  `build_home`, `build_map`, `tap_path`; async `apply(query, ...)` writes
  /homeassistant/themes/neighbourhood_view.yaml, calls frontend.reload_themes, checks
  frontend/get_themes, and makes/saves the `neighbourhood-map` and `neighbourhood-home` storage
  dashboards over the websocket). Settings `screen` {target none/own/ours, path, idle, areas};
  `/api/screen` GET/POST; `/api/scene` returns `screen` {tap, idle, map}. Card: a capture click
  on `.map` navigates (history.pushState + location-changed); 🖵 toolbar button enrols the device
  (localStorage `neighbourhood-view-screensaver` {map: pathname, idle}); a module-level idle watcher
  (runs on every dashboard, since the card is a global resource) navigates back after idle, not
  in edit mode or /config etc. Card options `tap_navigate`, `idle_return`. Owner's wall display
  dashboard is /wall-display-2 (uses kiosk_mode, card_mod); the map dashboard config sets
  kiosk_mode non_admin hide header/sidebar.
- 0.13.0 (owner: a kiosk / non-admin user must see the card; the wall display's user is locked to
  /wall-display-2, which will get the card as its home page): `src/card_data.py` `payload()` (also
  used by /api/scene) and `CardData` write www/neighbourhood-view/map-<token>.json every 15 s if
  changed (`card_data_loop` in __main__; token in /data/card_token, 48 hex; old map-*.json removed;
  POST /api/card/token makes a new one). The status sensor gets a `map_url` attribute
  (`ha_entities.attributes()`; the publisher compares value + attributes). The card reads
  `map_url` from hass.states (any user), fetches it with cache no-cache every 2 min and only redraws
  when the text changed; it falls back to ingress (admins) when there's no map_url or the file
  404s. /local is served without auth: the long name is the protection (documented).
- 0.14.0 (owner: screensaver global on/off, not per device; pick views from a list; group rooms by
  floor; choose each room's things and order): settings `screen` = {enabled, map ("" = the made Map
  dashboard), target own/ours, path, idle 30-3600, areas (ordered), entities {area: [ids]}}; old
  saved values migrate in `_valid` (target none → off; idle 0 → 120). `screen.saver()` →
  {tap, idle, map} goes on the status sensor's `screensaver` attribute (set at once on save, and by
  card_data_loop); the card file's module-level idle watcher reads it from
  `document.querySelector('home-assistant').hass` on every dashboard (no localStorage/🖵 any more).
  `screen.registries()` (floors optional), `views_list()` (lovelace/config of each dashboard: view
  paths or indexes), `chosen_entities()`, `floors_in_order()`; `build_home(..., floors, map_path)`
  makes a section per floor. GET /api/screen returns floors, areas with `things`, views.
- 0.14.1 (owner: tapping went to the wrong dashboard; saved path was /wall-display/home while their
  kiosk dashboard is /wall-display-2, likely two dashboards titled the same): the view pickers show
  each option's address too.
- 0.15.0 (owner asked for all 12 suggested details): scene v2 (`SCENE_V`; saved maps and places
  older than it are remade). scene.py: `_plots()` (house gardens: u along the street from the
  nearest neighbouring house, n away from the nearer street; front depth f to the pavement, back b
  to the next building (half way to a house) or street, by clipping edges to the garden's width;
  w half-width to half way to the neighbour), `landmark()` (church/school/pub from tags or an
  amenity node inside the building; a pub/chapel tagged house is drawn flat), `poi` (bus_stop,
  bench, post_box, bin nodes; Overpass query extended). Card: plotBits (paths, drives, cars,
  garages, hedges/walls, fences, patios, conservatories, sheds, trampolines, washing lines, bushes,
  flower beds, pumpkins, your car + charge glow, heat pump), roofBits (your solar panels, skylights,
  dormers, dishes, Christmas lights in rgb() so the night tint leaves them), landmarkBits, mown
  stripes, reeds, ducks, waterfall (river crossing a front-facing edge), traffic/bus/trains/people
  via SMIL animateMotion inside the ground clip (drawn before things), furniture, fireworks in
  draw(). Sun: live.sun {az, el} (rounded) → shadowVec(); golden sky/overlay when el < 10.
  Energy: settings solar_entity, car_entity, heat_pump_entity; live.energy via active() (same in
  py and js; a climate's hvac_action wins). Card options `motion: false`, `date` (testing).
- 0.15.1: config.yaml has no `options: {}` / `schema: {}` (the add-on linter fails on defaults; don't add them back).
- 0.16.0 (owner: rain stuttery; parked cars hit by traffic; gardens overlapping): rain/snow/cloud
  overlays are SVG-tile backgrounds (`fxTile`) moved with CSS transform (compositor) inside a rotated
  `.nv-tilt` (rain slant), not background-position; splashes 36 (hail 70). Parked cars at
  w/2 - 0.95 (scene.py `_cars`), traffic at max(0.8, w/4 - 0.25), sprite 1.35 wide. scene.py:
  plot half-width `pw` computed before the back-depth search (buildings within pw - 0.3, roads pw + 2);
  `_no_overlaps()` cuts the deeper of two overlapping back gardens by 25% (SAT on `_back_rect`, up to
  20 passes; < 2 m → 0). SCENE_V 3.
- 0.16.1 (owner: rain laggy on older devices; pickers cut off in Settings): fewer streaks/flakes,
  `.nv-tilt` inset -18%; `LITE` (auto: hardwareConcurrency <= 4 or deviceMemory <= 2; card option
  `effects: lite|full`): one rain/snow layer, no cloud layer, no splashes or puddle ripples, 20
  falling leaves. `.rows` is `overflow: visible` (it clipped the picker lists). addon_template and
  the other add-ons still have `.rows { overflow: hidden }` (the template file wasn't writable here).
- 0.16.2 (owner: traffic still looked to drive under parked cars): parked cars (scene.cars) are no
  longer depth-sorted with the buildings: drawn in the ground layer, far-side ones (further back than
  the nearest street point, by V.d) before the traffic, near-side ones after it. Traffic lane
  offset min(w/4, max(0.55, w/2 - 2.95)) (a car's width in from the parked line), the bus
  min(w/4, max(0.8, w/2 - 3.2)).
- 0.17.0 (owner: choose each decoration's dates; add Valentine's, Easter, Chinese New Year,
  birthdays (several dates); snowmen; frost and a gritter below 5°C): settings `occasions`
  (app_settings OCCASIONS: xmas, newyear, valentines, cny/easter with `auto`, halloween, bonfire,
  birthdays {on, dates: [{date MM-DD, name}]}), in the card payload / api scene as `occasions`.
  Card `occasion(d, cfg)`: ranges MM-DD (wrapping the year), `autoRange` (Easter by the Gregorian
  algorithm; Chinese New Year from the CNY table to 2040), exported on window.NeighbourhoodView for
  the settings page. Lanterns in roofBits; eggs, hearts, balloons, snowmen in plotBits; birthday chip
  via overlays(live, note). CTX.cold/frost from the weather entity's temperature (< 5°C or 41°F);
  frost through snowy(); gritter a mover on the second-biggest street. Settings page: day/month
  selects (`mdPick`), no year.
- 0.17.1 (owner: hedges off the island and drawn over buildings): plotBits `run()` draws fences,
  walls and hedges in pieces of up to 4 m, each depth-sorted, skipped when an end is off the island
  or its middle is in a building (`inBuilding`: a 20 m grid of footprints); hedges/walls drawn as the
  face towards you + top (no end caps, so pieces join); fences a single panel. `on()` has a fast path
  (|x|, |y| < H - 35 is always on the island): drawing ~2x faster.
- 0.18.0 (owner sent a satellite photo: gardens should fit together like the real street; then:
  houses and gardens not on roads or footpaths): scene.py `_make_room()` (before everything else uses
  the roads): a street with buildings within w/2 + PAVE + CLEAR gets narrower pavements (`pv`, down
  to PAVE_MIN 1.6) then road (down to NARROW_MIN 0.8 of w), ignoring buildings it runs into; a small
  building still on it is moved straight away from it (up to NUDGE_MAX 4 m, not into another
  building); footpaths are cut where they go through a building. Consumers of the old 2.8 use
  `r.get("pv", PAVE)` (rgrid folds pv into w). `_lots()`: a ~300-cell grid; roads + pv and paths
  + 0.4, big/other buildings, paved/yard/water/pitch/wood and grass > 2500 m² blocked; a multi-source
  Dijkstra from the house footprints (LOT_MAX 45 m) shares the rest out; edges between owners are
  chained, Douglas-Peucker'd and returned as `scene.fences` [{k side|street|edge, p, o [ids]}]; each
  plot's `b` is cut to the depth its lot mostly fills (then `_no_overlaps` again). SCENE_V 4. Card:
  `gardenFences()` draws them in 3 m depth-sorted pieces (street ones in front of a house left to
  plotBits' front hedge with gaps; open/low between front gardens; fence/hedge behind); plotBits'
  rectangle fences only for old scenes (`lots` false). `pv(r)` for pavement widths, verge only if
  pv >= 2.5. The sample's end-of-row houses touching the cross streets can't be moved (they'd go into
  the next house) and are left.
- 0.19.0 (owner: the 0.18.0 remake failed as Overpass timed out, leaving the old map; asked to keep
  OSM's data and redraw from it): places.py `OsmCache` (/data/osm/<sha1>.json.gz, {at, data}, the
  CACHE_KEEP 16 most recently used kept) wraps `overpass()` and `postcode_location()` via
  `cache.ask(key, fetch)`. offline_first (set by `_start`): a kept answer used without fetching;
  else fetched, falling back to the kept one on any error (`used_copy` = its date, used as the
  scene's `made` so it's tried again once that's 30 days old). map_maker/make_places pass
  offline_first when the saved scene fits except for SCENE_V (`fits(..., version=False)`) and it
  isn't a forced Refresh. `_why()` words errors (a timeout's str is empty). Test with a fake session
  (monkeypatches `_timeout`, as aiohttp isn't installed in the cloud test env).
- 0.19.1 (owner: the map restarted every 5-10 s, clouds resetting and cars vanishing): every new
  phone location changed the live key, so render() ran again. Card `steady(live, prev)` (exported
  on window.NeighbourhoodView, used by the card's set hass/_draw and the add-on page's
  liveNow()/drawMap) keeps a person's previous lat/lon while they've moved < STEADY_M 40 m (same
  state). Anything else new in live (weather, home/away, sun 5°, energy) still redraws.
- 0.20.0 (owner: Christmas on 1 Nov-6 Jan but nothing seen; the date logic was right, the eave
  bulbs were just too small by day): bulbs r .22 (.26 night) on a wire; `xmasTree(V, x, y, seed, s)`
  (three tiers, baubles twinkling at night, star) in front gardens of the decorated houses (same
  `rnd(id, 35) < 0.4` as roofBits, fr >= 1.6) and as furniture 'xmas_tree' (s 2.4) on the first free
  corner of the four junctions nearest the centre.
- 0.21.0 (owner: all decorations bigger, more varied, trees and scenery too, presents): roofBits'
  eave lights are `eaveLights(FP, len, id, style)`, style per house by rnd(id, 38): multi, warm,
  icicle, blue (xmas, rnd(id, 35) < 0.4), spooky (halloween, rnd(id, 39) < 0.3), love (valentines,
  < 0.22); EAVE colours (multi reads XMAS inside the function: XMAS is a later const). `treeDeco()`
  appended by tree() (40% of non-bush trees by rnd(x, y, 430)): xmas bulbs (conifer tiers + star),
  halloween swinging ghost, valentine hearts, easter eggs, cny lanterns. lamp(): xmas garland/bow/
  star, halloween bat, cny lantern. plotBits front: xmas tree + `presents()` (hex colours only:
  box()/mix() don't parse rgb()), `wreath()`, `reindeer()`, `candyCane()`; halloween 1-3 bigger
  `pumpkin(V, x, y, k)` + `gravestone()`; easter eggs .6x.8 striped + `bunny()`; birthday presents +
  `bunting()`. Helpers `star()`, `heartAt()`. shot5.py runs xmasday/xmasclose/hallday/easterday/valday.
- 0.22.0 (owner: add all 11 extras + the performance items; then: things drawn over roads/paths/
  buildings again, and the 5-second stutter): LAYERS: islandDrawn(opts.split) returns `layers`
  [still ground, moving ground (gAnim: anything with <animate, plus the near-side parked cars, under
  the island's clip; gAnim2 the waterfall), still things (still() strips SMIL except elements fx()
  marked data-nvk: smoke, leaves, hearts, TV flicker, heat pump, steam, windy washing), top (rain
  splashes, pins)]; draw() puts each in its own <svg class="nvlayer"> (0 and 2 will-change:transform;
  .up ones pointer-events:none); fit() sets every layer's viewBox; split is off in pick mode (the
  add-on page's Overview) and with card `layers: false`. P()/P2() route ground pushes; rivers are
  'still' (shimmer stripped). Trees don't sway in split. render() pauses SMIL/CSS (nv-paused) when
  hidden or off-screen (IntersectionObserver). steady(): temperature rounded, energy flags must hold
  SETTLE_MS 60 s; the card console.debug()s what changed. index.html setHTML() only writes changed
  HTML (rows every 1 s, card-file every 2 s were rewriting). GUARDS: plotBits thing(x, y, svg, rad,
  kerb) checks onRoad (grid of roads + pavements + paths) and inBuilding at rad round it; fences too.
  EXTRAS: wallTexture (BRICK colours: courses; else pebble-dash 50%), windowBits (curtains, window
  boxes, cats, TVs ≤ CTX.tv), wheelieBin (bin day from live.house.bins: src/live.py bin_day / card
  binDay), gardenTable/paddlingPool/barbecue by season/CTX.temp, road wear + give-way (legs whose ri
  is alone at the junction), scene "allot" areas and "garage" buildings (SCENE_V 5), settings
  `look` {door, plate} (app_settings DOORS; payload "look"), steam (CTX.frost, hour < 11), rainbow
  (LAST_WET within 45 min, or card `rainbow: true`), school run / milk float / dog walkers by
  CTX.hour, moon(when) by moonPhase (hidden when grey), house: door/garage/lights from
  ENTITY_KEYS bins/door/garage/garden_lights (PICKER_DOMAINS + calendar, cover, light, lock,
  input_datetime).
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
