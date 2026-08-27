"""Generate and load the launchd agent that keeps the catalogue current.

WatchPaths fires within seconds of a folder appearing or disappearing, which
covers the common case. StartInterval is the safety net: it catches downloads
that were still being written when the watch fired, and any change missed while
the machine was asleep.

The plist is generated rather than shipped, so nothing in the repo contains a
username or a path specific to one machine.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

LABEL = "com.lazycatalog.watch"
INTERVAL = 1800  # 30 minutes


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "{}.plist".format(LABEL)


def build_plist(library: Path, repo: Path, state: Path,
                config_path: Path, python: str) -> Dict[str, Any]:
    env = {
        # launchd jobs get a minimal PATH, so ffprobe and subliminal would be
        # invisible without this.
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "LAZY_CATALOG_CONFIG": str(config_path),
    }
    return {
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "lazycatalog", "update", "--quiet"],
        "WorkingDirectory": str(repo),
        "EnvironmentVariables": env,
        "WatchPaths": [str(library)],
        "StartInterval": INTERVAL,
        "RunAtLoad": False,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "Nice": 5,
        "StandardOutPath": str(state / "run.log"),
        "StandardErrorPath": str(state / "run.log"),
    }


def _launchctl(args: List[str]) -> Tuple[int, str]:
    try:
        done = subprocess.run(["launchctl"] + args, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return done.returncode, done.stdout.decode("utf-8", "replace").strip()


def install(library: Path, repo: Path, state: Path, config_path: Path) -> Tuple[bool, str]:
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    payload = build_plist(library, repo, state, config_path, sys.executable)
    with path.open("wb") as fh:
        plistlib.dump(payload, fh)

    target = "gui/{}".format(os.getuid())
    _launchctl(["bootout", "{}/{}".format(target, LABEL)])   # ignore "not loaded"
    code, output = _launchctl(["bootstrap", target, str(path)])
    if code != 0:
        return False, "launchctl bootstrap failed: {}".format(output or code)
    return True, str(path)


def uninstall() -> Tuple[bool, str]:
    target = "gui/{}/{}".format(os.getuid(), LABEL)
    _launchctl(["bootout", target])
    path = plist_path()
    if path.is_file():
        path.unlink()
        return True, str(path)
    return True, "nothing installed"


def status() -> str:
    code, output = _launchctl(["list", LABEL])
    if code != 0:
        return "not loaded"
    return "loaded" + (" — {}".format(output.splitlines()[0]) if output else "")
