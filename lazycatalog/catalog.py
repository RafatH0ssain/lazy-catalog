"""Orchestration: scan the library, settle new folders, enrich, render.

The order matters. Watched state is read back from CONTENTS.md *before*
anything is written, and the file is only rewritten from the cache, so a run
that dies halfway leaves the previous file intact.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import config, render_md, scan
from .cache import Cache, new_record

CONTENTS_NAME = "CONTENTS.md"
CACHE_NAME = "cache.json"
WEB_NAME = "index.html"

# How patiently a newly seen folder is watched before it is published. A
# torrent creates its folder long before the file is finished, so a folder is
# only catalogued once its size stops changing between checks.
SETTLE_ROUNDS = 4
SETTLE_SECONDS = 30

Reporter = Callable[[str], None]


def _noop(_message: str) -> None:
    pass


def _apply_local_facts(record: Dict[str, Any], entry: scan.Entry) -> None:
    """Copy across everything the filesystem knows. Always authoritative."""
    record["kind"] = entry.kind
    record["total_size"] = entry.total_size
    record["episode_count"] = entry.episode_count
    record["seasons"] = {str(k): v for k, v in sorted(entry.seasons.items())}
    record["external_subs"] = entry.external_subs
    record["issues"] = list(entry.issues)


def update(
    cfg: Dict[str, Any],
    settle_rounds: int = SETTLE_ROUNDS,
    settle_seconds: int = SETTLE_SECONDS,
    enrich: Optional[Callable[[Dict[str, Any], scan.Entry], None]] = None,
    report: Reporter = _noop,
    now: Optional[datetime] = None,
    force_ready: bool = False,
) -> Dict[str, Any]:
    """Bring the cache and CONTENTS.md in line with what's on disk."""
    root = config.library_path(cfg)
    state = config.state_dir(cfg)
    cache_path = state / CACHE_NAME

    # An existing library seen for the first time isn't a pile of in-progress
    # downloads, so import it immediately instead of making the user sit
    # through a settle cycle for files that finished months ago.
    if not cache_path.is_file():
        force_ready = True

    cache = Cache.load(cache_path)

    entries = scan.scan_library(root)
    by_key = {e.key: e for e in entries}

    # Ticked boxes are a human input; read them before the file is replaced.
    contents = root / CONTENTS_NAME
    if contents.is_file():
        watched = render_md.read_watched(contents.read_text(encoding="utf-8"))
        for key, is_watched in watched.items():
            record = cache.get(key)
            if record:
                record["watched"] = is_watched

    removed = cache.sync_keys(list(by_key))
    for key in removed:
        report("removed: {}".format(key))

    added: List[str] = []
    for entry in entries:
        record = cache.get(entry.key)
        if record is None:
            record = new_record(
                entry.key, entry.parsed.title, entry.parsed.year, entry.kind)
            cache.put(record)
            added.append(entry.key)
            report("new: {}".format(entry.key))
        _apply_local_facts(record, entry)

    # Settle pass: a folder whose signature is unchanged since last look is done
    # being written and can be published.
    pending = _settle(
        cache, by_key, settle_rounds, settle_seconds, report, force_ready)

    if enrich:
        for record in cache.ready():
            if record.get("enriched"):
                continue
            entry = by_key.get(record["key"])
            if entry is not None:
                enrich(record, entry)

    cache.save()

    ready = cache.ready()
    contents.write_text(render_md.render(ready, now=now), encoding="utf-8")
    web = write_web(cfg, ready, now=now)

    return {
        "added": added,
        "removed": removed,
        "pending": pending,
        "total": len(ready),
        "contents": contents,
        "web": web,
    }


def _settle(
    cache: Cache,
    by_key: Dict[str, scan.Entry],
    rounds: int,
    seconds: int,
    report: Reporter,
    force_ready: bool = False,
) -> List[str]:
    """Promote pending records whose folders have stopped changing."""
    def sweep() -> List[str]:
        still: List[str] = []
        for record in cache:
            if record.get("status") == "ready":
                continue
            entry = by_key.get(record["key"])
            if entry is None:
                continue
            signature = scan.folder_signature(entry.path)
            if force_ready and not entry.incomplete:
                record["signature"] = signature
                record["status"] = "ready"
                continue
            if entry.incomplete:
                record["signature"] = signature
                still.append(record["key"])
                continue
            if signature and signature == record.get("signature"):
                record["status"] = "ready"
                report("settled: {}".format(record["key"]))
            else:
                record["signature"] = signature
                still.append(record["key"])
        return still

    pending = sweep()
    attempts = 0
    while pending and attempts < rounds:
        time.sleep(seconds)
        attempts += 1
        report("waiting on {} folder(s) to finish downloading".format(len(pending)))
        for key in list(pending):
            entry = by_key.get(key)
            if entry is not None:
                # Re-scan so a folder that just gained its final file is seen.
                by_key[key] = scan.scan_folder(entry.path)
        pending = sweep()

    return pending


def rebuild(cfg: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Throw the cache away and start over, keeping watched state."""
    state = config.state_dir(cfg)
    cache_path = state / CACHE_NAME
    contents = config.library_path(cfg) / CONTENTS_NAME

    watched: Dict[str, bool] = {}
    if contents.is_file():
        watched = render_md.read_watched(contents.read_text(encoding="utf-8"))

    if cache_path.is_file():
        cache_path.unlink()

    # Nothing has a recorded signature now, so publish immediately rather than
    # making the user wait out a settle cycle for files that are already there.
    kwargs.setdefault("settle_rounds", 0)
    kwargs.setdefault("force_ready", True)
    result = update(cfg, **kwargs)

    if watched:
        cache = Cache.load(cache_path)
        for key, is_watched in watched.items():
            record = cache.get(key)
            if record:
                record["watched"] = is_watched
        cache.save()
        ready = cache.ready()
        contents.write_text(
            render_md.render(ready, now=kwargs.get("now")), encoding="utf-8")
        write_web(cfg, ready, now=kwargs.get("now"))
    return result


def write_web(cfg: Dict[str, Any], records, now: Optional[datetime] = None) -> Path:
    """Render the browsable page next to the cache, posters and all."""
    from . import render_web

    target = config.state_dir(cfg) / WEB_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_web.render(records, now=now), encoding="utf-8")
    return target
