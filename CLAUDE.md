# Working on this repository

Home Assistant add-ons, one folder per add-on (`repository.yaml` at the
top). The owner only runs them inside Home Assistant.

- **Every change bumps the add-on's version** (`<addon>/config.yaml`).
- **Changelog:** a new entry at the top of `<addon>/CHANGELOG.md`, titled
  `## X.Y.Z — Title`, with bullets starting **Feature:**, **Improvement:**,
  **Fix:**, **Change:** or **Docs:**. Old entries aren't rewritten.
- **Commit and tag every release** as `<addon folder>-X.Y.Z`
  (e.g. `ocpp_charge_proxy-2.39.2`). The owner pushes; give them the push
  command with every tag not yet pushed (`git push origin main <tags>`).
- Update the add-on's `DOCS.md` when behaviour changes.
- Tests: `cd <addon> && python -m pytest tests/`.
- New add-ons start from `addon_template/` with
  `python scripts/new_addon.py <folder> "<Name>" "<description>"`.
