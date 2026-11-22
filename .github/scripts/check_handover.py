"""Checks HANDOVER.md is up to date: every add-on (a folder with config.yaml) is in it, on a line
with its current version. Run by .github/workflows/handover.yaml; locally:
python .github/scripts/check_handover.py"""
import pathlib
import re
import sys

root = pathlib.Path(__file__).resolve().parents[2]
handover = (root / "HANDOVER.md").read_text(encoding="utf-8").splitlines()
stale = []
for config in sorted(root.glob("*/config.yaml")):
    folder = config.parent.name
    m = re.search(r'^version:\s*"?([^"\s]+)"?', config.read_text(encoding="utf-8"), re.M)
    if not m:
        continue
    version = m.group(1)
    if not any(f"`{folder}`" in line and re.search(rf"(?<![\d.]){re.escape(version)}(?![\d.])", line) for line in handover):
        stale.append(f"{folder} {version}")
if stale:
    print("HANDOVER.md is out of date. Update it (and its 'Last updated' line) for: " + ", ".join(stale))
    print("See AGENTS.md: keep HANDOVER.md current in the same commit as the change.")
    sys.exit(1)
print("HANDOVER.md lists every add-on at its current version.")
