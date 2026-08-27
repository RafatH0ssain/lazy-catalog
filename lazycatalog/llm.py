"""Ollama access, deliberately narrow.

The model is asked exactly two kinds of question: what a mangled folder name
probably says, and how a film feels. It is never asked for a runtime, a year,
a rating or a plot, because those are facts and TMDB has them. Keeping that
line means a hallucination can only ever cost us a bad mood tag.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

TIMEOUT = 180

MOOD_SYSTEM = (
    "You tag films and TV by how they feel to watch. "
    "Reply with 2 to 4 short lowercase tags separated by commas. "
    "No explanations, no punctuation beyond the commas, no numbering. "
    "Good tags: slow burn, bleak, warm, tense, funny, rewatchable, "
    "needs full attention, easy watch, unsettling, melancholy, stylish, "
    "talky, violent, hopeful, weird."
)

TITLE_SYSTEM = (
    "You extract the real title and release year from a messy download folder "
    "name. Reply with only JSON: {\"title\": string, \"year\": number or null}. "
    "Strip resolution, codec, source and release-group tags."
)


class LLMError(Exception):
    pass


def _post(host: str, path: str, payload: Dict[str, Any], opener=None) -> Dict[str, Any]:
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(
        host.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with opener(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise LLMError("Could not reach Ollama at {}: {}".format(host, exc.reason)) from exc


def list_models(host: str, opener=None) -> List[str]:
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(host.rstrip("/") + "/api/tags")
    try:
        with opener(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return []
    return [m["name"] for m in payload.get("models", []) if m.get("name")]


def generate(
    host: str, model: str, prompt: str, system: Optional[str] = None,
    temperature: float = 0.4, opener=None,
) -> str:
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if system:
        payload["system"] = system
    result = _post(host, "/api/generate", payload, opener=opener)
    if "error" in result:
        raise LLMError(str(result["error"]))
    return (result.get("response") or "").strip()


# -- the two allowed questions ----------------------------------------

def mood_tags(
    host: str, model: str, title: str, year: Optional[int], genres: List[str],
    overview: str, opener=None,
) -> List[str]:
    """Subjective tags. Wrong answers here are opinions, not errors."""
    prompt = "Title: {}{}\nGenres: {}\nSynopsis: {}\n\nTags:".format(
        title,
        " ({})".format(year) if year else "",
        ", ".join(genres) or "unknown",
        overview or "unknown",
    )
    try:
        raw = generate(host, model, prompt, system=MOOD_SYSTEM, temperature=0.5,
                       opener=opener)
    except LLMError:
        return []
    return _clean_tags(raw)


def _clean_tags(raw: str) -> List[str]:
    # Models like to editorialise; keep only the comma-separated tail.
    raw = raw.strip().splitlines()[-1] if raw.strip() else ""
    raw = re.sub(r"^(tags?|answer)\s*[:\-]\s*", "", raw, flags=re.IGNORECASE)
    tags: List[str] = []
    for piece in raw.split(","):
        tag = re.sub(r"[^a-z0-9 \-]", "", piece.strip().lower()).strip()
        if 2 <= len(tag) <= 24 and tag not in tags:
            tags.append(tag)
    return tags[:4]


def clean_name(
    host: str, model: str, folder_name: str, opener=None
) -> Optional[Tuple[str, Optional[int]]]:
    """Last resort for folder names the regexes couldn't read."""
    try:
        raw = generate(host, model, "Folder name: {}".format(folder_name),
                       system=TITLE_SYSTEM, temperature=0.0, opener=opener)
    except LLMError:
        return None

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    title = str(payload.get("title") or "").strip()
    if not title:
        return None
    year = payload.get("year")
    try:
        year_value = int(year) if year else None
    except (TypeError, ValueError):
        year_value = None
    if year_value is not None and not (1880 <= year_value <= 2100):
        year_value = None
    return title, year_value
