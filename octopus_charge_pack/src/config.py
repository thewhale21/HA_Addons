"""The add-on's options (Settings › Add-ons › Octopus Charge Pack › Configuration).

Home Assistant writes them to /data/options.json; the schema is in
config.yaml and the labels in translations/en.yaml."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields

OPTIONS_PATH = os.environ.get("ADDON_OPTIONS", "/data/options.json")


@dataclass(frozen=True)
class Config:
    api_key: str = ""  # Octopus API key (sk_live_...)
    # Options before 0.3.0, read once to copy them to the page's settings (src/app_settings.py):
    device_id: str = ""  # the device whose dispatches to follow
    poll_seconds: int = 60  # how often the planned dispatches are read


def load_config(path: str = OPTIONS_PATH) -> Config:
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, ValueError):
        raw = {}  # running outside Home Assistant (development): the defaults
    known = {f.name for f in fields(Config)}
    out = {k: v for k, v in (raw or {}).items() if k in known}
    for key in ("api_key", "device_id"):
        out[key] = str(out.get(key) or "").strip()
    if "poll_seconds" in out:
        out["poll_seconds"] = max(30, min(3600, int(out["poll_seconds"] or 60)))
    return Config(**out)
