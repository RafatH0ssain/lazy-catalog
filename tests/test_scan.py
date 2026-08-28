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
