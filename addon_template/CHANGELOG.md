# Changelog

## 0.1.3 — README as a how-to, and issue triage

- **Docs:** the README is laid out as a how-to for users (what you need,
  install, set it up, troubleshooting), ready to fill in for a new add-on:
  the issue triage reads it.
- **Docs:** DOCS.md says how issues are triaged (the repository's
  `.github/workflows/issue-triage.yaml`, which covers every add-on in the
  repository, a new one too) and how to take it to another repository.

## 0.1.2 — Passes the add-on linter

- **Fix:** `panel_icon` is no longer set to its default (`mdi:puzzle`),
  which the add-on linter rejects. It's left as a comment in `config.yaml`
  for setting your own add-on's sidebar icon.

## 0.1.1 — Log level applies straight away

- **Fix:** a log level set through the API's settings (or anything other
  than the page's log level buttons) was saved but not used until a
  restart; it now applies at once.

## 0.1.0 — First version

- **Feature:** a working add-on to start from: a web page in the Home
  Assistant sidebar (Overview, Settings, Diagnostics), a live link to
  Home Assistant with an entity picker, its own sensors posted to Home
  Assistant, saved settings, a log level, recent log lines, a diagnostics
  bundle and a restart button.
