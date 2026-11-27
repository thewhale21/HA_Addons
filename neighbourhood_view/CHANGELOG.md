# Changelog

## 0.18.0 — Whole gardens, like the street really is

- **Feature:** gardens fit together as they do on a satellite photo. The
  ground round the houses is shared out between them (each bit to the
  nearest house, going round streets, footpaths, other buildings, parks
  and water), so back gardens run back to meet the next street's half
  way, side fences sit half way between neighbours, and the blocks are all
  gardens instead of rectangles with spare lawn between. Fences between
  back gardens (some hedges), a fence, wall or hedge where one backs onto a
  street or park, and low walls or hedges between some front gardens.
- **Fix:** houses and gardens are no longer drawn on streets, pavements or
  footpaths: a street with houses close has narrower pavements (and, if
  need be, a slightly narrower road), a house still on one is moved back
  off it, and a footpath running through a building is left out there.
- **Change:** maps are made again (once) after updating, for the gardens.
## 0.17.1 — Hedges and fences in their place

- **Fix:** garden hedges, walls and fences are no longer drawn off the
  island's edge, through other buildings, or over buildings in front of
  them: each is drawn in short pieces, every one in its place among the
  buildings, and a piece off the edge or in a building is left out. Sheds,
  trampolines and the like aren't put in a building either.
- **Improvement:** the map draws about twice as fast (quicker checks of
  what's on the island; fences drawn as a single panel).
## 0.17.0 — Occasions you choose, snowmen and frost

- **Feature:** Settings › **Occasions**: turn each decoration on or off and
  choose the days it's on (a day and a month, either way round the new
  year).
- **Feature:** new occasions: Valentine's Day (hearts floating up), Chinese
  New Year (red lanterns), Easter (eggs in the gardens) and birthdays (as
  many dates as you like, with names: balloons by your front door and a
  happy birthday chip). Easter and Chinese New Year follow the calendar
  unless you set their days. New Year and Bonfire Night's fireworks are
  set separately.
- **Feature:** snowmen in some gardens when it snows.
- **Feature:** below 5°C: a frost on the lawns, roofs and trees, and a
  gritter spreading salt along the streets.
## 0.16.2 — Traffic past the parked cars

- **Fix:** the traffic no longer seems to drive under the parked cars: it
  keeps a car's width in from them (nearer the middle of the road), and the
  parked cars on the near side of a street are drawn in front of it, those
  on the far side behind it.
## 0.16.1 — Lighter rain and snow, pickers not cut off

- **Improvement:** fewer raindrops and snowflakes, and the rain's layer is
  smaller, so it's lighter on older devices. On a slower device (4 cores or
  fewer, or 2 GB or less) there's one layer of rain or snow, no drifting
  cloud, no splashes or puddle ripples and fewer falling leaves. The card's
  `effects: lite` (or `full`) option says which.
- **Fix:** Settings: a picker's list (e.g. the weather entity) is no longer
  cut off by the bottom of its section (e.g. On the map).
## 0.16.0 — Smooth rain, tidier streets and gardens

- **Improvement:** rain, snow and drifting cloud are moved by the browser's
  compositor instead of being redrawn every frame, so they're smooth however
  busy the map is: rain falls in two layers (near and far, three when
  pouring), snow drifts side to side as it falls.
- **Fix:** parked cars are tucked against the kerb, and the traffic drives
  between them and the middle of the road, so they don't drive through each
  other.
- **Fix:** back gardens no longer overlap (houses at odd angles, round
  corners): where two would, the deeper one is cut back. Gardens also stop
  at any building across their whole width, not just the house's.
- **Change:** maps are made again once after updating, for the above.
## 0.15.1 — Lint

- **Fix:** removed the empty `options` and `schema` from `config.yaml` (they're
  Home Assistant's defaults; the add-on linter failed on them).

## 0.15.0 — A living neighbourhood

- **Feature:** gardens: front paths, driveways (with cars, some to a garage),
  hedges and low walls; at the back fences or hedges between gardens,
  patios, conservatories, sheds, trampolines, washing lines, bushes and
  flower beds.
- **Feature:** parks and playing fields mown in stripes, reeds round ponds,
  ducks on them, and a waterfall where a river runs off the edge.
- **Feature:** street furniture: OpenStreetMap's bus stops, benches, post
  boxes and bins, plus benches along footpaths and post boxes at corners.
- **Feature:** traffic: cars and a bus driving the streets, the odd train;
  people walking the pavements, some with a dog (fewer at night or in the
  rain). Card option `motion: false` keeps it still.
- **Feature:** Settings › On the map › **Your house**: solar panels on your
  roof (glinting while producing), your car on the drive (glowing while
  charging) and a heat pump (puffing while running), each from an entity.
- **Feature:** skylights, dormers and satellite dishes on other houses.
- **Feature:** the real sun: shadows from where it is (long in the evening),
  and a golden light near sunrise and sunset.
- **Feature:** landmarks: churches with a spire, schools with a flag and a
  playground, pubs with a sign and picnic benches.
- **Feature:** occasions: Christmas lights in December, pumpkins at
  Halloween, fireworks on Bonfire Night and New Year.
- **Change:** maps are made again once after updating, to add the gardens,
  landmarks and street furniture.
## 0.14.1 — Which dashboard is which

- **Fix:** Settings › Screensaver lists each view with its address (e.g.
  Wall-Display-Large › Home — /wall-display-2/home), so two dashboards with
  the same name (e.g. one copied from the other) can be told apart. Picking
  the wrong one of two same-named dashboards sent taps to the other.
## 0.14.0 — A simpler, smarter screensaver

- **Change:** the screensaver is one switch for everything: on, every screen
  left alone on another dashboard comes back to the map; off, the map stays
  the map. The 🖵 button and the card's `idle_return` option are gone. (Saved
  settings carry over: on if tapping the map went somewhere.)
- **Feature:** **The map is on**: the view the map's on, picked from your
  dashboards' views (e.g. Wall display › Map); the add-on's Map dashboard is
  only made when it's chosen.
- **Feature:** **Tapping the map goes to** is picked from your dashboards'
  views too (or typed).
- **Feature:** the made Home dashboard groups the rooms by floor (Home
  Assistant's floors, bottom floor first), and you choose what each room
  shows (**Things**) and the rooms' order (**↑ ↓**).
- **Improvement:** scrolling starts the wait again too (as well as a touch,
  a tap, a key or the mouse).
## 0.13.0 — The card for every user (kiosk too)

- **Feature:** any signed-in user can see the dashboard card, kiosk and
  other non-administrator users too, so the map can be a kiosk user's home
  page. The add-on writes what the card draws to a file in Home Assistant's
  `www` folder with a long, private name, given to signed-in users in
  `sensor.neighbourhood_view_status`'s `map_url` attribute.
- **Feature:** Settings › Dashboard card › **New private name** for that file.
- **Improvement:** the card looks for a new map, places or settings every
  2 minutes (was 30), downloading only when something's changed.
## 0.12.0 — The map as a screensaver

- **Feature:** Settings › Screensaver: tapping the map on a dashboard goes to
  another dashboard, your own (e.g. `/wall-display-2/home`) or a **Home**
  dashboard made from the rooms (Home Assistant areas) you choose, with a
  view for each room.
- **Feature:** a device told to (the 🖵 button on the map) comes back to the
  map after being left alone for a time you choose.
- **Feature:** a **Map** dashboard (the map filling the screen) and a
  **Neighbourhood View** theme (glassy dark cards over the map's sky, a night
  sky in dark mode) are made for you.
- **Feature:** card options `tap_navigate` and `idle_return`.
## 0.11.1 — Bridges that line up

- **Fix:** each end of a bridge is now as wide as the street it joins (the
  road and its pavements, at that map's size) and carries straight on from
  it, so the kerbs and road line up on both islands; it narrows or widens
  smoothly in between.
## 0.11.0 — Weather on the ground, and the autumn fall

- **Feature:** rain (and heavy rain, thunderstorms, sleet, hail): wet, darker
  roads and pavements, puddles by the kerbs and on pavements with raindrops
  rippling them, and splashes all over; hail leaves hailstones lying about.
- **Feature:** wind (and heavy rain, thunderstorms): the trees sway.
- **Feature:** autumn: some trees thin to bare branches with a few clumps
  of leaves left, leaves lie under the turned trees, and leaves fall now and
  then (blown further when windy). Spring blossom drops petals.
- **Feature:** winter: many trees are bare branches (with snow on them when
  it's snowing).
- **Improvement:** shadows fade under a grey sky; bare and thinning trees
  cast little or none.
## 0.10.1 — Curvier, quieter bridges

- **Improvement:** the bridges to other places are now a curving road (an S
  where the streets don't line up) that leaves each map along its street
  and arches gently over the gap. They're narrower, in the roads' own
  colours, with a slim side and low rails, so they blend in.
## 0.10.0 — Seasons, snow, birds and zebra crossings

- **Feature:** zebra crossings on each street just back from junctions.
- **Feature:** ponds and lakes have a darker edge, a lighter middle and
  ripples spreading across them.
- **Feature:** now and then a flock of birds flies over (by day, when it's
  dry).
- **Feature:** seasons: trees turn in autumn, go dull in winter and some
  blossom in spring; when it's snowing (the weather entity), roofs, lawns,
  parks and trees are white.
## 0.9.0 — A better-looking world

- **Improvement:** the maps float in a sky: blue with drifting clouds by
  day, grey when it's wet, dark with twinkling stars at night, with a soft
  vignette round the edge.
- **Improvement:** buildings and trees cast soft shadows by day.
- **Feature:** street lamps along the bigger streets, lighting pools on the
  pavement at night (and a softer glow round your house).
- **Improvement:** chunks of rock float under each map's edge, rivers
  shimmer, a ring pulses out round your house, and the pin labels have a
  drop shadow.
## 0.8.0 — Bridges

- **Feature:** each other place is joined to your map by a bridge (a road
  deck on a stone span, with railings) between the nearest streets on the
  two maps.
- **Change:** another place's map only shows while someone's there (in its
  zone, or on it by their tracker), and disappears when they leave.
- **Improvement:** the other places sit a little closer to your map.
## 0.7.0 — Other places, and a smaller map

- **Change:** the map goes 150 m each way from your house (it was 250 m),
  so it's quicker to make and closer in. It's made again at the new size
  the first time the add-on starts after updating.
- **Feature:** Settings › Address › **Map size**: how far the map goes
  each way, 50 to 500 m.
- **Feature:** Settings › **Other places**: up to 6 Home Assistant zones
  (work, school…), each drawn as its own little map to the left, right,
  above or below yours, at a size you choose; places on the same side share
  it. Tap one to zoom in round it.
- **Feature:** people who are out are drawn where they are when their
  location is on one of the maps (a face on a stalk), or over the pin of
  the place whose zone they're in.
## 0.6.0 — Weather, people, day and night

- **Feature:** Settings › On the map › **Weather**: a weather entity, drawn
  over the map (rain, snow, fog, cloud shadows, sun, lightning) with a chip
  for it and the temperature.
- **Feature:** Settings › On the map › **People**: up to 6 people, each
  with a home / away (or zone) chip; whoever's home has their picture or
  initials over your house.
- **Feature:** night, from Home Assistant's sun: the map goes dark, some of
  the neighbours' windows are lit, and your house's lights are on (with a
  warm glow) when someone's home and off when nobody is. By day, someone
  home: smoke from your chimney.
- **Improvement:** the zoom and turn buttons are on a dark pill with an
  edge, so they stand out on the light map.
- **Feature:** the card follows the weather and people straight from Home
  Assistant, as they change; its own `weather` and `people` options too.

## 0.5.0 — Greener

- **Improvement:** the ground is lawn green (gardens), with shops',
  offices' and industrial land as hard standing; parks and woods a deeper
  green.
- **Feature:** trees in gardens and open ground, keeping off roads,
  pavements, buildings, car parks and yards.
- **Feature:** a grass verge along residential streets.

## 0.4.0 — Closer in, and roofs along the street

- **Change:** it starts zoomed in on your street and the ones round it
  (2.6×), as close as a game's view; − shows the whole square, and + goes
  closer than before (up to 9×). Your zoom is kept on each device (after
  this update it starts at the new default once).
- **Fix:** houses' roofs run along the nearest street, as British terraces
  and semis do. Before, a terraced house (deeper than it's wide) got its
  ridge front to back, so a row of them looked like a row of fins.

## 0.3.0 — Torn out of the ground

- **Improvement:** the map's edge is no longer a straight-sided board: the
  square looks torn out of the ground, with a ragged, rounded edge, a lip
  of turf, and soil and rock down its sides. Buildings, trees and cars the
  edge would cut through aren't drawn.

## 0.2.0 — Like a video game town

- **Improvement:** houses each get their own look: brick, render or stone
  walls, tiled, slate or clay roofs, gabled or hipped, chimneys, windows on
  every storey and a front door; bungalows, 2 and 3 storeys where
  OpenStreetMap has no height.
- **Improvement:** flats and offices with rows of windows, shops with a
  glass front and a coloured fascia, warehouses with high windows, and
  things on flat roofs.
- **Feature:** pavements with kerbs along the streets, white lines down the
  middle, and cars parked along the kerbs.
- **Improvement:** trees in three kinds (round, pointed, bushes), different
  greens and sizes.
- **Feature:** **+ −** zoom in around your house and back out, on the
  page and the card.

## 0.1.0 — First version

- **Feature:** an isometric drawing of the streets around your home, about
  250 m each way, from OpenStreetMap: buildings (houses with pitched roofs),
  roads, railways, parks, water and trees, with a pin on your house. Turn it
  a quarter at a time.
- **Feature:** Settings › **Address**: your postcode and house number. Your
  house is found from OpenStreetMap's addresses; if it isn't there, click it
  on the Overview (⌂).
- **Feature:** a **dashboard card** (`custom:neighbourhood-view-card`), put
  in place and added to your dashboards' resources by the add-on. It fills
  the screen in a panel view and fits phones, tablets and wall screens.
