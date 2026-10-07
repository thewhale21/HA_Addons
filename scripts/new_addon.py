#!/usr/bin/env python3
"""Start a new add-on from the template.

    python scripts/new_addon.py my_addon "My Add-on" ["What it does"]

Copies addon_template/ to my_addon/, renaming everything (folder, slug,
name, entity IDs, image, the s6 service) and starting it at version 0.1.0
with a fresh changelog. Run it at the top of the repository, then add the
add-on to the README's list.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "addon_template"
OLD_SLUG, OLD_DASHED, OLD_NAME = "addon_template", "addon-template", "Add-on Template"
OLD_DESCRIPTION = "A starting point for a Home Assistant add-on with a web page"
TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".md", ".txt", ".html", ".json", ""}


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    slug, name = argv[1].strip(), argv[2].strip()
    description = argv[3].strip() if len(argv) > 3 else f"{name} for Home Assistant"
    if not re.fullmatch(r"[a-z][a-z0-9_]*", slug):
        print("The folder name must be lower case letters, digits and _ (e.g. my_addon)")
        return 2
    target = ROOT / slug
    if target.exists():
        print(f"{target} already exists")
        return 1
    dashed = slug.replace("_", "-")
    shutil.copytree(TEMPLATE, target, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))

    # The s6 service folder and its entry in the user bundle
    s6 = target / "rootfs/etc/s6-overlay/s6-rc.d"
    (s6 / OLD_DASHED).rename(s6 / dashed)
    (s6 / "user/contents.d" / OLD_DASHED).rename(s6 / "user/contents.d" / dashed)

    for path in target.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        new = (text.replace(OLD_DESCRIPTION, description).replace(OLD_NAME, name)
               .replace(OLD_SLUG, slug).replace(OLD_DASHED, dashed))
        if new != text:
            path.write_text(new, encoding="utf-8")

    # Version 0.1.0 and a fresh changelog
    config = target / "config.yaml"
    config.write_text(re.sub(r'^version: ".*"$', 'version: "0.1.0"', config.read_text(encoding="utf-8"),
                             flags=re.M), encoding="utf-8")
    (target / "CHANGELOG.md").write_text(
        "# Changelog\n\n## 0.1.0 — First version\n\n- **Feature:** started from the add-on template.\n",
        encoding="utf-8")
    print(f"Created {slug}/ ({name}). Next:")
    print(f"  - replace {slug}/icon.png and {slug}/logo.png")
    print(f"  - edit {slug}/config.yaml, DOCS.md and README.md, and add it to the repository README")
    print(f"  - put its work in {slug}/src/__main__.py (see its DOCS.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
