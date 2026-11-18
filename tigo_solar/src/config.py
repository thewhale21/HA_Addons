"""The add-on's options (Settings › Add-ons › Tigo Solar › Configuration): your Tigo
login and system. Home Assistant writes them to /data/options.json; the schema is in
config.yaml and the labels in translations/en.yaml."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields

OPTIONS_PATH = os.environ.get("ADDON_OPTIONS", "/data/options.json")


@dataclass(frozen=True)
class Config:
    username: str = ""
    password: str = ""
    system_id: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.username.strip() and self.password and str(self.system_id).strip())


def load_config(path: str = OPTIONS_PATH) -> Config:
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, ValueError):
        raw = {}  # running outside Home Assistant (development): the defaults
    known = {f.name for f in fields(Config)}
    return Config(**{k: ("" if v is None else str(v)) for k, v in (raw or {}).items() if k in known})
