"""Reading and writing the add-on's JSON files in /data, safely.

Writes are atomic: the data goes to a temp file, flushed to disk, then renamed
over the file in one step, so a power cut mid-write leaves the old file or the
new one, never half of one. With `backup`, the previous good version is kept
as "<file>.bak" (a corrupt file never overwrites a good backup), and reading
falls back to it if the file is missing or unreadable.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def load(path: Optional[str], what: str, use: Callable[[dict], Any], backup: bool = True) -> bool:
    """Read `path` (else its backup) and hand the contents (a dict) to `use`. If the
    file is unreadable, isn't a dict or `use` raises, the backup is tried. Returns
    whether one was used. `what` names it in the log, e.g. "Automation settings"."""
    if not path:
        return False
    for candidate in (path, path + ".bak") if backup else (path,):
        try:
            with open(candidate, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("not a JSON object")
            use(data)
        except FileNotFoundError:
            continue
        except Exception as err:
            logger.warning("%s %s are unreadable (%s)", what, candidate, err)
            continue
        if candidate != path:
            logger.warning("%s: using the backup %s (the main file is missing or unreadable)", what, candidate)
        return True
    return False


def _valid(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            return isinstance(json.load(f), dict)
    except (OSError, ValueError, UnicodeDecodeError):
        return False


def _fsync_dir(folder: str) -> None:
    """Make the renames durable too (best effort; not supported everywhere)."""
    try:
        fd = os.open(folder or ".", os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def save(path: Optional[str], data: dict, what: str, backup: bool = True, quiet: bool = False, **dump) -> bool:
    """Write `data` to `path` atomically (see the module docstring). Returns whether it
    was written; a failure is logged (at debug level with `quiet`), never raised.
    `dump`: json.dump's options, e.g. indent=1 or default=str."""
    if not path:
        return False
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, **dump)
            f.flush()
            os.fsync(f.fileno())
        if backup and _valid(path):
            os.replace(path, path + ".bak")
        os.replace(tmp, path)
        _fsync_dir(os.path.dirname(path))
        return True
    except Exception:
        (logger.debug if quiet else logger.warning)("Could not save %s (%s)", what, path, exc_info=True)
        return False
