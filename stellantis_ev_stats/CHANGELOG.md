# Changelog

## 0.1.0 — First version

- **Feature:** records every trip from the Stellantis Vehicles
  integration's Last trip sensor (distance, energy, time, speed) with the
  outside temperature during it and the SoC before and after, the car's
  range estimate with the SoC and temperature, its battery health (SoH
  capacity and resistance) when it changes, and the usable capacity
  (Battery residual ÷ SoC). Its sensors are found by themselves.
- **Feature:** Overview: the real range at 100% at today's temperature (and
  what's left now), the efficiency over the last 30 days, battery health,
  and the real range against the car's estimate by temperature.
- **Feature:** Temperature tab: every trip's efficiency against the
  temperature, and a table by 5 °C band: trips, miles, mi/kWh, the real
  range (from the energy and from the SoC) and the car's estimate.
- **Feature:** Trips tab, and a Battery tab with the battery health and the
  measured usable capacity over time.
- **Feature:** the last 30 days of Home Assistant's history are read once,
  so there's something to see straight away.
- **Feature:** sensors: real range at 100%, real range left, the car's
  range at 100%, efficiency (30 days and at this temperature), usable
  capacity, battery health and trips recorded.
- **Feature:** settings for the shortest trip counted (2 miles) and the
  usable capacity (measured by default).
