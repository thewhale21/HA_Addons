# Home Assistant Add-on: Neighbourhood View

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

An isometric drawing of the streets around your home, about 250 m each
way: buildings (houses with pitched roofs), roads, railways, parks, water
and trees, from OpenStreetMap, with a pin on your house. It's the add-on's
page in the sidebar, and a card for your dashboards that fills the screen
on a phone, tablet or wall screen.

[Full documentation][docs] (also the add-on's **Documentation** tab).

---

## What you need

- Home Assistant OS or Supervised (add-ons need the Supervisor).
- A UK address (the postcode is looked up with postcodes.io).
- Internet access for the add-on (postcodes.io and OpenStreetMap), only
  when the map is made.

## Install

1. Add this repository to Home Assistant:
   **Settings › Add-ons › Add-on store › ⋮ › Repositories**, and add
   `https://github.com/thewhale21/HA_Addons`.
2. Find **Neighbourhood View** in the store and click **Install**.
3. **Start** it, turn on **Show in sidebar**, and open it.

## Set it up

1. **Settings › Address:** your postcode and house number, then **Save**.
   The map's made in a few seconds.
2. **Overview:** your street, with your house in the middle. If the pin
   isn't on your house (not every house has its address in OpenStreetMap),
   click **⌂** and then your house.
3. **A dashboard:** add a view with the type **Panel (single card)** and a
   card with `type: custom:neighbourhood-view-card`.

## Its Home Assistant entities

| Entity | |
| --- | --- |
| `sensor.neighbourhood_view_status` | What it's doing (e.g. Ready, Making the map) |

## Troubleshooting

- **"That postcode wasn't found":** check it on the Settings tab.
- **"OpenStreetMap's server is busy":** it tries again in 15 minutes, or
  press **Refresh**.
- **The card says it needs an administrator account:** it reads the map
  through the add-on, which Home Assistant only allows administrators.
- **Asking for help:** **Diagnostics › Debug** has the log and a
  diagnostics bundle to download. Attach it to a
  [GitHub issue](https://github.com/thewhale21/HA_Addons/issues).

Map data © OpenStreetMap contributors (ODbL).

[docs]: https://github.com/thewhale21/HA_Addons/blob/main/neighbourhood_view/DOCS.md
[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
