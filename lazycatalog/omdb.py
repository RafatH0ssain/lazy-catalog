"""Rotten Tomatoes, Metacritic and IMDb scores, via OMDb.

Rotten Tomatoes publishes no API and TMDB does not carry its scores, so OMDb
is the route: give it an IMDb id and it returns all three in one call. TMDB
already supplies the IMDb id, so this needs no matching logic of its own and
cannot attach the wrong film's scores.

The key is optional. Without one the catalogue simply has no critic scores,
which is why every failure here returns nothing instead of raising.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

API_ROOT = "https://www.omdbapi.com/"
TIMEOUT = 15


class OMDbError(Exception):
    pass


class AuthError(OMDbError):
    pass


class Client:
    def __init__(self, api_key: str, opener=None):
        if not api_key:
            raise AuthError("No OMDb key configured. Run `lazy-catalog init`.")
        self.api_key = api_key.strip()
        self._opener = opener or urllib.request.urlopen

    def _get(self, **params: Any) -> Dict[str, Any]:
        params["apikey"] = self.api_key
        url = API_ROOT + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"User-Agent": "lazy-catalog"})
        with self._opener(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))

    def verify(self) -> bool:
        self._check(self._get(i="tt0084787"))
        return True

    @staticmethod
    def _check(payload: Dict[str, Any]) -> Dict[str, Any]:
        if str(payload.get("Response")).lower() == "false":
            error = str(payload.get("Error") or "")
            if "api key" in error.lower():
                raise AuthError(
                    "OMDb rejected the API key. Run `lazy-catalog init` to replace it.")
            return {}
        return payload

    def ratings(self, imdb_id: str) -> Dict[str, Any]:
        """Critic scores for one title. Empty when unavailable."""
        if not imdb_id:
            return {}
        try:
            payload = self._check(self._get(i=imdb_id))
        except AuthError:
            raise
        except (urllib.error.URLError, OSError, ValueError):
            # Scores are a nice-to-have; never fail a catalogue run over them.
            return {}
        return parse(payload)


def _number(text: Any) -> Optional[float]:
    match = re.search(r"\d+(?:\.\d+)?", str(text or ""))
    return float(match.group()) if match else None


def parse(payload: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for entry in payload.get("Ratings") or []:
        source = str(entry.get("Source") or "").lower()
        value = _number(entry.get("Value"))
        if value is None:
            continue
        if "rotten" in source:
            out["rotten_tomatoes"] = int(value)
        elif "metacritic" in source:
            out["metacritic"] = int(value)
        elif "internet movie" in source:
            out["imdb"] = round(value, 1)

    # The Ratings list is the richer source, but these stand in when it is thin.
    if "imdb" not in out:
        value = _number(payload.get("imdbRating"))
        if value is not None:
            out["imdb"] = round(value, 1)
    if "metacritic" not in out:
        value = _number(payload.get("Metascore"))
        if value is not None:
            out["metacritic"] = int(value)
    return out


def summary(ratings: Dict[str, Any]) -> str:
    """The scores as one short line."""
    bits = []
    if ratings.get("rotten_tomatoes") is not None:
        bits.append("RT {}%".format(ratings["rotten_tomatoes"]))
    if ratings.get("metacritic") is not None:
        bits.append("MC {}".format(ratings["metacritic"]))
    if ratings.get("imdb") is not None:
        bits.append("IMDb {}".format(ratings["imdb"]))
    return " · ".join(bits)
