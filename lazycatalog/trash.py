"""Move something to the macOS Trash, never delete it outright.

Going through Finder rather than unlinking means the item keeps its Put Back
entry and can be recovered from the Trash the ordinary way. This tool should
never be the reason a film is gone for good.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Tuple

TIMEOUT = 30

# Passing the path as an argument rather than interpolating it into the script
# means no quoting or escaping to get wrong, whatever the filename contains.
SCRIPT = '''on run argv
    tell application "Finder" to delete (POSIX file (item 1 of argv) as alias)
end run'''


def check(path: Path, library: Path) -> Tuple[bool, str]:
    """Refuse anything that isn't a real item inside the library.

    The caller found this path through the cache, which can be stale or
    hand-edited, so it is proved rather than trusted before anything moves.
    """
    library = library.resolve()
    try:
        resolved = path.resolve()
    except OSError as exc:
        return False, str(exc)

    if resolved == library:
        return False, "That is the library folder itself."
    try:
        resolved.relative_to(library)
    except ValueError:
        return False, "That path is outside the library: {}".format(resolved)
    if not resolved.exists():
        return False, "That path does not exist any more: {}".format(resolved)
    return True, ""


def move(path: Path) -> Tuple[bool, str]:
    """Hand the item to Finder. Returns (moved, message)."""
    try:
        done = subprocess.run(["osascript", "-e", SCRIPT, str(path)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if done.returncode != 0:
        return False, done.stdout.decode("utf-8", "replace").strip() or "Finder refused"
    return True, "Moved to Trash"
