"""A single self-contained HTML page for browsing the library.

No server, no build step, no CDN: the data is embedded as JSON and the posters
are local files, so the page works with the network off and keeps working if
this project is never updated again.

Watched state is deliberately read-only here. It is set by ticking a box in
CONTENTS.md, which means there is exactly one place it can be changed and the
two views can never disagree.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from . import omdb
from .render_md import format_subs, human_duration, human_size

TEMPLATE = Path(__file__).parent / "templates" / "page.html"


def _runtime_label(record: Dict[str, Any]) -> str:
    """Prefer the runtime the file actually has over the one TMDB lists."""
    tech = record.get("tech") or {}
    seconds = tech.get("runtime_sec")
    if seconds:
        return human_duration(int(round(seconds / 60.0)))
    return human_duration(record.get("runtime"))


def _tech_line(record: Dict[str, Any]) -> str:
    tech = record.get("tech") or {}
    bits = [tech.get("resolution"), tech.get("video"), tech.get("audio"),
            tech.get("channels"), tech.get("hdr")]
    subs = format_subs(tech.get("subs") or [])
    if subs:
        bits.append("subs " + subs)
    elif record.get("external_subs"):
        bits.append("subs external")
    if record.get("total_size"):
        bits.append(human_size(record["total_size"]))
    return " · ".join(b for b in bits if b)


def _season_line(record: Dict[str, Any]) -> str:
    seasons = record.get("seasons") or {}
    numbers = sorted(int(n) for n in seasons if int(n) > 0)
    if not numbers:
        return ""
    span = ("Season {}".format(numbers[0]) if len(numbers) == 1
            else "Seasons {}\u2013{}".format(numbers[0], numbers[-1]))
    line = "{} · {} episodes".format(span, record.get("episode_count") or 0)
    if record.get("specials"):
        line += " · {} specials".format(record["specials"])
    return line


def _payload(record: Dict[str, Any]) -> Dict[str, Any]:
    title = record.get("title") or record["key"]
    haystack = " ".join([
        title,
        str(record.get("year") or ""),
        record.get("director") or "",
        " ".join(record.get("cast") or []),
        " ".join(record.get("genres") or []),
        " ".join(record.get("moods") or []),
        record.get("overview") or "",
    ]).lower()

    return {
        "key": record["key"],
        "title": title,
        "sortTitle": title.lower(),
        "year": record.get("year"),
        "kind": record.get("kind", "film"),
        "genres": record.get("genres") or [],
        "moods": record.get("moods") or [],
        "rating": record.get("rating"),
        "scores": omdb.summary(record.get("ratings") or {}),
        "runtime": record.get("runtime"),
        "runtimeLabel": _runtime_label(record),
        "size": record.get("total_size") or 0,
        "added": record.get("first_seen") or "",
        "watched": bool(record.get("watched")),
        "verified": bool(record.get("enriched")),
        "overview": record.get("overview") or "",
        "director": record.get("director") or "",
        "cast": record.get("cast") or [],
        "poster": record.get("poster"),
        "video": record.get("video"),
        "tmdb": record.get("tmdb_url"),
        "tech": _tech_line(record),
        "seasonLine": _season_line(record),
        "haystack": haystack,
    }


def _embed(payload: Any) -> str:
    """JSON safe to drop inside an inline <script>.

    Folder names are arbitrary text, and one containing "</script>" would
    otherwise close the tag early and break the page.
    """
    return (json.dumps(payload, ensure_ascii=False)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def render(records: Iterable[Dict[str, Any]], title: str = "The Home Cinema",
           now: Optional[datetime] = None, token: str = "") -> str:
    """Render the page.

    `token` is supplied only when the page is served by the local helper, and
    it is what enables playing a title in VLC. Opened straight off disk there
    is no token and no helper, so the play affordance is simply absent rather
    than present and broken.
    """
    records = list(records)
    payload = [_payload(r) for r in records]
    now = now or datetime.now()

    films = sum(1 for r in records if r.get("kind") == "film")
    series = len(records) - films
    watched = sum(1 for r in records if r.get("watched"))
    size = human_size(sum(r.get("total_size") or 0 for r in records))

    minutes = sum(r.get("runtime") or 0 for r in records if r.get("kind") == "film")
    ledger = [
        "<b>{}</b> films".format(films),
        "<b>{}</b> series".format(series),
        "<b>{}</b> on disk".format(size),
    ]
    if minutes:
        ledger.append("<b>{}h</b> of features".format(minutes // 60))
    if watched:
        ledger.append("<b>{}</b> seen".format(watched))

    footer = ("Catalogued by lazy-catalog on {}. "
              "Mark something watched by ticking its box in CONTENTS.md.").format(
        now.strftime("%d %B %Y, %H:%M"))
    if token:
        footer += " Click a poster in the detail view to play it in VLC."

    return (TEMPLATE.read_text(encoding="utf-8")
            .replace("__DATA__", _embed(payload))
            .replace("__TITLE__", title)
            .replace("__STATS__", "".join("<span>{}</span>".format(x) for x in ledger))
            .replace("__FOOTER__", footer)
            .replace("__TOKEN__", token))
