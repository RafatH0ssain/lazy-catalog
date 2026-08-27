"""Subtitle downloads, delegated to subliminal.

Subliminal is an external CLI rather than a dependency, for the same reason
ffprobe is: it can be missing without breaking anything else, and it keeps this
project free of a virtualenv. Install it with `uv tool install subliminal`.

Downloads only ever run from an explicit `lazy-catalog subs`, never from the
background job, because the free providers are rate limited and a watch loop
could burn a day's quota in one sweep.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

TIMEOUT = 180


def available() -> bool:
    return shutil.which("subliminal") is not None


def needs_subtitles(record: Dict[str, Any]) -> bool:
    """True when neither the container nor a sidecar file has subtitles."""
    if record.get("external_subs"):
        return False
    return not ((record.get("tech") or {}).get("subs") or [])


def fetch(video: Path, languages: Sequence[str]) -> Tuple[bool, str]:
    if not available():
        return False, "subliminal is not installed"

    command = ["subliminal", "download"]
    for language in languages:
        command += ["-l", language]
    command.append(str(video))

    try:
        done = subprocess.run(command, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except OSError as exc:
        return False, str(exc)

    output = done.stdout.decode("utf-8", "replace").strip()
    last = output.splitlines()[-1] if output else ""
    # Subliminal reports "Downloaded N subtitle" and exits 0 either way, so the
    # message is what tells you whether anything actually arrived.
    if "Downloaded 0 subtitle" in output or done.returncode != 0:
        return False, last or "nothing found"
    return True, last or "downloaded"


def candidates(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in records if needs_subtitles(r)]
