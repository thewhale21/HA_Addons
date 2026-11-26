# Neighbourhood View

An isometric drawing of the streets around your home, from OpenStreetMap,
as the add-on's page and as a dashboard card.

## Using it

1. Install the add-on, start it and open it from the sidebar.
2. **Settings › Address:** your **postcode** (UK) and **house number**,
   then **Save** (or Enter). The map's made straight away, usually in a few
   seconds, and kept: it's made again every 30 days, when you change your
   address, or now with **Refresh**.
3. **Overview:** the streets about 250 m each way from your house (a 500 m
   square), with a pin on your house showing its number.
   - **⟲ ⟳** turn it a quarter at a time (remembered on each device).
   - **⌂** picks your house: click it, then click your house. The map's
     made again centred on it, and it's kept until you change your address.
     Use it when the pin isn't on your house.
   - The chip at the top says how your house was found: from your address
     (OpenStreetMap has it), the building nearest your address, picked by
     you, or not found (the map's centred on your postcode: pick it).

## What's drawn

From OpenStreetMap: buildings, roads and paths, railways and tram lines,
parks, grass, woods, sports pitches, car parks, water and rivers, and the
trees it has. Where it has no heights, buildings get one by type (a house
6 m, flats 12 m, shops 8 m, garages 2.8 m...), or 3 m a storey where the
number of storeys is known. Houses get a pitched roof along their longer
side. Woods and parks get trees where OpenStreetMap has none mapped, and
residential streets get a few street trees (placed the same way each time,
so they don't move). Your house is drawn in blue.

How your house is found: postcodes.io gives the postcode's centre, then
OpenStreetMap's addresses within 400 m with your house number and postcode.
Not every house has its address in OpenStreetMap; then it's centred on the
postcode and the pin's on the building nearest it, until you pick yours.

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
house instead of the whole square small in the middle. ⟲ ⟳ turn it.

Options:

| Option | What it does |
| --- | --- |
| `label` | The pin's text (default: NO. and your house number, or HOME) |
| `height` | The card's height outside a panel view, e.g. `500px` |
| `addon` | The add-on's slug, if it can't be found (e.g. `a1b2c3d4_neighbourhood_view`) |
| `url` | Read the map from this address instead of through Home Assistant (e.g. `http://homeassistant.local:8099/`) |

The card reads the map from the add-on through Home Assistant's ingress, as
the add-on's page does, so it needs an **administrator** account. It reads
it again every 30 minutes. The card's file has nothing about you in it.

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
house) to OpenStreetMap's Overpass servers, when the map is made. Nothing
else leaves Home Assistant. The map's kept in the add-on's own data.

## Diagnostics

**Diagnostics › Health** shows the version, uptime and the link to Home
Assistant. **Diagnostics › Debug** has the log level, recent log lines, a
diagnostics bundle and a restart button.

Map data © OpenStreetMap contributors, under the Open Database Licence.
