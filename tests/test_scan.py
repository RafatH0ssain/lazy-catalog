import tempfile
import unittest
from pathlib import Path

from lazycatalog import scan


def make(root: Path, rel: str, size: int = 1024) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0" * size)
    return path


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_file_folder_is_a_film(self):
        make(self.root, "Her (2013) [1080p]/Her.2013.1080p.BluRay.x264.YIFY.mp4", 4096)
        entries = scan.scan_library(self.root)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].kind, "film")
        self.assertEqual(entries[0].parsed.title, "Her")
        self.assertEqual(entries[0].total_size, 4096)

    def test_flat_episode_files_make_a_series(self):
        folder = "The.Crowded.Room.S01.COMPLETE.1080p.ATVP.WEB-DL.DDP5.1.H.264-NTb[TGx]"
        for ep in (4, 5, 6):
            make(self.root, "{}/The.Crowded.Room.S01E{:02d}.Title.mkv".format(folder, ep))
        entry = scan.scan_library(self.root)[0]
        self.assertEqual(entry.kind, "series")
        self.assertEqual(entry.seasons, {1: 3})
        self.assertEqual(entry.episode_count, 3)

    def test_season_folders_attribute_episodes_without_sxxeyy(self):
        base = "Adventure Time (2010) Season 1-10 S01-S10 + Extras (1080p)"
        make(self.root, base + "/Season 01/ep one.mkv")
        make(self.root, base + "/Season 01/ep two.mkv")
        make(self.root, base + "/Season 02/ep three.mkv")
        make(self.root, base + "/Extras/behind the scenes.mkv")
        entry = scan.scan_library(self.root)[0]
        self.assertEqual(entry.kind, "series")
        self.assertEqual(entry.seasons[1], 2)
        self.assertEqual(entry.seasons[2], 1)
        self.assertTrue(entry.has_extras)

    def test_extras_do_not_count_as_episodes(self):
        base = "Show (2010)"
        make(self.root, base + "/Season 01/Show.S01E01.mkv")
        make(self.root, base + "/Season 01/Show.S01E02.mkv")
        make(self.root, base + "/Extras/Season 01/Animatic Extra 1.mkv")
        make(self.root, base + "/Extras/Season 01/Animatic Extra 2.mkv")
        entry = scan.scan_library(self.root)[0]
        self.assertEqual(entry.seasons, {1: 2})
        self.assertEqual(entry.episode_count, 2)
        self.assertTrue(entry.has_extras)

    def test_specials_are_counted_separately_from_episodes(self):
        base = "Show (2010)"
        for ep in (1, 2, 3):
            make(self.root, base + "/Season 01/Show.S01E{:02d}.mkv".format(ep))
        for ep in (1, 2):
            make(self.root, base + "/Season 00/Show.S00E{:02d}.mkv".format(ep))
        entry = scan.scan_library(self.root)[0]
        self.assertEqual(entry.episode_count, 3)
        self.assertEqual(entry.specials, 2)

    def test_an_extra_is_never_the_file_you_play(self):
        base = "Show (2010)"
        make(self.root, base + "/Extras/Season 01/Animatic Extra 1.mkv", 9999)
        make(self.root, base + "/Season 01/Show.S01E01.mkv", 100)
        entry = scan.scan_library(self.root)[0]
        self.assertEqual(entry.primary_video().path.name, "Show.S01E01.mkv")

    def test_a_film_ignores_its_sample_file(self):
        make(self.root, "Film (2020)/Sample/sample.mkv", 50)
        make(self.root, "Film (2020)/Film.mkv", 900)
        entry = scan.scan_library(self.root)[0]
        self.assertEqual(entry.primary_video().path.name, "Film.mkv")

    def test_a_loose_video_file_is_catalogued(self):
        """Not every film arrives in its own folder."""
        make(self.root, "Coyote.vs.Acme.2026.1080p.HEVC.x265.RMTeam.mkv", 4096)
        entries = scan.scan_library(self.root)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.kind, "film")
        self.assertEqual(entry.parsed.title, "Coyote vs Acme")
        self.assertEqual(entry.parsed.year, 2026)
        self.assertEqual(entry.total_size, 4096)
        self.assertEqual(len(entry.videos), 1)

    def test_a_loose_files_extension_is_not_part_of_its_title(self):
        make(self.root, "Send Help 2026 1080p WEB-DL x265 BONE.mkv")
        self.assertEqual(scan.scan_library(self.root)[0].parsed.title, "Send Help")

    def test_the_key_of_a_loose_file_keeps_its_extension(self):
        """The key has to name something that exists on disk."""
        make(self.root, "Leviticus.2026.1080p.WEBRip.x265-NeoNoir.mkv")
        self.assertEqual(scan.scan_library(self.root)[0].key,
                         "Leviticus.2026.1080p.WEBRip.x265-NeoNoir.mkv")

    def test_loose_files_and_folders_live_side_by_side(self):
        make(self.root, "Her (2013) [1080p]/Her.mp4")
        make(self.root, "Leviticus.2026.1080p.mkv")
        self.assertEqual(len(scan.scan_library(self.root)), 2)

    def test_a_sidecar_subtitle_beside_a_loose_file_is_found(self):
        make(self.root, "Leviticus.2026.1080p.mkv")
        make(self.root, "Leviticus.2026.1080p.srt")
        self.assertTrue(scan.scan_library(self.root)[0].external_subs)

    def test_a_language_tagged_sidecar_is_also_found(self):
        make(self.root, "Leviticus.2026.mkv")
        make(self.root, "Leviticus.2026.en.srt")
        self.assertTrue(scan.scan_library(self.root)[0].external_subs)

    def test_a_sidecar_for_a_different_film_is_not_borrowed(self):
        make(self.root, "Leviticus.2026.mkv")
        make(self.root, "Something Else.srt")
        self.assertFalse(scan.scan_library(self.root)[0].external_subs)

    def test_loose_non_video_files_are_not_catalogued(self):
        make(self.root, "CONTENTS.md")
        make(self.root, "WATCHLIST.md")
        make(self.root, "poster.jpg")
        self.assertEqual(scan.scan_library(self.root), [])

    def test_a_partial_loose_download_is_ignored_until_it_is_renamed(self):
        """A .part becomes a real filename when it finishes, under a new key,
        so cataloguing it now would only create an entry that vanishes."""
        make(self.root, "Leviticus.2026.mkv.part")
        self.assertEqual(scan.scan_library(self.root), [])

    def test_a_growing_loose_file_changes_its_signature(self):
        path = make(self.root, "Leviticus.2026.mkv", 100)
        first = scan.folder_signature(path)
        make(self.root, "Leviticus.2026.mkv", 900)
        self.assertNotEqual(first, scan.folder_signature(path))
        self.assertTrue(first)

    def test_a_loose_episode_file_is_still_one_thing_to_watch(self):
        make(self.root, "Show.S01E01.Pilot.1080p.mkv")
        entry = scan.scan_library(self.root)[0]
        self.assertEqual(len(entry.videos), 1)
        self.assertEqual(entry.primary_video().path.name,
                         "Show.S01E01.Pilot.1080p.mkv")

    def test_incomplete_download_is_flagged(self):
        make(self.root, "Some Movie (2020)/movie.mkv.part")
        entry = scan.scan_library(self.root)[0]
        self.assertTrue(entry.incomplete)
        self.assertIn("download looks incomplete", entry.issues)

    def test_folder_with_no_video_is_flagged(self):
        make(self.root, "Empty Movie (2020)/readme.txt")
        entry = scan.scan_library(self.root)[0]
        self.assertIn("no video files found", entry.issues)

    def test_external_subtitles_are_detected(self):
        make(self.root, "Closer (2004)/Closer.mkv")
        make(self.root, "Closer (2004)/Closer.srt")
        entry = scan.scan_library(self.root)[0]
        self.assertTrue(entry.external_subs)

    def test_state_dir_and_loose_files_are_ignored(self):
        make(self.root, ".lazy/cache.json")
        make(self.root, "CONTENTS.md")
        make(self.root, "Dogma (1999)/Dogma.mkv")
        entries = scan.scan_library(self.root)
        self.assertEqual([e.key for e in entries], ["Dogma (1999)"])

    def test_signature_changes_while_a_download_grows(self):
        folder = self.root / "Growing (2021)"
        make(self.root, "Growing (2021)/part.mkv", 100)
        first = scan.folder_signature(folder)
        make(self.root, "Growing (2021)/part.mkv", 500)
        self.assertNotEqual(first, scan.folder_signature(folder))

    def test_missing_library_raises(self):
        with self.assertRaises(FileNotFoundError):
            scan.scan_library(self.root / "nope")


if __name__ == "__main__":
    unittest.main()
