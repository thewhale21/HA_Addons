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
- **Update `HANDOVER.md` in the same commit** as any change that alters
  what someone picking this up should know: a new add-on or version, new
  or changed behaviour or settings, a decision the owner made (including
  what they turned down), a new limitation, an idea offered but not built,
  or changes to the owner's setup. Bump its "Last updated" line. Keep it
  a summary, not a changelog. This applies to every agent and tool working
  here (see `AGENTS.md`). Its add-on table must show every add-on's
  current version: `python .github/scripts/check_handover.py` checks, and
  so does GitHub on each push.
- Tests: `cd <addon> && python -m pytest tests/`.
- New add-ons start from `addon_template/` with
  `python scripts/new_addon.py <folder> "<Name>" "<description>"`.
- **OCPP Charge Proxy:** changes go to this repo only. The separate
  `ocpp_charge_proxy` repository (its old home) isn't updated any more
  unless the owner says so.

## Picking this up

Read `HANDOVER.md` first: the owner's setup (Octopus IOG, Sigenergy,
Predbat, the OCPP proxy as a virtual charger), what each add-on does,
recent decisions, known limitations and open ideas.

- **Give the push command as one paste-ready PowerShell line:**
  `cd C:\Users\Matthew\VScodeRepo\HA_Addons; git push origin main <tags>`.
- **Never write credentials** (API keys, tokens) into code, the repo, logs
  or pages; add-ons take them from their options.
- **Writing style** for pages, DOCS.md, changelogs and log lines: plain
  British English, short sentences, "you/your", examples with real times.
  Match what's there.
- **OCPP Charge Proxy:** bump `AUTO_PLAN_VERSION` in `src/automation.py`
  whenever the automatic schedule's planning rules change. Add a test for
  each fix that fails on the old code. The page (`src/static/index.html`)
  has no tests: check its scripts parse and look at it in a browser.
- When the owner asks a question ("question, not an ask"), answer it
  without changing code.
