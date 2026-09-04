"""Suggest films you don't own, based on the ones you do.

The division of labour is the same as everywhere else in this project, and it
matters more here than anywhere: the model chooses the titles, because taste
adjacency is exactly what it is good at, and TMDB then confirms each one is a
real film and supplies every fact printed about it. A title TMDB can't find is
treated as invented and dropped.

TMDB's own recommendation endpoints were tried first and are not usable for
this: asked what resembles The Lobster it offers The Boy in the Striped
Pyjamas, and asked about Her it offers Forrest Gump. Good for facts, useless
for taste.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import llm, tmdb

SYSTEM = """You recommend films someone would like, based on a library they own.

Rules:
- Never suggest anything already in their library.
- Suggest real, released films only. Give the exact title and release year.
- Match the specific taste the library shows, not what is broadly popular.
  A library of arthouse films should not be answered with blockbusters.
- Each "why" is one sentence under 25 words, and must refer to something
  concrete in their library by name.

Reply with only JSON:
{"suggestions":[{"title":"...","year":1999,"why":"..."}]}"""


def taste_profile(records: Sequence[Dict[str, Any]], limit: int = 60) -> str:
    """The library as the model sees it.

    Watched titles come first and are marked: owning something says you were
    curious, finishing it says you liked it, and that is the stronger signal.
    """
    def rank(record: Dict[str, Any]) -> tuple:
        return (0 if record.get("watched") else 1,
                -(float(record.get("rating") or 0)))

    lines = []
    for record in sorted(records, key=rank)[:limit]:
        bits = [record.get("title") or record["key"]]
        if record.get("year"):
            bits.append("({})".format(record["year"]))
        if record.get("genres"):
            bits.append("· " + ", ".join(record["genres"][:3]))
        if record.get("moods"):
            bits.append("· " + ", ".join(record["moods"]))
        if record.get("watched"):
            bits.append("· WATCHED")
        lines.append("- " + " ".join(bits))
    return "\n".join(lines)


def build_prompt(records: Sequence[Dict[str, Any]], request: str, count: int,
                 avoid: Sequence[str] = ()) -> str:
    parts = ["My library:", taste_profile(records), ""]
    if avoid:
        # Without this the model offers the same handful every run.
        parts += ["Already suggested before, do not repeat these:",
                  "\n".join("- " + title for title in avoid), ""]
    parts.append("Request: {}".format(request or "anything I'd probably like"))
    parts.append("")
    parts.append("Suggest {} films I do not already own. JSON:".format(count))
    return "\n".join(parts)


def _candidate_list(raw: str) -> List[Any]:
    """Pull the list of suggestions out of whatever shape the model replied in.

    Models differ here and the difference is not worth a prompt fight:
    mistral-small returns {"suggestions": [...]}, gemma3 returns a bare [...].
    Both are accepted, fenced or not.
    """
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", raw.strip(),
                  flags=re.MULTILINE).strip()

    for pattern in (r"\[.*\]", r"\{.*\}"):
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            continue
        try:
            payload = json.loads(match.group())
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("suggestions", "films", "movies", "results", "recommendations"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
            # A single suggestion returned bare rather than in a list.
            if payload.get("title"):
                return [payload]
    return []


def parse(raw: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in _candidate_list(raw):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        if not title:
            continue
        try:
            year: Optional[int] = int(item.get("year"))
        except (TypeError, ValueError):
            year = None
        if year is not None and not (1880 <= year <= date.today().year + 2):
            year = None
        out.append({"title": title, "year": year,
                    "why": str(item.get("why") or item.get("reason") or "").strip()})
    return out


def verify(
    client: tmdb.Client,
    candidates: Sequence[Dict[str, Any]],
    owned_ids: set,
    owned_titles: set,
    known_ids: set,
    model: str = "",
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]]]:
    """Confirm each suggestion exists and isn't already yours.

    Returns (accepted, [(title, reason it was dropped)]).
    """
    accepted: List[Dict[str, Any]] = []
    dropped: List[Tuple[str, str]] = []
    seen_ids = set()

    for candidate in candidates:
        label = candidate["title"]
        if candidate.get("year"):
            label += " ({})".format(candidate["year"])

        try:
            found = client.lookup(candidate["title"], candidate.get("year"), "film")
        except tmdb.TMDBError as exc:
            dropped.append((label, "TMDB lookup failed: {}".format(exc)))
            continue

        if not found or not found.get("tmdb_id"):
            dropped.append((label, "no such film on TMDB"))
            continue

        tmdb_id = str(found["tmdb_id"])
        if tmdb_id in owned_ids:
            dropped.append((label, "already in your library"))
            continue
        if tmdb._normalise_title(found_title(found, candidate)) in owned_titles:
            dropped.append((label, "already in your library"))
            continue
        if tmdb_id in known_ids or tmdb_id in seen_ids:
            dropped.append((label, "already on the watchlist"))
            continue
        seen_ids.add(tmdb_id)

        accepted.append({
            "tmdb_id": int(found["tmdb_id"]),
            "title": found_title(found, candidate),
            "year": found.get("year") or candidate.get("year"),
            "genres": found.get("genres") or [],
            "runtime": found.get("runtime"),
            "rating": found.get("rating"),
            "overview": found.get("overview") or "",
            "director": found.get("director"),
            "cast": found.get("cast") or [],
            "tmdb_url": found.get("tmdb_url"),
            "why": candidate.get("why") or "",
            "model": model,
            "added": date.today().isoformat(),
            "watched": False,
        })

    return accepted, dropped


def found_title(found: Dict[str, Any], candidate: Dict[str, Any]) -> str:
    return found.get("title") or candidate["title"]


def propose(
    records: Sequence[Dict[str, Any]],
    request: str,
    client: tmdb.Client,
    host: str,
    model: str,
    count: int = 5,
    owned_ids: Optional[set] = None,
    known_ids: Optional[set] = None,
    avoid: Sequence[str] = (),
    opener=None,
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]], Optional[str]]:
    """Returns (accepted, dropped, error)."""
    if not records:
        return [], [], "Nothing in the catalogue yet. Run `lazy-catalog update` first."

    # Ask for extra: verification always removes some, and coming back with two
    # films when five were asked for reads as a failure.
    asked = min(count * 2, count + 6)
    prompt = build_prompt(records, request, asked, avoid)
    try:
        raw = llm.generate(host, model, prompt, system=SYSTEM, temperature=0.8,
                           opener=opener)
    except llm.LLMError as exc:
        return [], [], str(exc)

    candidates = parse(raw)
    if not candidates:
        return [], [], "The model didn't return a usable answer. Try rephrasing."

    owned_titles = {
        tmdb._normalise_title(r.get("title") or "") for r in records}
    accepted, dropped = verify(
        client, candidates, owned_ids or set(), owned_titles,
        known_ids or set(), model)
    return accepted[:count], dropped, None
