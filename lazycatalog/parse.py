"""Turn a scene-release folder name into a title and year.

Deliberately deterministic: no model is consulted here. The LLM is only asked
about names this module reports as low confidence, so a bad model answer can
never overwrite a name the regexes already understood.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple

# A year, standalone. Bounded so "1080p", "x265" and "DDP5" can't match.
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

# Nothing can have been released next year but a title can be named after any
# year at all, so a number beyond this is part of the name: Blade Runner 2049
# came out in 2017.
def _latest_plausible_year() -> int:
    return date.today().year + 1

# Season/episode notation. Two digits after S keeps "DTS" and "SPARKS" out.
SXXEYY_RE = re.compile(r"\bS(\d{1,2})E(\d{1,3})\b", re.IGNORECASE)
NxNN_RE = re.compile(r"\b(\d{1,2})x(\d{2})\b")
SEASON_WORD_RE = re.compile(r"\bseasons?\s*(\d{1,2})(?:\s*-\s*(\d{1,2}))?\b", re.IGNORECASE)
SXX_RE = re.compile(r"\bS(\d{2})\b(?:\s*-\s*S(\d{2})\b)?", re.IGNORECASE)
SEASON_FOLDER_RE = re.compile(r"^(?:season|series|s)[\s._-]*(\d{1,3})$", re.IGNORECASE)

# Tokens that mark the end of a title. Everything from the first one onwards is
# release metadata, not part of the name.
JUNK_TOKENS = {
    # resolution / scan
    "480p", "540p", "576p", "720p", "1080p", "1080i", "2160p", "4k", "uhd", "hd",
    # source
    "bluray", "blu-ray", "bdrip", "bdremux", "brrip", "dvdrip", "dvd", "hdtv",
    "webrip", "web-dl", "webdl", "web", "hdrip", "remux", "cam", "ts",
    # platform
    "amzn", "atvp", "nf", "hulu", "dsnp", "hmax", "max", "pcok", "stan", "itunes",
    # video codec
    "x264", "x265", "h264", "h265", "hevc", "avc", "xvid", "divx", "av1",
    "10bit", "8bit", "12bit", "hdr", "hdr10", "dv", "sdr",
    # audio
    "aac", "ac3", "eac3", "dd", "ddp", "dts", "dts-hd", "truehd", "atmos",
    "mp3", "flac", "opus", "2.0", "5.1", "7.1", "dual", "dubbed",
    # edition / status
    "remastered", "extended", "unrated", "uncut", "proper", "repack", "internal",
    "limited", "imax", "criterion", "complete", "multi", "subbed",
}

# Groups and tags that trail the name, matched as substrings.
TRAILING_TAGS = ("yts", "yify", "rarbg", "tgx", "galaxyrg", "ettv", "eztv")


@dataclass
class ParsedName:
    """What a folder name yielded. `confidence` gates the LLM fallback."""

    raw: str
    title: str
    year: Optional[int] = None
    series_hint: bool = False
    season_hint: List[int] = field(default_factory=list)
    confidence: str = "low"  # high | medium | low


def _normalise(name: str) -> str:
    """Dot-separated releases become spaced; bracket tags are dropped."""
    text = name.replace("_", " ")
    # Only de-dot names that actually use dots as separators, so "YTS.AM" or
    # "5.1" inside an otherwise spaced name survives untouched.
    if text.count(".") > text.count(" "):
        text = text.replace(".", " ")
    return re.sub(r"\s+", " ", text).strip()


def _is_junk(token: str) -> bool:
    low = token.lower().strip("[]()<>{}-–—,")
    if not low:
        return False
    if low in JUNK_TOKENS:
        return True
    if any(tag in low for tag in TRAILING_TAGS):
        return True
    # "1600MB", "700mb"
    if re.fullmatch(r"\d+(?:mb|gb)", low):
        return True
    # "DD5", "DDP5", "AAC5", "AC3" style audio blobs with the channel glued on
    if re.fullmatch(r"(?:dd|ddp|aac|ac|dts|eac)\d(?:\.\d)?", low):
        return True
    return False


def _clean_title(text: str) -> str:
    text = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", text)  # drop whole bracket groups
    text = text.strip(" .-_[](){}<>+&")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _series_markers(name: str) -> Tuple[bool, List[int]]:
    seasons: List[int] = []
    hit = False

    match = SEASON_WORD_RE.search(name)
    if match:
        hit = True
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        seasons.extend(range(min(start, end), max(start, end) + 1))

    match = SXX_RE.search(name)
    if match:
        hit = True
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        seasons.extend(range(min(start, end), max(start, end) + 1))

    if SXXEYY_RE.search(name) or NxNN_RE.search(name):
        hit = True

    return hit, sorted(set(seasons))


def _series_cut(text: str) -> Optional[int]:
    """Where a season or episode marker starts, if one does.

    The title scan below works token by token, which cannot see a marker
    spelled across two of them: "Game of Thrones Season 1" walks straight past
    "Season" because the number lives in the next token. Searching the whole
    string first catches every spelling — "Season 1", "S04", "S01E01", "1x01".
    """
    starts = [match.start() for match in (
        SEASON_WORD_RE.search(text), SXX_RE.search(text),
        SXXEYY_RE.search(text), NxNN_RE.search(text)) if match]
    starts = [start for start in starts if start > 0]
    return min(starts) if starts else None


def parse_folder(name: str) -> ParsedName:
    """Best-effort (title, year) for one library folder."""
    text = _normalise(name)
    series_hint, season_hint = _series_markers(text)

    # Which of the numbers in this name is the release year?
    #
    # Not one at position zero: "2012 (2009)" and "1917.2019" name films whose
    # title is a year. Not one that hasn't happened yet: "Blade Runner 2049" is
    # a title, and the 2017 beside it is the release. And a bracketed year wins
    # outright, because "(2017)" is how a release year is written by hand.
    year: Optional[int] = None
    title_part: Optional[str] = None
    latest = _latest_plausible_year()

    candidates = []
    for match in YEAR_RE.finditer(text):
        if match.start() == 0:
            continue
        title = _clean_title(text[: match.start()])
        if not title:
            continue
        bracketed = (text[match.start() - 1] in "([{"
                     and match.end() < len(text) and text[match.end()] in ")]}")
        candidates.append((bracketed, int(match.group()), title))

    for want_bracketed in (True, False):
        for bracketed, value, title in candidates:
            if bracketed is not want_bracketed or value > latest:
                continue
            year, title_part = value, title
            break
        if title_part:
            break

    if title_part:
        return ParsedName(
            raw=name,
            title=title_part,
            year=year,
            series_hint=series_hint,
            season_hint=season_hint,
            confidence="high",
        )

    # No usable year: cut at a season marker if there is one, then keep tokens
    # until the first release-metadata token.
    cut = _series_cut(text)
    if cut is not None:
        text = text[:cut]
    tokens = text.split(" ")
    kept: List[str] = []
    stopped = False
    for token in tokens:
        if _is_junk(token) or SXX_RE.fullmatch(token) or SEASON_WORD_RE.fullmatch(token):
            stopped = True
            break
        kept.append(token)

    title = _clean_title(" ".join(kept))
    if title and (stopped or cut is not None):
        confidence = "medium"
    else:
        confidence = "low"
        title = title or _clean_title(text) or name

    return ParsedName(
        raw=name,
        title=title,
        year=None,
        series_hint=series_hint,
        season_hint=season_hint,
        confidence=confidence,
    )


def parse_episode(filename: str) -> Optional[Tuple[int, int]]:
    """(season, episode) from an episode filename, or None."""
    match = SXXEYY_RE.search(filename)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = NxNN_RE.search(filename)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def parse_season_folder(name: str) -> Optional[int]:
    """Season number from a folder like 'Season 01', or None for 'Extras'."""
    match = SEASON_FOLDER_RE.match(name.strip())
    return int(match.group(1)) if match else None
