"""The catalogue's single source of truth.

CONTENTS.md and index.html are both *regenerated* from this file, never edited
in place, so adding or removing a folder can't leave the two views disagreeing.
Watched state lives here too, read back out of CONTENTS.md on every run.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

CACHE_VERSION = 1


def new_record(key: str, title: str, year: Optional[int], kind: str) -> Dict[str, Any]:
    """A freshly discovered folder, before any enrichment."""
    return {
        "key": key,
        "title": title,
        "year": year,
        "kind": kind,
        "status": "pending",       # pending -> ready once the folder settles
        "signature": "",
        "first_seen": date.today().isoformat(),
        "watched": False,
        # TMDB
        "overview": "",
        "genres": [],
        "runtime": None,
        "rating": None,
        "votes": None,
        "director": None,
        "cast": [],
        "tmdb_id": None,
        "tmdb_url": None,
        "poster": None,
        "enriched": False,
        # local truth
        "seasons": {},
        "episode_count": 0,
        "specials": 0,
        "total_size": 0,
        "tech": {},
        "external_subs": False,
        "video": None,               # primary file, relative to the library
        # model-generated, never factual
        "moods": [],
        "issues": [],
    }


class Cache:
    def __init__(self, path: Path, data: Optional[Dict[str, Any]] = None):
        self.path = path
        self.data = data or {"version": CACHE_VERSION, "entries": {}}
        self.data.setdefault("entries", {})

    @classmethod
    def load(cls, path: Path) -> "Cache":
        if not path.is_file():
            return cls(path)
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            # A corrupt cache is recoverable: everything in it can be rebuilt.
            # Keep the bad file for inspection rather than deleting it silently.
            try:
                path.replace(path.with_suffix(".json.corrupt"))
            except OSError:
                pass
            return cls(path)
        return cls(path, data)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file and rename, so an interrupted run can't truncate
        # a good cache.
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
        os.replace(str(tmp), str(self.path))

    # -- record access -------------------------------------------------

    @property
    def entries(self) -> Dict[str, Dict[str, Any]]:
        return self.data["entries"]

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self.entries.get(key)

    def put(self, record: Dict[str, Any]) -> None:
        self.entries[record["key"]] = record

    def remove(self, key: str) -> None:
        self.entries.pop(key, None)

    def keys(self) -> List[str]:
        return list(self.entries.keys())

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        return iter(self.entries.values())

    def __len__(self) -> int:
        return len(self.entries)

    def ready(self) -> List[Dict[str, Any]]:
        """Records settled enough to publish."""
        return [r for r in self.entries.values() if r.get("status") == "ready"]

    def sync_keys(self, present: List[str]) -> List[str]:
        """Drop records whose folder is gone. Returns the removed keys."""
        gone = [k for k in self.entries if k not in set(present)]
        for key in gone:
            self.remove(key)
        return gone
