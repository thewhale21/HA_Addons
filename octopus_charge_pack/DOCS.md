# Octopus Charge Pack

A working add-on to build a new one from. It has a web page in the Home
Assistant sidebar, a live link to Home Assistant, its own sensors, saved
settings and diagnostics, so a new add-on only needs its own work adding.

## Using it

See the README (the add-on's **Info** tab) for setting it up, its options
and its sensors. In short: enter your Octopus API key on the
**Configuration** tab and start it.

1. **Overview** shows its status across the top, then the next discharge
   (with its local date, start and end as the date and time sensors give
   them) and next charge, each with its own planned dispatches.
2. **Settings** has the device and read interval (both drop-downs, applied
   at once).
3. **Diagnostics** has its health, the sensors it posts, the log
   and a diagnostics bundle (the API key is always hidden).

## How it works

- `src/octopus.py`: the Octopus GraphQL API. A Kraken token from the API key
  (renewed every 45 minutes, and at once if Octopus says it's expired), then
  `flexPlannedDispatches(deviceId)`. The account's devices
  (`viewer.accounts`, then `devices(accountNumber)`) are read at start and
  every 6 hours, for the Settings tab's drop-down.
- `src/app_settings.py`: the settings made on the page (device, read
  interval, log level), kept in `/data/settings.json`. A change wakes the
  reader at once. Pre-0.3.0 `device_id` / `poll_seconds` options are copied
  over once.
- `src/reader.py`: at the read interval, reads the dispatches and works out
  the sensors' values. The last discharge start time is kept in
  `/data/state.json`, as the template sensor kept its state (and the
  last charge start time, the same way).
- `src/dispatches.py`: the logic of the old template sensors, with no I/O:
  the next charge (energyAddedKwh < 0) and discharge (> 0) that hasn't
  ended, and each one's local date and times.
- `src/ha_entities.py`: the sensors, posted through the Supervisor. If a
  read fails they keep their last values (so a short Octopus outage doesn't
  change Predbat's plan), and the status sensor says what went wrong.

## Issues: automatic triage

Every new issue in the repository is read by an AI model with the add-on's
README, its source files and latest changes, and gets a comment: what kind
of issue it is, what's missing, the likely cause and a suggested fix, plus
labels (bug, enhancement or question, and the add-on's folder). It's
`.github/workflows/issue-triage.yaml`, with the prompt built by
`.github/scripts/triage_prompt.py`; it finds the add-ons by their
`config.yaml`, so a new add-on is covered as soon as it's in the
repository. Keep the README's how-to (what it needs, how to set it up,
troubleshooting) and each `src/` file's first docstring line up to date:
they're what it works from.

It works with any OpenAI-compatible chat completions API. Set it up under
the repository's **Settings › Secrets and variables › Actions**: the secret
`TRIAGE_API_KEY` (the provider's API key), and the variables
`TRIAGE_API_URL` (its URL ending `/chat/completions`) and `TRIAGE_MODEL`.
Until all three are set it skips, without failing. **Actions › Issue triage
› Run workflow** triages an issue again. In another repository, copy those
two files and set the same secret and variables.

## Releasing a change

1. Make the change, and bump `version` in `config.yaml`.
2. Add an entry at the top of `CHANGELOG.md`: `## X.Y.Z — Title`, then
   bullets starting **Feature:**, **Improvement:**, **Fix:**, **Change:** or
   **Docs:**.
3. Commit, tag it `octopus_charge_pack-X.Y.Z` (the add-on's folder name and
   the version, as other add-ons share this repository), and push the
   branch and the tag. The Builder workflow builds and publishes the image;
   Home Assistant then offers the update.
