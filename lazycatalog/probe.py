"""ffprobe: what the files actually are.

TMDB knows what a film is; only the file knows whether this copy is 1080p,
which audio track it carries, and whether the subtitles you need are already
inside it. That last one is the question a library list usually can't answer.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

TIMEOUT = 60

# Bumped whenever the interpretation of an ffprobe payload changes, so stored
# readings are refreshed instead of staying wrong forever.
VERSION = 3

CHANNEL_NAMES = {1: "1.0", 2: "2.0", 3: "2.1", 4: "4.0", 5: "5.0",
                 6: "5.1", 7: "6.1", 8: "7.1"}

# Transfer characteristics that mean HDR rather than plain SDR.
HDR_TRANSFERS = {"smpte2084": "HDR10", "arib-std-b67": "HLG"}


def available() -> bool:
    return shutil.which("ffprobe") is not None


def _run_ffprobe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        return json.loads(completed.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None


# Each tier as (label, minimum width, minimum height). A file qualifies on
# either dimension, so the list is walked top down and the first hit wins.
#
# Both dimensions are needed because either one alone gets it wrong: a 2.35:1
# film at 1920x800 is 1080p despite the short height, and a 1.66:1 film at
# 1792x1080 is 1080p despite the narrow width. Thresholds sit under the nominal
# values because encoders round (1916 and 1918 both turn up in the wild).
RESOLUTION_TIERS = (
    ("2160p", 3400, 1700),
    ("1080p", 1800, 950),
    ("720p", 1200, 620),
    ("576p", 900, 530),
    ("480p", 640, 380),
)


def _resolution(height: Optional[int], width: Optional[int]) -> Optional[str]:
    width = width or 0
    height = height or 0
    if not width and not height:
        return None
    for label, min_width, min_height in RESOLUTION_TIERS:
        if width >= min_width or height >= min_height:
            return label
    return "{}p".format(height) if height else None


def summarise(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce an ffprobe payload to the handful of fields worth showing."""
    streams = payload.get("streams") or []
    out: Dict[str, Any] = {}

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video:
        out["video"] = video.get("codec_name")
        resolution = _resolution(video.get("height"), video.get("width"))
        if resolution:
            out["resolution"] = resolution
        transfer = (video.get("color_transfer") or "").lower()
        if transfer in HDR_TRANSFERS:
            out["hdr"] = HDR_TRANSFERS[transfer]

    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if audios:
        # The default track is what will actually play.
        primary = next(
            (a for a in audios if (a.get("disposition") or {}).get("default")), audios[0])
        out["audio"] = (primary.get("codec_name") or "").upper() or None
        channels = primary.get("channels")
        if channels:
            out["channels"] = CHANNEL_NAMES.get(int(channels), "{}ch".format(channels))
        if len(audios) > 1:
            out["audio_tracks"] = len(audios)

    subs: List[str] = []
    for stream in streams:
        if stream.get("codec_type") != "subtitle":
            continue
        language = ((stream.get("tags") or {}).get("language") or "und").lower()
        if language not in subs:
            subs.append(language)
    out["subs"] = subs

    duration = (payload.get("format") or {}).get("duration")
    try:
        seconds = float(duration)
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds > 0:
        out["runtime_sec"] = int(seconds)

    return {k: v for k, v in out.items() if v not in (None, "")}


def describe(entry, runner: Optional[Callable[[Path], Optional[Dict[str, Any]]]] = None
             ) -> Dict[str, Any]:
    """Tech specs for one library entry, read from its largest video file.

    The biggest file is the best representative: for a film it is the film, and
    for a series it avoids describing the library by a 90-second recap clip.
    """
    runner = runner or _run_ffprobe
    if not entry.videos:
        return {}
    if runner is _run_ffprobe and not available():
        return {}

    largest = max(entry.videos, key=lambda v: v.size)
    payload = runner(largest.path)
    if not payload:
        return {}

    tech = summarise(payload)
    if entry.kind == "series":
        # A series' "runtime" is one episode's; the total is derived from the
        # episode count instead, so don't imply the whole show is 42 minutes.
        tech.pop("runtime_sec", None)
    return tech
