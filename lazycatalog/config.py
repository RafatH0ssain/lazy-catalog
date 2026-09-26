"""Configuration loading.

The real config holds a TMDB API key, so it lives outside the repo in
~/.config/lazy-catalog/config.json at mode 600 and is written by
`lazy-catalog init` rather than by hand. LAZY_CATALOG_CONFIG overrides the
location, which is what the tests use.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

CONFIG_ENV = "LAZY_CATALOG_CONFIG"

DEFAULTS: Dict[str, Any] = {
    "library_path": "~/TV",
    "tmdb_api_key": "",
    "ollama_host": "http://localhost:11434",
    # 12B is the sweet spot here: on a 24GB machine the 24B model measured
    # 20GB resident and 12.7s per call, against 8.6GB and 4.7s for this, with
    # tags that were no better. None of these jobs need the extra weight.
    "ollama_model": "gemma3:12b",
    # Recalling films you don't own rewards breadth over reasoning, so the best
    # model for `suggest` is often not the best one for `pick`: gemma3 returns
    # less obvious picks here, and twice as fast. Falls back to ollama_model if
    # it isn't installed. Empty means use ollama_model.
    "suggest_model": "gemma3:12b",
    "language": "en-US",
    "subtitle_languages": ["en"],
}


class ConfigError(Exception):
    """Raised when the config is missing or unusable."""


def config_path() -> Path:
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "lazy-catalog" / "config.json"


def exists() -> bool:
    return config_path().is_file()


def load() -> Dict[str, Any]:
    """Return the config, defaults filled in. Raises ConfigError if unusable."""
    path = config_path()
    if not path.is_file():
        raise ConfigError(
            "No config found at {}.\nRun `lazy-catalog init` to create one.".format(path)
        )
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ConfigError("{} is not valid JSON: {}".format(path, exc)) from exc
    if not isinstance(data, dict):
        raise ConfigError("{} must contain a JSON object.".format(path))

    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if v is not None})
    return merged


def save(data: Dict[str, Any]) -> Path:
    """Write the config at mode 600, creating the directory if needed."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write then chmod before the key lands on disk world-readable: create the
    # file empty with the right mode rather than fixing it up afterwards.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.chmod(str(path), 0o600)
    return path


def library_path(cfg: Dict[str, Any]) -> Path:
    return Path(str(cfg["library_path"])).expanduser()


def state_dir(cfg: Dict[str, Any]) -> Path:
    """Hidden per-library state: cache, cached posters, run log."""
    return library_path(cfg) / ".lazy"
