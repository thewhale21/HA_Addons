# Neighbourhood View

An isometric drawing of the streets around your home, from OpenStreetMap,
as the add-on's page and as a dashboard card.

## Using it

1. Install the add-on, start it and open it from the sidebar.
2. **Settings › Address:** your **postcode** (UK) and **house number**,
   then **Save** (or Enter). The map's made straight away, usually in a few
   seconds, and kept: it's made again every 30 days, when you change your
   address, or now with **Refresh**. **Map size** (beside them) is how far
   the map goes each way from your house: 150 m by default (a 300 m
   square), anything from 50 to 500 m. A bigger map takes longer to make
   and draw.
3. **Overview:** the streets round your house, with a pin on your house
   showing its number.
   - **+ −** zoom in around your house and back out (it starts close in,
     on your street and the ones round it; − four times shows the whole
     square), **⟲ ⟳** turn it a quarter at a time (both remembered on
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
  their face on a stalk where they are; someone in a zone that's one of
  your other places, without a location, over that place's pin.
- **Night** (Home Assistant's sun below the horizon): the map goes dark
  blue, about a third of the other houses' windows are lit, and your
  house's lights are on, with a warm glow round it, when someone's home,
  and off when nobody is. **By day**, someone home: smoke from your
  chimney (and their faces over the house).

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
  (road and pavements), so they line up, narrowing or widening between.
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
  are 2 storeys, some bungalows and some 3 storeys.
- **Other buildings:** flats and offices with rows of windows, shops with
  a glass front and a coloured fascia, warehouses with high windows, and
  things on their flat roofs. Heights from OpenStreetMap (3 m a storey),
  else by type (flats 12 m, shops 8 m, garages 2.8 m...).
- **The ground** is lawn, as gardens mostly are; shops', offices' and
  industrial land is hard standing, and car parks are grey.
- **Streets** have a pavement each side with its kerb (and a grass verge
  on residential streets), and white lines down the middle; footpaths are
  drawn on their own.
- **Trees** in three kinds (round, pointed and bushes), in different
  greens and sizes: the ones OpenStreetMap has, more in woods and parks,
  some along residential streets, and some in gardens (never on a road,
  pavement, building, car park or yard).
- **Cars** parked along the kerbs, in different colours (not near
  junctions).

- **The edge:** the square looks torn out of the ground, with a ragged
  edge, a lip of turf, and soil and rock (with the odd stone) down its
  sides, and a few chunks of rock floating underneath. Buildings the torn
  edge would cut through aren't drawn.
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
  - **Snow:** roofs, lawns, parks and trees turn white (roads stay clear).
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
display.

- **Tapping the map goes to** a dashboard of your choosing:
  - **Nowhere**: the map stays put.
  - **My own dashboard**: pick one, or type its path, e.g.
    `/wall-display-2/home` for a view.
  - **A dashboard made from my rooms**: tick the rooms (Home Assistant's
    areas). A **Home** dashboard is made with a Home view (the clock, the
    weather, who's in, a button for each room and one back to the map),
    and a view for each room with its lights, switches, fans, blinds,
    locks, media players, heating and cooling, and temperature, humidity
    and door/window/motion sensors. It's made again each time you save,
    so changes made to it by hand are lost: copy it (its ⋮ menu › Raw
    configuration editor) to make your own.
- **Save and make the dashboards** also makes a **Map** dashboard (the
  map filling the screen, at `/neighbourhood-map/map`) and the
  **Neighbourhood View** theme: glassy dark cards over a blue sky by day,
  or a night sky in dark mode, the same as the map. Both made dashboards
  use it; to use it on your own, pick it in a view's settings (Theme) or
  your profile. Home Assistant has to read your `themes` folder: if the
  page says it doesn't, add this to `configuration.yaml` and restart:

  ```yaml
  frontend:
    themes: !include_dir_merge_named themes
  ```

- **Back to the map after being left alone** (1 to 30 minutes, or
  never): only on devices you choose. Open the Map dashboard on that
  device and press **🖵** on the map's buttons (it turns blue). Then,
  wherever it's left on another dashboard, it comes back to the map after
  that long with nobody touching it (not while editing a dashboard, or in
  Home Assistant's settings). Press 🖵 again there to stop.

The card's own options `tap_navigate: /path` (or `''` for nowhere) and
`idle_return: seconds` override these for that card.

The card reads the map through the add-on, so the wall display's user
has to be an administrator.

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
and out, **⟲ ⟳** turn it.

Options:

| Option | What it does |
| --- | --- |
| `label` | The pin's text (default: NO. and your house number, or HOME) |
| `height` | The card's height outside a panel view, e.g. `500px` |
| `addon` | The add-on's slug, if it can't be found (e.g. `a1b2c3d4_neighbourhood_view`) |
| `url` | Read the map from this address instead of through Home Assistant (e.g. `http://homeassistant.local:8099/`) |
| `weather` | A weather entity for this card, instead of the add-on's |
| `people` | People for this card, instead of the add-on's, e.g. `[person.matt, person.jo]` |
| `tap_navigate` | Where tapping the map goes, instead of Settings › Screensaver, e.g. `/wall-display-2/home` (`''`: nowhere) |
| `idle_return` | Seconds left alone before a device with 🖵 on comes back to the map, instead of the add-on's |

The card reads the map from the add-on through Home Assistant's ingress, as
the add-on's page does, so it needs an **administrator** account. It reads
it again every 30 minutes. The weather, people and day or night it follows
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
else leaves Home Assistant. The map's kept in the add-on's own data.

## Diagnostics

**Diagnostics › Health** shows the version, uptime and the link to Home
Assistant. **Diagnostics › Debug** has the log level, recent log lines, a
diagnostics bundle and a restart button.

Map data © OpenStreetMap contributors, under the Open Database Licence.
