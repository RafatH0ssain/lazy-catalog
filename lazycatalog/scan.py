"""Walk the library and describe what is on disk.

Nothing here reaches the network or a model: this is the ground truth that
every later stage is layered on top of.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import parse

VIDEO_EXTS = {
    ".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".flv", ".webm",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".divx", ".ogm",
}
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".sub", ".vtt", ".idx"}

# Partial-download markers left by torrent clients and browsers.
INCOMPLETE_SUFFIXES = (".part", ".!qb", ".crdownload", ".aria2", ".download", ".tmp")

STATE_DIR_NAME = ".lazy"

# Folders whose contents are bonus material, not the show. A release can nest a
# full "Season 01" tree inside Extras, so these are excluded by path rather than
# by filename — otherwise an animatic outranks the actual first episode and
# inflates the episode count.
EXTRA_DIRS = {"extras", "featurettes", "behind the scenes", "deleted scenes",
              "interviews", "trailers", "trailer", "sample", "samples", "other",
              "bonus", "bloopers"}


@dataclass
class VideoFile:
    path: Path
    size: int
    season: Optional[int] = None
    episode: Optional[int] = None
    extra: bool = False


@dataclass
class Entry:
    """One top-level folder in the library."""

    key: str                      # folder name; the cache is keyed on this
    path: Path
    kind: str                     # "film" | "series"
    parsed: parse.ParsedName
    videos: List[VideoFile] = field(default_factory=list)
    seasons: Dict[int, int] = field(default_factory=dict)   # season -> episodes
    has_extras: bool = False
    external_subs: bool = False
    incomplete: bool = False
    total_size: int = 0
    issues: List[str] = field(default_factory=list)

    @property
    def episode_count(self) -> int:
        """Episodes in numbered seasons. Specials are counted separately so a
        show isn't described as "Season 1, 40 episodes" when 14 of those are
        season-zero extras."""
        return sum(count for season, count in self.seasons.items() if season >= 1)

    @property
    def specials(self) -> int:
        return self.seasons.get(0, 0)

    def primary_video(self) -> Optional[VideoFile]:
        """The file to play when you pick this title.

        For a film that is simply the biggest file. For a series it is the
        earliest episode, since the largest would be an arbitrary mid-season
        one and starting a show at episode 7 helps nobody.
        """
        if not self.videos:
            return None
        main = [v for v in self.videos if not v.extra] or self.videos
        if self.kind == "series":
            episodic = [v for v in main if v.season is not None]
            if episodic:
                # Season 0 is specials and pilots, so it sorts last: starting a
                # show means episode one of season one, not a bonus reel.
                return min(episodic, key=lambda v: (0 if v.season >= 1 else 1,
                                                    v.season, v.episode or 0,
                                                    v.path.name))
        return max(main, key=lambda v: v.size)


def _is_incomplete(name: str) -> bool:
    low = name.lower()
    return low.endswith(INCOMPLETE_SUFFIXES)


def scan_folder(path: Path) -> Entry:
    """Describe a single library folder."""
    parsed = parse.parse_folder(path.name)
    entry = Entry(key=path.name, path=path, kind="film", parsed=parsed)

    season_from_dir: Dict[Path, int] = {}
    for root, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        root_path = Path(root)

        # Remember which season folder we are inside, so episodes in a
        # "Season 03" directory are attributed even when the filenames don't
        # carry SxxExx.
        for dirname in dirnames:
            number = parse.parse_season_folder(dirname)
            if number is not None:
                season_from_dir[root_path / dirname] = number
            elif dirname.lower() in ("extras", "specials", "featurettes"):
                entry.has_extras = True

        for filename in filenames:
            if filename.startswith("."):
                continue
            file_path = root_path / filename
            suffix = file_path.suffix.lower()

            if _is_incomplete(filename):
                entry.incomplete = True
                continue
            if suffix in SUBTITLE_EXTS:
                entry.external_subs = True
                continue
            if suffix not in VIDEO_EXTS:
                continue

            try:
                size = file_path.stat().st_size
            except OSError:
                continue

            season = None
            episode = None
            found = parse.parse_episode(filename)
            if found:
                season, episode = found
            else:
                # Fall back to the enclosing season folder.
                for parent in file_path.parents:
                    if parent in season_from_dir:
                        season = season_from_dir[parent]
                        break

            is_extra = any(part.lower() in EXTRA_DIRS
                           for part in file_path.relative_to(path).parts[:-1])
            entry.videos.append(
                VideoFile(file_path, size, season, episode, is_extra))
            entry.total_size += size

    # A folder is a series if the disk says so, or failing that if the name did.
    episodic = [v for v in entry.videos if v.season is not None]
    if episodic or season_from_dir:
        entry.kind = "series"
    elif parsed.series_hint and len(entry.videos) > 1:
        entry.kind = "series"

    if entry.kind == "series":
        for video in entry.videos:
            if video.season is None or video.extra:
                continue
            entry.seasons[video.season] = entry.seasons.get(video.season, 0) + 1

    if not entry.videos:
        entry.issues.append("no video files found")
    if entry.incomplete:
        entry.issues.append("download looks incomplete")

    return entry


def scan_library(root: Path) -> List[Entry]:
    """Every top-level folder in the library, sorted by name."""
    if not root.is_dir():
        raise FileNotFoundError("Library path does not exist: {}".format(root))

    entries = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if child.name.startswith(".") or child.name == STATE_DIR_NAME:
            continue
        if not child.is_dir():
            continue
        entries.append(scan_folder(child))
    return entries


def folder_signature(path: Path) -> str:
    """Cheap fingerprint of a folder's contents.

    Used to tell a finished download from one still being written: an unchanged
    signature across two runs means the folder has settled.
    """
    total = 0
    count = 0
    for root, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            if filename.startswith("."):
                continue
            try:
                total += (Path(root) / filename).stat().st_size
            except OSError:
                continue
            count += 1
    return "{}:{}".format(count, total)
