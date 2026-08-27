"""Command line entry point."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import catalog, config, llm, tmdb
from .lock import AlreadyRunning, held

LOCK_NAME = "run.lock"


def _say(message: str = "") -> None:
    print(message, flush=True)


def _ask(prompt: str, default: str = "") -> str:
    suffix = " [{}]".format(default) if default else ""
    try:
        answer = input("{}{}: ".format(prompt, suffix)).strip()
    except EOFError:
        return default
    return answer or default


# -- init --------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    """Interactive setup. The API key is never echoed or passed as an argument."""
    existing: Dict[str, Any] = {}
    if config.exists():
        try:
            existing = config.load()
            _say("Updating existing config at {}".format(config.config_path()))
        except config.ConfigError:
            _say("Existing config is unreadable; starting fresh.")
    _say()

    library = _ask("Library folder", str(existing.get("library_path", "~/TV")))
    if not Path(library).expanduser().is_dir():
        _say("  ! {} doesn't exist yet — that's fine, but nothing will be "
             "catalogued until it does.".format(library))

    _say()
    _say("TMDB API key (themoviedb.org → Settings → API).")
    _say("Typing is hidden, and the key is written to a file only you can read.")
    current = existing.get("tmdb_api_key") or ""
    prompt = "TMDB key [keep existing]: " if current else "TMDB key: "
    try:
        key = getpass.getpass(prompt).strip() or current
    except (EOFError, KeyboardInterrupt):
        _say("\nCancelled.")
        return 1
    if not key:
        _say("A key is required. Get one free at "
             "https://www.themoviedb.org/settings/api")
        return 1

    _say("Checking the key with TMDB...")
    try:
        tmdb.Client(key).verify()
    except tmdb.AuthError:
        _say("  ✗ TMDB rejected that key. Check you copied the whole thing.")
        return 1
    except tmdb.TMDBError as exc:
        _say("  ! Couldn't reach TMDB to check it ({}). Saving anyway.".format(exc))
    else:
        _say("  ✓ Key works.")

    host = existing.get("ollama_host", config.DEFAULTS["ollama_host"])
    model = existing.get("ollama_model", config.DEFAULTS["ollama_model"])
    models = llm.list_models(host)
    _say()
    if models:
        _say("Ollama models available:")
        for index, name in enumerate(models, 1):
            marker = " (current)" if name == model else ""
            _say("  {}. {}{}".format(index, name, marker))
        choice = _ask("Model to use for mood tags and picks", model)
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            model = models[int(choice) - 1]
        elif choice:
            model = choice
    else:
        _say("! Ollama isn't answering at {} — keeping {}.".format(host, model))
        _say("  Mood tags and lazy-pick need it; everything else works without.")

    cfg = dict(config.DEFAULTS)
    cfg.update(existing)
    cfg.update({
        "library_path": library,
        "tmdb_api_key": key,
        "ollama_host": host,
        "ollama_model": model,
    })
    path = config.save(cfg)
    _say()
    _say("Saved {} (mode 600).".format(path))
    _say("Next: lazy-catalog update")
    return 0


# -- update / rebuild --------------------------------------------------

def _enricher(cfg: Dict[str, Any], report, use_llm: bool = True):
    """Build the callback that fills a record in from TMDB, ffprobe and ollama."""
    from . import probe

    client: Optional[tmdb.Client] = None
    try:
        client = tmdb.Client(cfg["tmdb_api_key"], cfg.get("language", "en-US"))
    except tmdb.AuthError as exc:
        report("! {}".format(exc))

    posters = config.state_dir(cfg) / "posters"
    host = cfg["ollama_host"]
    model = cfg["ollama_model"]

    def enrich(record: Dict[str, Any], entry) -> None:
        # 1. Local truth first: it never fails and never lies.
        record["tech"] = probe.describe(entry)

        # 2. A name the regexes couldn't read gets one model opinion.
        if entry.parsed.confidence == "low" and use_llm:
            guessed = llm.clean_name(host, model, entry.key)
            if guessed:
                record["title"], record["year"] = guessed
                report("  named by model: {} -> {}".format(entry.key, guessed[0]))

        # 3. Facts.
        if client is not None:
            try:
                found = client.lookup(record["title"], record.get("year"),
                                      record.get("kind", "film"))
            except tmdb.TMDBError as exc:
                report("  ! {}: {}".format(record["title"], exc))
                found = None
            if found:
                poster_url = found.pop("poster_url", None)
                found_year = found.pop("year", None)
                record.update({k: v for k, v in found.items() if v not in (None, [], "")})
                if found_year and not record.get("year"):
                    record["year"] = found_year
                record["enriched"] = True
                if poster_url:
                    target = posters / "{}.jpg".format(record["tmdb_id"])
                    if target.is_file() or tmdb.download_poster(poster_url, target):
                        record["poster"] = "posters/{}.jpg".format(record["tmdb_id"])
            else:
                record.setdefault("issues", []).append("no TMDB match")
                report("  ? no TMDB match for {}".format(record["title"]))

        # 4. Opinions last, and only when there's something to react to.
        if use_llm and not record.get("moods"):
            record["moods"] = llm.mood_tags(
                host, model, record["title"], record.get("year"),
                record.get("genres") or [], record.get("overview") or "")

    return enrich


def _run(cfg: Dict[str, Any], args: argparse.Namespace, rebuild: bool) -> int:
    report = (lambda m: None) if args.quiet else _say
    enrich = None if args.no_enrich else _enricher(cfg, report, use_llm=not args.no_llm)

    kwargs: Dict[str, Any] = {"enrich": enrich, "report": report}
    if args.now:
        kwargs["settle_rounds"] = 0
        kwargs["force_ready"] = True

    lock_path = config.state_dir(cfg) / LOCK_NAME
    try:
        with held(lock_path):
            runner = catalog.rebuild if rebuild else catalog.update
            result = runner(cfg, **kwargs)
    except AlreadyRunning as exc:
        _say("Skipping: {}".format(exc))
        return 0
    except FileNotFoundError as exc:
        _say(str(exc))
        return 1

    if not args.quiet:
        _say()
        _say("{} titles in {}".format(result["total"], result["contents"]))
        if result["added"]:
            _say("added {}".format(len(result["added"])))
        if result["removed"]:
            _say("removed {}".format(len(result["removed"])))
        if result["pending"]:
            _say("{} still downloading, will be picked up later".format(
                len(result["pending"])))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    return _run(config.load(), args, rebuild=False)


def cmd_rebuild(args: argparse.Namespace) -> int:
    return _run(config.load(), args, rebuild=True)


def cmd_status(args: argparse.Namespace) -> int:
    from .cache import Cache

    cfg = config.load()
    cache = Cache.load(config.state_dir(cfg) / catalog.CACHE_NAME)
    ready = cache.ready()
    _say("library   {}".format(config.library_path(cfg)))
    _say("config    {}".format(config.config_path()))
    _say("model     {}".format(cfg["ollama_model"]))
    _say("titles    {} ready, {} pending".format(ready and len(ready) or 0,
                                                 len(cache) - len(ready)))
    _say("watched   {}".format(sum(1 for r in ready if r.get("watched"))))
    missing = [r["title"] for r in ready if not r.get("enriched")]
    if missing:
        _say("no TMDB   {}".format(", ".join(missing[:8])))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lazy-catalog",
        description="Catalogue a local film and TV library into CONTENTS.md.")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="set up the config and TMDB key")

    for name, help_text in (("update", "catalogue new folders"),
                            ("rebuild", "discard the cache and start over")):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("--now", action="store_true",
                         help="skip the wait for downloads to settle")
        sub.add_argument("--quiet", action="store_true", help="only report errors")
        sub.add_argument("--no-enrich", action="store_true",
                         help="filesystem only: no TMDB, no model")
        sub.add_argument("--no-llm", action="store_true",
                         help="TMDB facts but no mood tags")

    subparsers.add_parser("status", help="show what the catalogue knows")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    handlers = {
        "init": cmd_init,
        "update": cmd_update,
        "rebuild": cmd_rebuild,
        "status": cmd_status,
    }
    try:
        return handlers[args.command](args)
    except config.ConfigError as exc:
        _say(str(exc))
        return 1
    except KeyboardInterrupt:
        _say("\nStopped.")
        return 130
