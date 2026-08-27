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
    client: Optional[tmdb.Client] = None
    try:
        client = tmdb.Client(cfg["tmdb_api_key"], cfg.get("language", "en-US"))
    except tmdb.AuthError as exc:
        report("! {}".format(exc))

    posters = config.state_dir(cfg) / "posters"
    host = cfg["ollama_host"]
    model = cfg["ollama_model"]

    def enrich(record: Dict[str, Any], entry) -> None:
        # Tech specs are handled by the local-facts pass, which refreshes them
        # on every run rather than only at first sight.

        # 1. A name the regexes couldn't read gets one model opinion.
        if entry.parsed.confidence == "low" and use_llm:
            guessed = llm.clean_name(host, model, entry.key)
            if guessed:
                record["title"], record["year"] = guessed
                report("  named by model: {} -> {}".format(entry.key, guessed[0]))

        # 2. Facts.
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

        # 3. Opinions last, and only when there's something to react to.
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


def cmd_pick(args: argparse.Namespace) -> int:
    from . import pick
    from .cache import Cache

    cfg = config.load()
    cache = Cache.load(config.state_dir(cfg) / catalog.CACHE_NAME)
    records = cache.ready()
    if args.unwatched:
        records = [r for r in records if not r.get("watched")]
    if args.kind:
        records = [r for r in records if r.get("kind") == args.kind]

    request = " ".join(args.request).strip() or "something good tonight"
    result, error = pick.choose(records, request, cfg["ollama_host"],
                                cfg["ollama_model"])
    if error:
        _say(error)
        return 1
    _say(pick.format_result(result, records, colour=sys.stdout.isatty()))
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    from .cache import Cache

    cfg = config.load()
    cache = Cache.load(config.state_dir(cfg) / catalog.CACHE_NAME)
    path = catalog.write_web(cfg, cache.ready())
    print(path)
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    from . import install as installer

    cfg = config.load()
    library = config.library_path(cfg)
    if not library.is_dir():
        _say("Library folder {} doesn't exist yet.".format(library))
        return 1

    ok, detail = installer.install(
        library, Path(__file__).resolve().parent.parent,
        config.state_dir(cfg), config.config_path())
    if not ok:
        _say(detail)
        return 1
    _say("Watching {} — {}".format(library, installer.status()))
    _say("Agent: {}".format(detail))
    _say("It runs on any change to the folder, plus every 30 minutes as a backstop.")
    _say("Log: {}".format(config.state_dir(cfg) / "run.log"))
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    from . import install as installer

    ok, detail = installer.uninstall()
    _say("Stopped watching. Removed {}".format(detail))
    return 0 if ok else 1


def cmd_subs(args: argparse.Namespace) -> int:
    from . import scan, subs
    from .cache import Cache

    cfg = config.load()
    if not subs.available():
        _say("subliminal isn't installed. Add it with:")
        _say("    uv tool install subliminal")
        return 1

    cache = Cache.load(config.state_dir(cfg) / catalog.CACHE_NAME)
    wanted = subs.candidates(cache.ready())
    if args.title:
        needle = args.title.lower()
        wanted = [r for r in wanted if needle in (r.get("title") or "").lower()]
    if args.kind:
        wanted = [r for r in wanted if r.get("kind") == args.kind]
    if not wanted:
        _say("Nothing is missing subtitles.")
        return 0

    # Work out the real size of the job first. A single ten-season series is
    # hundreds of episodes, and the free providers are rate limited per day, so
    # sweeping the whole library would spend the quota before it got anywhere
    # useful.
    library = config.library_path(cfg)
    jobs = []
    for record in wanted:
        folder = library / record["key"]
        if not folder.is_dir():
            continue
        entry = scan.scan_folder(folder)
        for video in entry.videos:
            jobs.append((record, video.path))

    languages = args.lang or cfg.get("subtitle_languages") or ["en"]
    _say("{} file(s) across {} title(s) have no subtitles:".format(
        len(jobs), len(wanted)))
    for record in wanted:
        count = sum(1 for r, _ in jobs if r["key"] == record["key"])
        _say("  {:>4} × {}".format(count, record.get("title") or record["key"]))
    _say()

    if args.dry_run:
        _say("Nothing downloaded. Drop --dry-run to fetch {} subtitles.".format(
            "/".join(languages)))
        return 0

    if len(jobs) > args.max and not args.title:
        _say("That's more than --max ({}), and free subtitle providers cap how".format(
            args.max))
        _say("many you can pull per day. Narrow it down or raise the ceiling:")
        _say("    lazy-catalog subs --films")
        _say("    lazy-catalog subs --title \"Her\"")
        _say("    lazy-catalog subs --max {}".format(len(jobs)))
        return 1

    _say("Fetching {} subtitles...".format("/".join(languages)))
    found = 0
    for record, path in jobs[:args.max]:
        ok, detail = subs.fetch(path, languages)
        _say("  {} {} — {}".format("✓" if ok else "·", path.name, detail))
        found += 1 if ok else 0

    _say()
    _say("{} of {} found. Run `lazy-catalog update` to record them.".format(
        found, len(jobs[:args.max])))
    return 0


def cmd_nfo(args: argparse.Namespace) -> int:
    from . import nfo
    from .cache import Cache

    cfg = config.load()
    library = config.library_path(cfg)
    state = config.state_dir(cfg)
    cache = Cache.load(state / catalog.CACHE_NAME)

    written = 0
    for record in cache.ready():
        if not record.get("enriched"):
            continue
        folder = library / record["key"]
        if not folder.is_dir():
            continue
        poster = state / record["poster"] if record.get("poster") else None
        target = nfo.write(record, folder, poster)
        written += 1
        if not args.quiet:
            _say("  {}".format(target))

    _say("Wrote {} sidecar file(s). Jellyfin, Kodi and Plex will read these."
         .format(written))
    return 0


def cmd_suggest_renames(args: argparse.Namespace) -> int:
    """Report only. This never touches a file — see README for why."""
    from .cache import Cache

    cfg = config.load()
    cache = Cache.load(config.state_dir(cfg) / catalog.CACHE_NAME)

    suggestions = []
    for record in sorted(cache.ready(), key=lambda r: r["key"].lower()):
        title = record.get("title") or record["key"]
        year = record.get("year")
        ideal = "{} ({})".format(title, year) if year else title
        ideal = ideal.replace("/", "-")
        if ideal != record["key"]:
            suggestions.append((record["key"], ideal))

    if not suggestions:
        _say("Every folder is already named the way a media server expects.")
        return 0

    _say("These folder names could be tidier. Nothing has been changed —")
    _say("copy any line you want and run it yourself.")
    _say()
    library = config.library_path(cfg)
    for current, ideal in suggestions:
        _say("  {}".format(current))
        _say("    -> {}".format(ideal))
        _say('    mv {} {}'.format(
            _shell_quote(str(library / current)), _shell_quote(str(library / ideal))))
        _say()
    _say("Two things worth knowing before you rename anything:")
    _say("  · the catalogue is keyed on the folder name, so a renamed title")
    _say("    loses its watched tick and is re-catalogued as if it were new;")
    _say("  · `lazy-catalog nfo` gets you media-server recognition without")
    _say("    touching a single filename, which is usually the better trade.")
    return 0


def _shell_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


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

    picker = subparsers.add_parser(
        "pick", help="ask the local model what to watch")
    picker.add_argument("request", nargs="*",
                        help="what you're in the mood for, in plain English")
    picker.add_argument("--unwatched", action="store_true",
                        help="only consider things you haven't ticked off")
    picker.add_argument("--films", dest="kind", action="store_const", const="film",
                        help="films only")
    picker.add_argument("--series", dest="kind", action="store_const", const="series",
                        help="series only")
    picker.set_defaults(kind=None)

    subparsers.add_parser("web", help="rebuild the browsable page and print its path")

    subparsers.add_parser("install", help="watch the library automatically (launchd)")
    subparsers.add_parser("uninstall", help="stop watching the library")

    sub_cmd = subparsers.add_parser("subs", help="download missing subtitles")
    sub_cmd.add_argument("--lang", action="append",
                         help="language code, repeatable (default: from config)")
    sub_cmd.add_argument("--title", help="only this title")
    sub_cmd.add_argument("--dry-run", action="store_true",
                         help="list what's missing without downloading")
    sub_cmd.add_argument("--max", type=int, default=25,
                         help="most files to fetch in one run (default: 25)")
    sub_cmd.add_argument("--films", dest="kind", action="store_const", const="film",
                         help="films only, skipping series")
    sub_cmd.add_argument("--series", dest="kind", action="store_const", const="series",
                         help="series only")
    sub_cmd.set_defaults(kind=None)

    nfo_cmd = subparsers.add_parser(
        "nfo", help="write .nfo sidecars for Jellyfin, Kodi and Plex")
    nfo_cmd.add_argument("--quiet", action="store_true")

    subparsers.add_parser(
        "suggest-renames", help="report tidier folder names without changing anything")
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
        "pick": cmd_pick,
        "web": cmd_web,
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "subs": cmd_subs,
        "nfo": cmd_nfo,
        "suggest-renames": cmd_suggest_renames,
    }
    try:
        return handlers[args.command](args)
    except config.ConfigError as exc:
        _say(str(exc))
        return 1
    except KeyboardInterrupt:
        _say("\nStopped.")
        return 130
