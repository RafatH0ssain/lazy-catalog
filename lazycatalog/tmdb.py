"""TMDB lookups — the source of every fact in the catalogue.

Facts come from here rather than from a language model on purpose: a model
asked for a runtime or a rating will produce a plausible wrong number, and a
catalogue that is confidently wrong is worse than one that is incomplete.

Accepts either a v3 API key or a v4 read-access token; which one you pasted
is detected rather than asked about.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

API_ROOT = "https://api.themoviedb.org/3"
IMAGE_ROOT = "https://image.tmdb.org/t/p/w500"
SITE_ROOT = "https://www.themoviedb.org"
TIMEOUT = 20


class TMDBError(Exception):
    pass


class AuthError(TMDBError):
    pass


def _is_bearer_token(key: str) -> bool:
    """v4 tokens are JWTs; v3 keys are 32 hex characters."""
    return key.startswith("ey") and key.count(".") == 2


class Client:
    def __init__(self, api_key: str, language: str = "en-US", opener=None):
        if not api_key:
            raise AuthError("No TMDB key configured. Run `lazy-catalog init`.")
        self.api_key = api_key.strip()
        self.language = language
        self._opener = opener or urllib.request.urlopen

    def _get(self, path: str, **params: Any) -> Dict[str, Any]:
        params = {k: v for k, v in params.items() if v not in (None, "")}
        params.setdefault("language", self.language)

        headers = {"Accept": "application/json", "User-Agent": "lazy-catalog"}
        if _is_bearer_token(self.api_key):
            headers["Authorization"] = "Bearer " + self.api_key
        else:
            params["api_key"] = self.api_key

        url = "{}{}?{}".format(API_ROOT, path, urllib.parse.urlencode(params))
        request = urllib.request.Request(url, headers=headers)

        for attempt in range(3):
            try:
                with self._opener(request, timeout=TIMEOUT) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise AuthError(
                        "TMDB rejected the API key. Run `lazy-catalog init` to replace it."
                    ) from exc
                if exc.code == 429 and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                if exc.code == 404:
                    raise TMDBError("Not found: {}".format(path)) from exc
                raise TMDBError("TMDB error {} for {}".format(exc.code, path)) from exc
            except urllib.error.URLError as exc:
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                raise TMDBError("Could not reach TMDB: {}".format(exc.reason)) from exc
        raise TMDBError("Could not reach TMDB")

    # -- public API ----------------------------------------------------

    def verify(self) -> bool:
        """True if the key works. Used by `lazy-catalog init`."""
        self._get("/configuration")
        return True

    def search(self, title: str, year: Optional[int], kind: str) -> Optional[Dict[str, Any]]:
        if kind == "series":
            payload = self._get("/search/tv", query=title, first_air_date_year=year)
        else:
            payload = self._get("/search/movie", query=title, year=year)
        results = payload.get("results") or []
        if not results and year:
            # The folder's year is often the release year of the rip, not the
            # film. Retry without it before giving up.
            return self.search(title, None, kind)
        return _best_match(results, title, year, kind)

    def details(self, tmdb_id: int, kind: str) -> Dict[str, Any]:
        path = "/tv/{}".format(tmdb_id) if kind == "series" else "/movie/{}".format(tmdb_id)
        return self._get(path, append_to_response="credits")

    def lookup(self, title: str, year: Optional[int], kind: str) -> Optional[Dict[str, Any]]:
        """Search then fetch details, normalised into cache fields."""
        match = self.search(title, year, kind)
        if not match:
            return None
        return normalise(self.details(match["id"], kind), kind)


def _normalise_title(text: str) -> str:
    text = text.lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _result_year(result: Dict[str, Any], kind: str) -> Optional[int]:
    field = "first_air_date" if kind == "series" else "release_date"
    value = (result.get(field) or "")[:4]
    return int(value) if value.isdigit() else None


def _best_match(
    results: List[Dict[str, Any]], title: str, year: Optional[int], kind: str
) -> Optional[Dict[str, Any]]:
    """Prefer an exact title match in the right year over a popular near-miss."""
    if not results:
        return None
    wanted = _normalise_title(title)

    def score(result: Dict[str, Any]) -> Tuple[int, int, float]:
        name = result.get("title") or result.get("name") or ""
        original = result.get("original_title") or result.get("original_name") or ""
        candidates = {_normalise_title(name), _normalise_title(original)}
        title_score = 2 if wanted in candidates else (
            1 if any(wanted in c or c in wanted for c in candidates if c) else 0)

        found_year = _result_year(result, kind)
        if year and found_year:
            # Releases straddle new year, so allow a year either side.
            year_score = 2 if found_year == year else (1 if abs(found_year - year) <= 1 else 0)
        else:
            year_score = 0
        return (title_score, year_score, float(result.get("popularity") or 0.0))

    return max(results, key=score)


def normalise(details: Dict[str, Any], kind: str) -> Dict[str, Any]:
    """TMDB's payload reduced to the fields the catalogue stores."""
    credits = details.get("credits") or {}
    crew = credits.get("crew") or []
    cast = credits.get("cast") or []

    if kind == "series":
        creators = [c.get("name") for c in (details.get("created_by") or []) if c.get("name")]
        director = ", ".join(creators) or None
        runtimes = details.get("episode_run_time") or []
        runtime = int(runtimes[0]) if runtimes else None
        year = _result_year(details, kind)
    else:
        director = next(
            (c.get("name") for c in crew if c.get("job") == "Director"), None)
        runtime = details.get("runtime") or None
        year = _result_year(details, kind)

    rating = details.get("vote_average")
    poster_path = details.get("poster_path")

    return {
        "tmdb_id": details.get("id"),
        "tmdb_url": "{}/{}/{}".format(
            SITE_ROOT, "tv" if kind == "series" else "movie", details.get("id")),
        "overview": (details.get("overview") or "").strip(),
        "genres": [g["name"] for g in (details.get("genres") or []) if g.get("name")],
        "runtime": int(runtime) if runtime else None,
        "rating": round(float(rating), 1) if rating else None,
        "votes": details.get("vote_count") or None,
        "director": director,
        "cast": [c.get("name") for c in cast[:5] if c.get("name")],
        "year": year,
        "poster_url": IMAGE_ROOT + poster_path if poster_path else None,
    }


def download_poster(url: str, destination, opener=None) -> bool:
    """Cache a poster locally so the web view works offline."""
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(url, headers={"User-Agent": "lazy-catalog"})
    try:
        with opener(request, timeout=TIMEOUT) as response:
            data = response.read()
    except (urllib.error.URLError, OSError):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return True
