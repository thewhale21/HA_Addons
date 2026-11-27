# Neighbourhood View

An isometric drawing of the streets around your home, from OpenStreetMap,
as the add-on's page and as a dashboard card.

## Using it

1. Install the add-on, start it and open it from the sidebar.
2. **Settings › Address:** your **postcode** (UK) and **house number**,
   then **Save** (or Enter). The map's made straight away, usually in a few
   seconds, and kept: it's made again every 30 days, when you change your
   address, or now with **Refresh**. What OpenStreetMap sent is kept too,
   so after an add-on update that draws the map differently it's redrawn
   from that copy without asking OpenStreetMap again, and if OpenStreetMap
   can't be reached (busy, or no connection) the map's made from the last
   copy instead (the log says so, with its date). **Map size** (beside them) is how far
   the map goes each way from your house: 150 m by default (a 300 m
   square), anything from 50 to 500 m. A bigger map takes longer to make
   and draw.
3. **Overview:** the streets round your house, with a pin on your house
   showing its number.
   - **+ −** zoom in around your house and back out (it starts close in,
     on your street and the ones round it; − four times shows the whole
     square), **⟲ ⟳** turn it an eighth (45°) at a time (both remembered on
     each device).
   - **⌂** picks your house: click it, then click your house. The map's
     made again centred on it, and it's kept until you change your address.
     Use it when the pin isn't on your house.
   - The chip at the top says how your house was found: from your address
     (OpenStreetMap has it), the building nearest your address, picked by
     you, or not found (the map's centred on your postcode: pick it).

## Weather and people

Settings › **On the map**:

- **Weather:** a weather entity (e.g. the Met Office or Met.no
  integration's `weather.home`). Its weather is drawn over the map: rain
  (heavier when pouring), snow, fog, cloud shadows drifting over, a warm
  light when it's sunny and flashes of lightning in a thunderstorm, with a
  chip at the top right saying what it is and the temperature.
- **People:** up to 6 people (Home Assistant's people, or device
  trackers). Each has a chip at the top right: home, away, or the zone
  they're in. Whoever's home has their picture (or initials) over your
  house. Someone out whose tracker gives a location (e.g. the companion
  app's GPS) that's on one of the maps, yours or another place's, has
  their face on a stalk where they are (moved once they've gone 40 m or
  more, so the map isn't drawn again for every small wobble in a phone's
  location); someone in a zone that's one of
  your other places, without a location, over that place's pin.
- **Night** (Home Assistant's sun below the horizon): the map goes dark
  blue, about a third of the other houses' windows are lit, and your
  house's lights are on, with a warm glow round it, when someone's home,
  and off when nobody is. **By day**, someone home: smoke from your
  chimney (and their faces over the house).
- **Your house** (each from an entity of yours; leave any out):
  - **Solar panels** on your roof, glinting while it says they're producing
    (a power sensor over 20 W, or on).
  - **Your car** on your drive (or at the kerb outside if there's no room
    for one), glowing with a charging bolt while it says it's charging (on,
    charging, or a power over 20 W).
  - **A heat pump** beside the house: its fan turns and it puffs while it
    says it's running (on, heating, a thermostat heating or cooling, or a
    power over 20 W). Solar, car and heat pump only change on the map once
    they've said so for a minute, so a power hovering round 20 W doesn't
    keep drawing the map again.
  - **Bins:** your bins (and most of the street's) are put out at the kerb
    from 6pm the evening before collection day and brought back in at 7pm
    on the day, with the bin lorry doing the rounds that morning (7am to
    1pm). Otherwise they stand beside the house. From a bin calendar (e.g.
    a calendar with an all-day event on each collection day, or the Waste
    Collection Schedule integration's calendar), a bin collection sensor
    (today, tomorrow, "Recycling in 2 days", days to go, or the date), or a
    switch. Only the bins its words name go out: general (rubbish, refuse,
    black, grey), recycling (blue, paper, plastic), garden (green, brown,
    compost), food (a caddy) and glass; with none named, all of them. Each
    house has a general and a recycling bin, some a garden bin, a food
    caddy or a glass box.
  - **Front door:** open while a door sensor says so (or a lock's
    unlocked), lit inside at night. Its colour (Settings: Door colour) and
    your number on a plate beside it are yours to choose.
  - **Garage:** a garage beside your house (where there's room), its door
    up while a cover or sensor says it's open.
  - **Garden lights:** lights round your back garden while a light or
    switch is on, glowing at night.

## Other places

Settings › **Other places**: up to 6 more maps beside yours, e.g. work, a
school or the gym, each a Home Assistant **zone** (Settings › Areas,
labels & zones › Zones in Home Assistant). For each: the zone, which side
of your map it goes (**left**, **right**, **above** or **below**) and how
far it goes each way round the zone's middle (100 m by default, 30 to
400 m). Then **Save**.

- Each is drawn as its own little island next to yours, with a pin
  labelled with the zone's name, joined to yours by a bridge between the
  nearest streets on the two maps: a road that leaves each map along its
  street and curves (an S where the streets don't line up) and arches
  gently over the gap. Each end is as wide as the street it carries on
  (road and pavements), so they line up, narrowing or widening between. A
  bridge only starts where a street runs off the edge of a map on the side
  facing the other one (never at a cul-de-sac's end or from a street in
  the middle, which would send it back across the map); with no such street
  on that side, it starts from the grass at the edge.
- A place only shows **while someone's there**: in its zone, or on its
  map by their tracker's location. When they leave, it disappears (and if
  you were zoomed in on it, the view goes back to your house). Places showing on the same side share it: two on
  the left are one above the other, two below are side by side, made
  smaller to fit if they need to be.
- **Tap a place** on the Overview (or the card) to zoom in round it; tap
  your own map to come back to it. At the furthest zoom out (**−**)
  everything's in view.
- Their maps are made after yours (a couple of seconds apart, to be kind
  to OpenStreetMap's servers), kept, and made again every 30 days, when
  the zone moves or you change its size.

## What's drawn

From OpenStreetMap: buildings, roads and paths, railways and tram lines,
parks, grass, woods, sports pitches, car parks, water and rivers, and the
trees it has, drawn like a video game's town:

- **Houses** each get their own look: brick, render or stone walls, a
  tiled, slate or clay roof, gabled or hipped, its ridge running along the
  nearest street (as a terrace's or a semi's does), a chimney on some, windows
  on every storey and a front door. Where OpenStreetMap has no height, most
  are 2 storeys, some bungalows and some 3 storeys. What most of them are
  built of is yours to choose (Settings › Your house › Houses round here:
  mostly brick, the default, as most British houses are; mostly rendered;
  mostly stone; or a mix), each still in its own shade with its own roof,
  and a few different; with mostly brick, some flats and bigger buildings
  are brick too. Brick walls show their courses, a darker plinth and the odd
  brick a shade off, some rendered ones a pebble-dash; windows have curtains half
  drawn in some, window boxes under some, the odd cat on a sill, and at
  night a TV flickering in a few.
- **Other buildings:** flats and offices with rows of windows, shops with
  a glass front and a coloured fascia, warehouses with high windows, and
  things on their flat roofs. Heights from OpenStreetMap (3 m a storey),
  else by type (flats 12 m, shops 8 m, garages 2.8 m...).
- **The ground** is lawn, as gardens mostly are; shops', offices' and
  industrial land is hard standing, and car parks are grey.
- **Allotments** as rows of beds (bare in winter) with the odd shed, and
  **garages** (lock-up blocks too) with a row of up-and-over doors.
- **Streets** have a pavement each side with its kerb (and a grass verge
  on residential streets), and white lines down the middle; footpaths are
  drawn on their own. Houses are never drawn on a street, its pavements or
  a footpath: where houses are close, the pavements (then the road, a
  little) are drawn narrower, a house still on one is moved back off it,
  and a footpath that runs through a building is left out there.
- **Trees** in three kinds (round, pointed and bushes), in different
  greens and sizes: the ones OpenStreetMap has, more in woods and parks,
  some along residential streets, and some in gardens (never on a road,
  pavement, building, car park or yard).
- **Cars** parked along the kerbs, in different colours (not near
  junctions).
- **Gardens:** as on a satellite photo, the ground round the houses is
  shared out between them: each bit goes to the nearest house (going round,
  not across, streets, footpaths, other buildings, parks, car parks and
  water), up to 45 m from it. So back gardens run back to meet the gardens
  of the next street half way, side boundaries sit half way between
  neighbours, and a block is all gardens, with no spare lawn. Between back
  gardens there's a fence (some a hedge), where a garden backs onto a
  street or park a fence, wall or hedge, and between front gardens a low
  wall or hedge (or nothing: many are open). At the front:
  a path to the door, a driveway on about half (many with a car, some
  leading to a garage), a hedge or low wall along the pavement, flowers
  under the window, wheelie bins (grey, green, blue). At the back: patios,
  the odd conservatory, sheds, trampolines, washing lines (brought in when
  it's wet or dark, blowing about when it's windy), bushes and flower
  beds; through the year, tables under parasols and the odd paddling pool
  in summer, a barbecue on a warm day (18°C or more), a table and chairs
  in spring and autumn, all put away in winter. Nothing in a garden is
  drawn on a street, pavement, footpath or building.
- **Roofs:** skylights, dormers and satellite dishes on some.
- **Greenery:** parks and playing fields mown in stripes, reeds round
  ponds.
- **Street furniture:** OpenStreetMap's bus stops (a shelter and its
  sign), benches, post boxes and bins, and more besides: benches (some
  with a bin) along footpaths, post boxes at some street corners.
- **Landmarks** from what OpenStreetMap says a building is: churches (a
  tower and spire), schools (a flag and a playground) and pubs (a hanging
  sign and picnic benches).
- **Roads** wear: patched tarmac now and then, drain covers by the kerbs,
  and faded give-way lines where a side street meets another.
- **Life:** cars and a bus driving the streets (on the left; busier on
  the school run, weekdays about 8:15 to 9 and 3 to 3:45), a milk float or
  delivery van early in the morning (5 to 8), a train now and then on a
  railway, people walking the pavements (some with a dog, more walking
  dogs on dry evenings, 5 to 9; fewer at night or in the rain), ducks
  paddling on ponds, and a waterfall where a river runs off the front edge.
- **Sky:** the moon at night in its phase (unless it's cloudy), and a
  rainbow when the sun comes out after rain (for up to 45 minutes).
  Steam from some roofs on a frosty morning. The card's `motion: false`
  option keeps all this still.

- **The edge:** the square looks torn out of the ground, with a ragged
  edge, a lip of turf, and soil and rock (with the odd stone) down its
  sides, and a few chunks of rock floating underneath. Buildings the torn
  edge would cut through aren't drawn.
- **The sun:** with Home Assistant's sun (`sun.sun`), shadows fall away
  from where it really is, long in the evening, and near sunrise and
  sunset the sky and the map turn golden.
- **Occasions** (Settings › **Occasions**: each on or off, and the days
  it's on, as a day and a month, either way round the new year):
  Each house that joins in does it its own way, and some of the trees and
  street lamps are decorated too.
  - **Christmas** (1 December to 6 January): lights along the eaves of many
    houses and yours (coloured, warm white, icicles, or blue and white),
    twinkling at night; in their front gardens a decorated tree with
    presents under it, a wreath on the door, a light-up reindeer, candy
    canes along the path; lights in some trees, garlands, bows and stars on
    the street lamps, and a big tree on a corner of the junction nearest
    the middle of the map.
  - **New Year** (31 December to 1 January) and **Bonfire Night** (4 to 6
    November): fireworks over the map at night.
  - **Valentine's Day** (14 February): hearts floating up from some houses
    and yours, heart lights along some eaves, and hearts in some trees.
  - **Chinese New Year**: red lanterns along the eaves, in some trees and
    on the street lamps, glowing at night. By the calendar (the day before
    New Year to the Lantern Festival, its dates each year to 2040), or days
    you choose.
  - **Easter**: coloured eggs hidden in the back gardens, a bunny in some,
    and painted eggs hanging in some trees. By the calendar (Good Friday to
    Easter Monday), or days you choose.
  - **Halloween** (24 to 31 October): pumpkins by front doors (lit at
    night), gravestones in some front gardens, orange and purple lights
    along some eaves, ghosts swinging from some trees, bats on the lamps.
  - **Birthdays**: as many dates as you like, each with a name if you
    want. On the day, balloons and presents by your front door, bunting
    across the front, and a chip wishing them happy birthday.
- **Light:** by day buildings and trees cast soft shadows, and the maps
  float in a blue sky with clouds drifting behind (grey when it's wet). At
  night the sky's dark with stars, and street lamps along the bigger
  streets light pools on the pavement. Rivers shimmer, and a ring pulses
  out on the ground round your house.
- **Junctions** have zebra crossings on each street just back from them.
- **Ponds and lakes** have a darker edge, are lighter in the middle, and
  ripples spread across them now and then.
- **Birds:** now and then a flock flies over (by day, when it's dry).
- **Seasons** (from the date): in autumn many trees turn orange, red and
  yellow, some thinning to bare branches with a few clumps left, leaves
  lying round them and falling now and then; in winter many are bare and
  the rest dull, and the grass browner; in spring some blossom pink and
  white and drop petals.
- **The weather on the ground** (from the weather entity):
  - **Rain** (and heavy rain, thunderstorms, sleet): the roads and
    pavements go dark and wet, puddles lie by the kerbs and on the
    pavements with raindrops rippling them, and rain splashes all over.
  - **Hail:** wet roads and puddles, with hailstones lying about.
  - **Snow:** roofs, lawns, parks and trees turn white (roads stay clear),
    and snowmen stand in some gardens (and yours).
  - **Below 5°C** (41°F, by the weather entity's temperature): a frost
    rimes the lawns, roofs and trees (when it isn't snowing or raining),
    and an orange gritter drives the streets now and then, spreading salt.
  - **Wind** (and heavy rain, thunderstorms): the trees sway, and falling
    leaves are blown further.
  - Under a grey sky shadows fade; with sun they're crisp.

What's made up (each house's colours, the trees and cars added, the
storeys where none are known) is the same every time, so nothing moves
about between visits. Your house is drawn in blue.

How your house is found: postcodes.io gives the postcode's centre, then
OpenStreetMap's addresses within 400 m with your house number and postcode.
Not every house has its address in OpenStreetMap; then it's centred on the
postcode and the pin's on the building nearest it, until you pick yours.

## Screensaver

Settings › **Screensaver** makes the map a screensaver, e.g. for a wall
display. It's on or off for everything (every screen, every user):

- **The map is on:** the view the map's on, picked from your dashboards'
  views (e.g. **Wall display › Map**, `/wall-display-2/map`), or **the Map
  dashboard** the add-on makes for you (`/neighbourhood-map/map`, made only
  when it's chosen).
- **Tapping the map goes to:** one of your views (e.g. **Wall display ›
  Home**), any address typed in, or **a dashboard made from my rooms**:
  - Tick the rooms (Home Assistant's areas, shown by floor). Under each,
    **Things** lists what's in it (lights, switches, fans, blinds, locks,
    media players, heating and cooling, and temperature, humidity and
    door/window/motion sensors): untick what you don't want. **↑ ↓** put
    the rooms in order on their floor.
  - It makes a **Home** dashboard: a Home view (the clock, the weather,
    who's in, the rooms grouped by floor, bottom floor first, and a button
    back to the map), and a view for each room. It's made again each time
    you save, so changes made to it by hand are lost: copy it (its ⋮ menu ›
    Raw configuration editor) to make your own.
- **Back to the map after being left alone** (1 to 30 minutes): any screen
  on another dashboard with nobody using it goes back to the map. Using it
  (a tap, a touch, a scroll, a key, the mouse) starts the wait again, so it
  only goes while nobody's there; a dialog left open goes too. It doesn't
  happen while editing a dashboard, in Home Assistant's settings or on the
  add-on's page.

Saving also makes the **Neighbourhood View** theme: glassy dark cards over a
blue sky by day, or a night sky in dark mode, the same as the map. The
dashboards made here use it; to use it on your own, pick it in a view's
settings (Theme). Home Assistant has to read your `themes` folder: if the
page says it doesn't, add this to `configuration.yaml` and restart:

```yaml
frontend:
  themes: !include_dir_merge_named themes
```

The card's own option `tap_navigate: /path` (or `''` for nowhere)
overrides where tapping it goes.

**A kiosk wall display**, kept on your own dashboard: add the map as the
dashboard's first view (a panel view with the card, path `map`), then in
Settings › Screensaver choose **The map is on** › that view and **Tapping
the map goes to** › your home view.

## The dashboard card

The add-on puts the card in Home Assistant's `www` folder
(`www/neighbourhood-view/neighbourhood-view-card.js`) and adds it to your
dashboards' resources each time it starts (Settings › **Dashboard card**
says whether it did). Then:

1. Edit a dashboard and add a view. For the whole screen, give it the view
   type **Panel (single card)**.
2. Add a card: **Manual**, with

   ```yaml
   type: custom:neighbourhood-view-card
   ```

In a panel view it fills the screen below the header; elsewhere it's 4:3,
or as tall as `height` says. On a screen much narrower (or flatter) than
the drawing, e.g. a phone held upright, it shows closer in around your
house instead of the whole square small in the middle. **+ −** zoom in
and out, **⟲ ⟳** turn it, 45° at a time.

Options:

| Option | What it does |
| --- | --- |
| `label` | The pin's text (default: NO. and your house number, or HOME) |
| `height` | The card's height outside a panel view, e.g. `500px` |
| `addon` | The add-on's slug, if it can't be found (e.g. `a1b2c3d4_neighbourhood_view`) |
| `url` | Read the map from this address instead of through Home Assistant (e.g. `http://homeassistant.local:8099/`) |
| `weather` | A weather entity for this card, instead of the add-on's |
| `people` | People for this card, instead of the add-on's, e.g. `[person.matt, person.jo]` |
| `motion` | `false`: nothing moves (traffic, people, ducks, a train), e.g. on a slow tablet |
| `layers` | `false`: draw the map as one picture, as before 0.22.0 (it's drawn in layers, so what moves doesn't make the browser draw the whole map again each frame) |
| `effects` | `lite`: one layer of rain or snow, no drifting cloud, no splashes or puddle ripples, fewer falling leaves, plainer walls and windows, fewer decorated trees and people walking; `full`: all of it. Left out: lite on slower devices (4 cores or fewer, or 2 GB or less), full on the rest |
| `tap_navigate` | Where tapping the map goes, instead of Settings › Screensaver, e.g. `/wall-display-2/home` (`''`: nowhere) |

Any signed-in Home Assistant user can see the card, kiosk and other
non-administrator users too. The add-on keeps what the card draws in a
file in Home Assistant's `www` folder with a long, private name
(`/local/neighbourhood-view/map-….json`), and tells signed-in users the
name in the `map_url` attribute of `sensor.neighbourhood_view_status`.
Files in `www` are served without signing in, so the name is what keeps
it private: **Settings › Dashboard card › New private name** makes a new
one if you think it's got out (cards pick it up by themselves). The card
looks for changes every 2 minutes (only downloading it when it's
changed). The weather, people and day or night it follows
straight from Home Assistant, as they change. The card's file has nothing about you in it.

**Dashboards in YAML mode:** the add-on can't add the resource; add it to
your configuration:

```yaml
lovelace:
  resources:
    - url: /local/neighbourhood-view/neighbourhood-view-card.js
      type: module
```

## Its Home Assistant entities

`sensor.neighbourhood_view_status`: what it's doing (Waiting for your
address, Making the map, Ready, Problem). It shows unavailable while the
add-on is stopped.

## Privacy

Your postcode goes to postcodes.io, and the location of your postcode (or
house), and of your other places' zones, to OpenStreetMap's Overpass
servers, when the maps are made. People's locations stay in Home
Assistant: they're only used to draw them. Nothing
else leaves Home Assistant. The map, and what OpenStreetMap and postcodes.io
sent for it, are kept in the add-on's own data.

## Diagnostics

**Diagnostics › Health** shows the version, uptime and the link to Home
Assistant. **Diagnostics › Debug** has the log level, recent log lines, a
diagnostics bundle and a restart button.

Map data © OpenStreetMap contributors, under the Open Database Licence.
