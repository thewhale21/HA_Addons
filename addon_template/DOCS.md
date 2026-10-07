# Add-on Template

A working add-on to build a new one from. It has a web page in the Home
Assistant sidebar, a live link to Home Assistant, its own sensors, saved
settings and diagnostics, so a new add-on only needs its own work adding.

## Using it

1. Install the add-on and start it. Open it from the sidebar.
2. **Overview** shows what it's doing: its status, the example entity's
   reading and the example option.
3. **Settings** has the example entity picker: type to search Home
   Assistant's entities, pick one, and its reading appears on the Overview
   and updates live.
4. **Diagnostics › Health** shows the version, uptime and the link to Home
   Assistant; anything wrong also turns the dot next to the title amber or
   red. **Diagnostics › Debug** has the log level (kept after a restart),
   recent log lines, a diagnostics bundle to download and a restart button.

It posts two sensors to Home Assistant, `sensor.addon_template_status` and
`sensor.addon_template_ticks`. They show as unavailable while the add-on is
stopped.

### Options

- **Example option:** shown on the Overview. Replace it with your own.

## Making it your own

Where everything lives (all under this folder):

| What | Where |
| --- | --- |
| Name, version, options and their schema | `config.yaml` (labels in `translations/en.yaml`) |
| Reading the options | `src/config.py` |
| Your add-on's work | `worker()` in `src/__main__.py` (start more tasks next to it) |
| What the web page shows | `src/shared_state.py` (the state) and `renderState()` in `src/static/index.html` |
| Web page and API | `src/static/index.html` and `src/api.py` |
| Home Assistant: entities to follow, service calls | `src/ha_link.py` (`ENTITY_KEYS`, `call_service()`, `query()`) |
| Sensors the add-on posts to Home Assistant | `src/ha_entities.py` (`SENSORS` and `values()`) |
| Settings made on the web page | `src/app_settings.py` |
| Logs, diagnostics, restart | `src/debug_tools.py`, `src/log_filters.py` |
| Python packages | `requirements.txt` (tests: `requirements-dev.txt`) |
| Tests | `tests/` (`python -m pytest tests/`) |
| Icons | `icon.png` (128×128) and `logo.png` (250×100); the sidebar icon is `panel_icon` in `config.yaml` |

Some recipes:

- **Add an option:** add it under `options` and `schema` in `config.yaml`,
  give it a name and description in `translations/en.yaml`, and add a field
  with a default to `Config` in `src/config.py`.
- **Follow another entity:** add a key to `ENTITY_KEYS` in `src/ha_link.py`
  (with the domains it may be), a `<span class="picker" data-key="...">` on
  the Settings tab, and handle it in `entity_changed()` in
  `src/__main__.py`.
- **Do something in Home Assistant:**
  `await link.call_service("light", "turn_on", target={"entity_id": "light.hall"})`.
- **Post another sensor:** add it to `SENSORS` in `src/ha_entities.py` and
  give its value in `values()`. Use `device_class`, `state_class` and
  `unit_of_measurement` so Home Assistant records it properly.
- **Show something new on the page:** add a field to `SharedState`, set it
  in your code, and show it in `renderState()`. Changes are pushed to the
  page within a second. For something on its own tab, add a `<section>`
  and a tab button, and load it in `refreshTab()`.
- **Add an API call:** a handler in `src/api.py` and a route in
  `create_api_app()`; call it from the page with `api('your/path')`.

The page follows Home Assistant's theme (light or dark) when opened from the
sidebar, and works on a phone.

## Releasing a change

1. Make the change, and bump `version` in `config.yaml`.
2. Add an entry at the top of `CHANGELOG.md`: `## X.Y.Z — Title`, then
   bullets starting **Feature:**, **Improvement:**, **Fix:**, **Change:** or
   **Docs:**.
3. Commit, tag it `addon_template-X.Y.Z` (the add-on's folder name and
   the version, as other add-ons share this repository), and push the
   branch and the tag. The Builder workflow builds and publishes the image;
   Home Assistant then offers the update.
