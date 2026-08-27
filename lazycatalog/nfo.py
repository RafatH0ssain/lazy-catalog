"""Kodi/Jellyfin/Plex sidecar files.

Writing an .nfo next to the video means any media server identifies the title
instantly, with no scraping and no renaming of your files. It is the cheap half
of media-server support: interoperability without a second catalogue to keep in
sync.

This is the only part of the tool that writes inside a title's folder, so it
only runs when asked for explicitly.
"""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional


def _text(parent: ET.Element, tag: str, value: Any) -> None:
    if value in (None, "", []):
        return
    ET.SubElement(parent, tag).text = str(value)


def build(record: Dict[str, Any]) -> bytes:
    kind = record.get("kind", "film")
    root = ET.Element("tvshow" if kind == "series" else "movie")

    _text(root, "title", record.get("title"))
    _text(root, "year", record.get("year"))
    _text(root, "plot", record.get("overview"))
    if record.get("rating"):
        ratings = ET.SubElement(root, "ratings")
        rating = ET.SubElement(ratings, "rating", {"name": "themoviedb",
                                                  "max": "10", "default": "true"})
        _text(rating, "value", record["rating"])
        _text(rating, "votes", record.get("votes"))
    if kind != "series":
        _text(root, "runtime", record.get("runtime"))
    for genre in record.get("genres") or []:
        _text(root, "genre", genre)
    if record.get("director"):
        for name in str(record["director"]).split(", "):
            _text(root, "director" if kind != "series" else "creator", name)
    for name in record.get("cast") or []:
        actor = ET.SubElement(root, "actor")
        _text(actor, "name", name)
    if record.get("tmdb_id"):
        ET.SubElement(root, "uniqueid",
                      {"type": "tmdb", "default": "true"}).text = str(record["tmdb_id"])

    ET.indent(root, space="  ") if hasattr(ET, "indent") else None
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + \
        ET.tostring(root, encoding="utf-8")


def write(record: Dict[str, Any], folder: Path,
          poster_source: Optional[Path] = None) -> Path:
    """Write the sidecar, and copy the cached poster in beside it."""
    name = "tvshow.nfo" if record.get("kind") == "series" else "movie.nfo"
    target = folder / name
    target.write_bytes(build(record))

    if poster_source and poster_source.is_file():
        destination = folder / "poster.jpg"
        if not destination.exists():
            shutil.copyfile(str(poster_source), str(destination))
    return target
