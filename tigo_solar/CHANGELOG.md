# Changelog

## 0.2.0 — Each panel stacked on the charts, and each panel at any point

- **Fix:** with a panel left out, a day's chart was empty for every day
  before the add-on started (Tigo keeps only each panel's latest reading).
  Those days now estimate each panel's power from the system's power by
  the minute and the panel's share of the day's energy, and say so.
- **Feature:** the charts stack each panel in its own colour (a colour per
  string), by day, week, month and year (**By panel**); **Reclaimed**
  shows what the panels made on their own and what the optimisers
  reclaimed, as before.
- **Feature:** click a point on the chart to see each panel's power and
  reclaimed power at that time (or its energy that day or month), with the
  total; the roof shows each panel then too. **Show this day** opens a
  week's or month's day.
- **Docs:** both.

## 0.1.0 — First version

- **Feature:** reads your Tigo system from the Tigo portal with your login
  (the free plan is enough): each panel's power, reclaimed power and
  energy, and the system's power by the minute and energy by the day,
  every 5 minutes (every minute on the premium plan), and all your history
  from the day the system started, in the background.
- **Feature:** a view of your roof from Tigo's layout, coloured by each
  panel's power now or its energy over the chart's time. Click panels to
  choose which are in the charts; drag them to where they really are.
- **Feature:** production charts by day (power), week, month and year
  (energy), split into what the panels made on their own and what the
  optimisers reclaimed, for the whole system or the panels you choose.
- **Feature:** Home Assistant sensors for the system (power, reclaimed
  power, energy today, this month, this year and ever, reclaimed energy
  today) and each panel (power, reclaimed power, energy today).
