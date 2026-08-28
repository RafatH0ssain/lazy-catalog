"""A local server so the page can hand a file to VLC.

VLC registers no URL scheme on macOS, so a page loaded from file:// has no way
to launch it. This serves the same page over 127.0.0.1 and adds one endpoint
that opens a title in VLC.

The endpoint never accepts a path. It accepts a cache key, looks the path up
itself, and refuses anything that does not resolve to a real file inside the
library — a page in another tab must not be able to talk this into opening
arbitrary files. A per-run token, checked on every request, means only the page
this server itself served can call it at all.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from . import catalog, config, render_web
from .cache import Cache

PLAYER = "VLC"
MAX_BODY = 4096


def _launch(path: Path) -> Tuple[bool, str]:
    if not Path("/Applications/{}.app".format(PLAYER)).is_dir():
        return False, "{} isn't installed in /Applications.".format(PLAYER)
    try:
        done = subprocess.run(["open", "-a", PLAYER, str(path)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if done.returncode != 0:
        return False, done.stdout.decode("utf-8", "replace").strip() or "open failed"
    return True, "Playing {} in {}".format(path.name, PLAYER)


class Player:
    """Resolves a cache key to a real file and hands it to VLC."""

    def __init__(self, cfg: Dict[str, Any], launcher=None):
        self.cfg = cfg
        self.library = config.library_path(cfg).resolve()
        self.launcher = launcher or _launch

    def _lookup(self, key: str) -> Tuple[Optional[Path], Optional[str]]:
        cache = Cache.load(config.state_dir(self.cfg) / catalog.CACHE_NAME)
        record = cache.get(key)
        if record is None:
            return None, "That title isn't in the catalogue."
        relative = record.get("video")
        if not relative:
            return None, "No video file was found for {}.".format(
                record.get("title") or key)

        path = (self.library / relative).resolve()
        # The key came from the page, but the path must still be proved to sit
        # inside the library: a crafted cache or a symlink could point anywhere.
        try:
            path.relative_to(self.library)
        except ValueError:
            return None, "That file is outside the library."
        if not path.is_file():
            return None, "The file has moved or been deleted."
        return path, None

    def play(self, key: str) -> Tuple[bool, str]:
        path, error = self._lookup(key)
        if error:
            return False, error
        return self.launcher(path)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, cfg: Dict[str, Any], token: str,
                 player: Player, **kwargs: Any):
        self.cfg = cfg
        self.token = token
        self.player = player
        super().__init__(*args, directory=str(config.state_dir(cfg)), **kwargs)

    # Quiet by default; the terminal is the user's, not a request log.
    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self) -> bool:
        if self.headers.get("X-Lazy-Token") != self.token:
            return False
        # A page on another origin must not be able to drive this, even if it
        # somehow learned the token.
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
            return False
        return True

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            cache = Cache.load(config.state_dir(self.cfg) / catalog.CACHE_NAME)
            # Rendered per request so the page is never stale, and so the token
            # lives only in what is served rather than on disk.
            html = render_web.render(cache.ready(), token=self.token).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(html)
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path != "/play":
            self._json(404, {"ok": False, "error": "Unknown endpoint."})
            return
        if not self._authorised():
            self._json(403, {"ok": False, "error": "Not allowed."})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._json(400, {"ok": False, "error": "Bad request."})
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            key = str(payload["key"])
        except (ValueError, KeyError, TypeError):
            self._json(400, {"ok": False, "error": "Bad request."})
            return

        ok, message = self.player.play(key)
        self._json(200 if ok else 409, {"ok": ok,
                                        "error": None if ok else message,
                                        "message": message if ok else None})


def start(cfg: Dict[str, Any], port: int = 0,
          launcher=None) -> Tuple[ThreadingHTTPServer, str, str]:
    """Start the server on localhost. Returns (server, url, token)."""
    token = secrets.token_urlsafe(24)
    player = Player(cfg, launcher=launcher)
    handler = partial(Handler, cfg=cfg, token=token, player=player)

    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    url = "http://127.0.0.1:{}/".format(server.server_address[1])
    return server, url, token


def serve_forever(cfg: Dict[str, Any], port: int = 0) -> Tuple[str, threading.Thread]:
    server, url, _token = start(cfg, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return url, thread
