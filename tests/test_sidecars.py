import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from lazycatalog import cache, install, nfo, subs


def record(**kw):
    rec = cache.new_record("k", kw.pop("title", "The Thing"), kw.pop("year", 1982),
                           kw.pop("kind", "film"))
    rec.update(kw)
    return rec


class NfoTest(unittest.TestCase):
    def test_movie_sidecar_is_valid_xml_with_the_expected_tags(self):
        xml = nfo.build(record(overview="Hunted.", genres=["Horror", "Sci-Fi"],
                               rating=8.2, votes=9000, runtime=109,
                               director="John Carpenter", cast=["Kurt Russell"],
                               tmdb_id=1091))
        root = ET.fromstring(xml)
        self.assertEqual(root.tag, "movie")
        self.assertEqual(root.findtext("title"), "The Thing")
        self.assertEqual(root.findtext("runtime"), "109")
        self.assertEqual([g.text for g in root.findall("genre")], ["Horror", "Sci-Fi"])
        self.assertEqual(root.findtext("uniqueid"), "1091")

    def test_series_sidecar_uses_the_tvshow_root_and_omits_runtime(self):
        root = ET.fromstring(nfo.build(record(kind="series", title="Adventure Time",
                                              runtime=11)))
        self.assertEqual(root.tag, "tvshow")
        self.assertIsNone(root.find("runtime"))

    def test_missing_fields_are_left_out_rather_than_written_empty(self):
        root = ET.fromstring(nfo.build(record()))
        self.assertIsNone(root.find("plot"))
        self.assertIsNone(root.find("ratings"))

    def test_write_places_the_file_and_copies_the_poster(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "The Thing (1982)"
            folder.mkdir()
            poster = Path(tmp) / "1091.jpg"
            poster.write_bytes(b"jpegdata")
            target = nfo.write(record(tmdb_id=1091), folder, poster)
            self.assertEqual(target.name, "movie.nfo")
            self.assertEqual((folder / "poster.jpg").read_bytes(), b"jpegdata")


class LooseFileNfoTest(unittest.TestCase):
    """Kodi names a standalone film's sidecar after the file, not the folder."""

    def test_the_sidecar_sits_beside_the_file_and_shares_its_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "Coyote.vs.Acme.2026.1080p.mkv"
            video.write_bytes(b"0")
            target = nfo.write(record(title="Coyote vs Acme"), video)
            self.assertEqual(target.name, "Coyote.vs.Acme.2026.1080p.nfo")
            self.assertTrue(target.is_file())

    def test_each_loose_film_gets_its_own_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "A.2026.mkv"
            second = Path(tmp) / "B.2026.mkv"
            for path in (first, second):
                path.write_bytes(b"0")
                nfo.write(record(title=path.stem), path)
            self.assertTrue((Path(tmp) / "A.2026.nfo").is_file())
            self.assertTrue((Path(tmp) / "B.2026.nfo").is_file())

    def test_the_poster_is_named_after_the_file_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "A.2026.mkv"
            video.write_bytes(b"0")
            poster = Path(tmp) / "src.jpg"
            poster.write_bytes(b"jpegdata")
            nfo.write(record(), video, poster)
            self.assertEqual((Path(tmp) / "A.2026-poster.jpg").read_bytes(),
                             b"jpegdata")


class RenameSuggestionTest(unittest.TestCase):
    def test_a_loose_file_keeps_its_extension(self):
        """Dropping .mkv from a rename would make the file unplayable."""
        from lazycatalog import cli
        self.assertEqual(
            cli._ideal_name({"key": "Coyote.vs.Acme.2026.1080p.x265.mkv",
                             "title": "Coyote vs Acme", "year": 2026}),
            "Coyote vs Acme (2026).mkv")

    def test_a_folder_gets_no_extension(self):
        from lazycatalog import cli
        self.assertEqual(
            cli._ideal_name({"key": "Her (2013) [1080p]", "title": "Her",
                             "year": 2013}),
            "Her (2013)")

    def test_a_slash_in_a_title_is_not_turned_into_a_path(self):
        from lazycatalog import cli
        self.assertNotIn("/", cli._ideal_name(
            {"key": "x", "title": "Face/Off", "year": 1997}))


class SubsTest(unittest.TestCase):
    def test_embedded_subtitles_mean_nothing_to_download(self):
        self.assertFalse(subs.needs_subtitles(record(tech={"subs": ["eng"]})))

    def test_a_sidecar_srt_also_counts(self):
        self.assertFalse(subs.needs_subtitles(record(external_subs=True)))

    def test_no_subtitles_anywhere_is_a_candidate(self):
        self.assertTrue(subs.needs_subtitles(record(tech={"subs": []})))

    def test_candidates_filters_the_library(self):
        have = record(tech={"subs": ["eng"]})
        need = record(tech={"subs": []})
        self.assertEqual(subs.candidates([have, need]), [need])


class LaunchAgentTest(unittest.TestCase):
    def test_plist_watches_the_library_and_keeps_a_backstop_interval(self):
        payload = install.build_plist(
            Path("/Users/x/TV"), Path("/Users/x/Projects/lazy-catalog"),
            Path("/Users/x/TV/.lazy"), Path("/Users/x/.config/lazy-catalog/config.json"),
            "/usr/bin/python3")
        self.assertEqual(payload["WatchPaths"], ["/Users/x/TV"])
        self.assertEqual(payload["StartInterval"], 1800)
        self.assertFalse(payload["RunAtLoad"])

    def test_plist_carries_a_path_that_can_find_homebrew_tools(self):
        payload = install.build_plist(
            Path("/tv"), Path("/repo"), Path("/state"), Path("/cfg.json"), "python3")
        self.assertIn("/opt/homebrew/bin", payload["EnvironmentVariables"]["PATH"])

    def test_plist_points_at_the_config_it_was_installed_with(self):
        payload = install.build_plist(
            Path("/tv"), Path("/repo"), Path("/state"), Path("/cfg.json"), "python3")
        self.assertEqual(
            payload["EnvironmentVariables"]["LAZY_CATALOG_CONFIG"], "/cfg.json")

    def test_the_job_runs_quietly_and_logs_to_the_state_dir(self):
        payload = install.build_plist(
            Path("/tv"), Path("/repo"), Path("/state"), Path("/cfg.json"), "python3")
        self.assertIn("--quiet", payload["ProgramArguments"])
        self.assertEqual(payload["StandardOutPath"], "/state/run.log")


if __name__ == "__main__":
    unittest.main()
