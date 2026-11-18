# Changelog

## 0.4.0 — Each panel through every past day, from Tigo

- **Feature:** Tigo keeps each panel's power and reclaimed power every 15
  minutes (the time slider in the Tigo app), so once the rest of the
  history is read, the add-on reads them back for every earlier day,
  newest first, gently (about 70 requests a day of history). Past days
  then show each panel's own power and reclaimed power through the day,
  not an estimate; so does any time the add-on was stopped. The first few
  answers are checked against the system's power before the rest are
  trusted; if they don't add up, it stops and those days stay estimated.
- **Improvement:** **History** shows how far back each panel's power has
  been read, and whether it's still reading.

## 0.3.3 — Some panels chosen look like the whole system

- **Fix:** on a day's chart, with some panels chosen (not all), the
  estimated power was drawn every 5 minutes, while the whole system is
  drawn every minute, so the two looked quite different (smoothed peaks
  and dips, and a different end of the day). Each panel's estimate is now
  every minute too, so the shape is the same, just smaller.

## 0.3.2 — Choose a string's panels in one click

- **Feature:** under the roof, next to **All panels** and **None**, a
  button for each string (**String A**, **String B**…) chooses just that
  string's panels, with a swatch of its colour on the charts. The button
  for what's chosen is highlighted.

## 0.3.1 — The whole day by panel, and the chart's colours after a restart

- **Fix:** **By panel** on a day's chart showed only the time since the
  add-on started recording each panel (e.g. from 9am after a restart).
  Before that, and in any gap while the add-on was stopped, each panel is
  now estimated from the system's power, as on earlier days, and the note
  under the chart says the day is partly estimated.
- **Fix:** the chart was grey after the add-on restarted, until you
  switched to **Reclaimed** and back: it was drawn before the add-on had
  read your panels from Tigo. It's drawn again in their colours as soon as
  they come.

## 0.3.0 — Highlight a time on the chart, and reclaimed on the roof

- **Feature:** drag across the chart to highlight a time (part of a day,
  or a run of days or months). Under the chart: what was made and
  reclaimed over it, the peak and average power (or the average a day or
  month), and each panel's energy, share, reclaimed energy and peak. The
  roof colours each panel by its energy over that time. A click still
  picks a single point.
- **Feature:** each panel on the roof shows its reclaimed power in
  brackets under its number (or its reclaimed energy, for a point or a
  time picked on a day's chart). Not shown with **Energy**: Tigo keeps
  each panel's reclaimed energy only through the day.
- **Improvement:** small amounts of energy are shown in Wh, not as
  0.00 kWh.

## 0.2.1 — Each panel outlined in its chart colour

- **Improvement:** each panel on the roof is outlined in its colour on the
  charts, so you can tell which is which. The chart colours are now blues,
  purples and pinks (a hue per string, lighter along it), not the greens
  and yellows a panel is filled with for its power or energy.
- **Change:** chosen panels are no longer outlined in blue: the ones left
  out are faded instead.

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
