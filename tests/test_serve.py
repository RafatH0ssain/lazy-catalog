import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from lazycatalog import catalog, config, serve
from lazycatalog.cache import Cache, new_record


def make(root: Path, rel: str, size: int = 1024) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0" * size)
    return path


class ServeTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "TV"
        self.root.mkdir()
        make(self.root, "Her (2013)/Her.mp4")
        make(self.root, "Outside/secret.mp4")   # sits outside the library below
        self.cfg = dict(config.DEFAULTS, library_path=str(self.root))
        catalog.update(self.cfg, settle_rounds=0)

        self.launched = []
        self.server, self.url, self.token = serve.start(
            self.cfg, 0, launcher=self._fake_launch)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _fake_launch(self, path):
        self.launched.append(path)
        return True, "Playing {} in VLC".format(path.name)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def post(self, key, token=None, origin=None):
        request = urllib.request.Request(
            self.url + "play",
            data=json.dumps({"key": key}).encode(),
            headers={"Content-Type": "application/json",
                     "X-Lazy-Token": self.token if token is None else token},
            method="POST")
        if origin:
            request.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


class PlayEndpointTest(ServeTestBase):
    def test_a_valid_key_launches_the_file(self):
        status, body = self.post("Her (2013)")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(self.launched[0].name, "Her.mp4")

    def test_without_the_token_nothing_launches(self):
        status, body = self.post("Her (2013)", token="wrong")
        self.assertEqual(status, 403)
        self.assertEqual(self.launched, [])

    def test_a_foreign_origin_is_refused(self):
        status, body = self.post("Her (2013)", origin="https://evil.example")
        self.assertEqual(status, 403)
        self.assertEqual(self.launched, [])

    def test_an_unknown_key_launches_nothing(self):
        status, body = self.post("Not In The Catalogue")
        self.assertEqual(status, 409)
        self.assertIn("isn't in the catalogue", body["error"])
        self.assertEqual(self.launched, [])

    def test_the_endpoint_takes_keys_not_paths(self):
        """A path handed in as a key must not be opened."""
        for attempt in ("../Outside/secret.mp4",
                        "/etc/passwd",
                        "Her (2013)/../../Outside/secret.mp4"):
            with self.subTest(attempt=attempt):
                status, _ = self.post(attempt)
                self.assertEqual(status, 409)
        self.assertEqual(self.launched, [])

    def test_a_deleted_file_reports_rather_than_launching(self):
        (self.root / "Her (2013)" / "Her.mp4").unlink()
        status, body = self.post("Her (2013)")
        self.assertEqual(status, 409)
        self.assertIn("moved or been deleted", body["error"])

    def test_a_title_with_no_video_reports_clearly(self):
        cache = Cache.load(config.state_dir(self.cfg) / catalog.CACHE_NAME)
        record = new_record("Empty", "Empty", 2000, "film")
        record["status"] = "ready"
        cache.put(record)
        cache.save()
        status, body = self.post("Empty")
        self.assertEqual(status, 409)
        self.assertIn("No video file", body["error"])

    def test_unknown_endpoints_are_not_served(self):
        request = urllib.request.Request(self.url + "shutdown", data=b"{}",
                                         method="POST")
        request.add_header("X-Lazy-Token", self.token)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        self.assertEqual(status, 404)


class PageTest(ServeTestBase):
    def test_the_served_page_carries_the_token(self):
        with urllib.request.urlopen(self.url, timeout=5) as response:
            html = response.read().decode()
        self.assertIn(self.token, html)
        self.assertIn("button.play", html)

    def test_the_page_is_rendered_fresh_from_the_cache(self):
        with urllib.request.urlopen(self.url, timeout=5) as response:
            self.assertIn("Her", response.read().decode())

    def test_a_page_written_to_disk_has_no_token_and_no_play_control(self):
        path = catalog.write_web(self.cfg, [])
        self.assertNotIn(self.token, path.read_text(encoding="utf-8"))


class PrimaryVideoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "TV"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _record(self, key):
        cfg = dict(config.DEFAULTS, library_path=str(self.root))
        catalog.update(cfg, settle_rounds=0)
        cache = Cache.load(config.state_dir(cfg) / catalog.CACHE_NAME)
        return cache.get(key)

    def test_a_film_plays_its_largest_file(self):
        make(self.root, "Her (2013)/sample.mp4", 100)
        make(self.root, "Her (2013)/Her.mp4", 9999)
        self.assertEqual(self._record("Her (2013)")["video"], "Her (2013)/Her.mp4")

    def test_a_series_plays_its_earliest_episode_not_its_biggest(self):
        for ep, size in ((3, 9999), (1, 100), (2, 500)):
            make(self.root, "Show S01/Show.S01E{:02d}.mkv".format(ep), size)
        self.assertEqual(self._record("Show S01")["video"],
                         "Show S01/Show.S01E01.mkv")

    def test_specials_do_not_beat_season_one(self):
        """Season 0 is pilots and extras; starting a show means S01E01."""
        make(self.root, "Show/Season 00/Show.S00E01.Pilot.mkv", 100)
        make(self.root, "Show/Season 01/Show.S01E01.mkv", 100)
        make(self.root, "Show/Season 01/Show.S01E02.mkv", 100)
        self.assertEqual(self._record("Show")["video"],
                         "Show/Season 01/Show.S01E01.mkv")

    def test_specials_are_used_when_there_is_nothing_else(self):
        make(self.root, "Show/Season 00/Show.S00E01.Pilot.mkv", 100)
        self.assertEqual(self._record("Show")["video"],
                         "Show/Season 00/Show.S00E01.Pilot.mkv")

    def test_a_folder_with_no_video_has_no_playable_file(self):
        make(self.root, "Empty (2020)/readme.txt")
        self.assertIsNone(self._record("Empty (2020)")["video"])


if __name__ == "__main__":
    unittest.main()
