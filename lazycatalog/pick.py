"""lazy-pick: ask the local model what to watch, and get a ranked answer.

The model chooses by number from a list it is handed, and every number is
checked against that list before anything is printed. It cannot invent a film
you don't own, which is the failure mode that would make the whole feature
useless.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import llm
from .render_md import human_duration

SYSTEM = """You recommend what to watch tonight from a specific personal library.

You are given a numbered list. You may only reference those numbers.
Rank your recommendations into tiers: "S" is the single best fit (at most two),
"A" is a strong fit, "B" is a reasonable fallback. Include 3 to 6 picks total.
Add "honorable" entries for titles worth naming that don't fit the tiers, and
"skipped" for notable titles you deliberately ruled out.

Every "why" is one sentence, specific to the request, no more than 20 words.
Never mention numbers or tiers inside a "why".

Reply with only JSON in exactly this shape:
{"picks":[{"n":1,"tier":"S","why":"..."}],
 "honorable":[{"n":2,"why":"..."}],
 "skipped":[{"n":3,"why":"..."}]}"""

TIER_ORDER = {"S": 0, "A": 1, "B": 2}


def catalog_lines(records: Sequence[Dict[str, Any]]) -> List[str]:
    """One compact line per title, cheap enough to send in full."""
    lines = []
    for index, record in enumerate(records, 1):
        bits = [record.get("title") or record["key"]]
        if record.get("year"):
            bits.append("({})".format(record["year"]))
        if record.get("kind") == "series":
            bits.append("[series, {} eps]".format(record.get("episode_count") or 0))
        elif record.get("runtime"):
            bits.append("[{} min]".format(record["runtime"]))
        if record.get("genres"):
            bits.append("· " + ", ".join(record["genres"][:3]))
        if record.get("moods"):
            bits.append("· " + ", ".join(record["moods"]))
        if record.get("rating"):
            bits.append("· {:.1f}/10".format(float(record["rating"])))
        if record.get("watched"):
            bits.append("· already watched")
        lines.append("{}. {}".format(index, " ".join(bits)))
    return lines


def build_prompt(records: Sequence[Dict[str, Any]], request: str) -> str:
    return "Library:\n{}\n\nRequest: {}\n\nJSON:".format(
        "\n".join(catalog_lines(records)), request)


def _parse(raw: str, count: int) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    def clean(items: Any, with_tier: bool) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen = set()
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                number = int(item.get("n"))
            except (TypeError, ValueError):
                continue
            # The whole point of the numbered list: anything out of range is a
            # title the model made up, so it is dropped rather than shown.
            if not (1 <= number <= count) or number in seen:
                continue
            seen.add(number)
            entry = {"n": number, "why": str(item.get("why") or "").strip()}
            if with_tier:
                tier = str(item.get("tier") or "B").strip().upper()[:1]
                entry["tier"] = tier if tier in TIER_ORDER else "B"
            out.append(entry)
        return out

    return {
        "picks": clean(payload.get("picks"), True),
        "honorable": clean(payload.get("honorable"), False),
        "skipped": clean(payload.get("skipped"), False),
    }


def choose(
    records: Sequence[Dict[str, Any]], request: str, host: str, model: str,
    opener=None,
) -> Tuple[Optional[Dict[str, List[Dict[str, Any]]]], Optional[str]]:
    """Returns (result, error)."""
    if not records:
        return None, "Nothing in the catalogue yet. Run `lazy-catalog update` first."
    try:
        raw = llm.generate(host, model, build_prompt(records, request),
                           system=SYSTEM, temperature=0.6, opener=opener)
    except llm.LLMError as exc:
        return None, str(exc)

    result = _parse(raw, len(records))
    if not result or not result["picks"]:
        return None, "The model didn't return a usable answer. Try rephrasing."
    result["picks"].sort(key=lambda p: TIER_ORDER.get(p["tier"], 3))
    return result, None


# -- presentation ------------------------------------------------------

BOLD = "\033[1m"
DIM = "\033[2m"
GOLD = "\033[38;5;179m"
RESET = "\033[0m"


def _label(record: Dict[str, Any]) -> str:
    title = record.get("title") or record["key"]
    if record.get("year"):
        title += " ({})".format(record["year"])
    if record.get("kind") == "series":
        extra = "{} eps".format(record.get("episode_count") or 0)
    else:
        extra = human_duration(record.get("runtime"))
    return "{} · {}".format(title, extra) if extra else title


def format_result(
    result: Dict[str, List[Dict[str, Any]]], records: Sequence[Dict[str, Any]],
    colour: bool = True,
) -> str:
    def paint(text: str, code: str) -> str:
        return "{}{}{}".format(code, text, RESET) if colour else text

    lines: List[str] = [""]
    for pick in result["picks"]:
        record = records[pick["n"] - 1]
        lines.append("{}  {}".format(
            paint(pick["tier"], GOLD + BOLD), paint(_label(record), BOLD)))
        if pick["why"]:
            lines.append("   {}".format(paint(pick["why"], DIM)))
        lines.append("")

    if result["honorable"]:
        lines.append(paint("Honorable mentions", BOLD))
        for item in result["honorable"]:
            record = records[item["n"] - 1]
            why = " — {}".format(item["why"]) if item["why"] else ""
            lines.append("   {}{}".format(_label(record), paint(why, DIM)))
        lines.append("")

    if result["skipped"]:
        names = ", ".join(
            (records[i["n"] - 1].get("title") or records[i["n"] - 1]["key"])
            for i in result["skipped"])
        lines.append(paint("Ruled out: {}".format(names), DIM))
        lines.append("")

    return "\n".join(lines)
