"""A single-holder lock, so a launchd trigger can't race a manual run."""

from __future__ import annotations

import errno
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class AlreadyRunning(Exception):
    pass


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno == errno.EPERM
    return True


@contextmanager
def held(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        # A lock left behind by a killed run shouldn't block the tool forever.
        try:
            pid = int(path.read_text(encoding="utf-8").strip() or 0)
        except (ValueError, OSError):
            pid = 0
        if pid and _alive(pid):
            raise AlreadyRunning("another run is in progress (pid {})".format(pid))
        path.unlink(missing_ok=True)
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)

    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        try:
            path.unlink()
        except OSError:
            pass
