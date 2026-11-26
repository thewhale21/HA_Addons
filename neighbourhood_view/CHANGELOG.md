# Changelog

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
