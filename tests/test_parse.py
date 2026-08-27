import unittest

from lazycatalog import parse

# The real folder names from the library this was built against. If the parser
# regresses on any of these, it regresses on a case that actually happened.
CORPUS = [
    ("Anomalisa.2015.1080p.BluRay.DDP5.1.x265.10bit-GalaxyRG265[TGx]",
     "Anomalisa", 2015),
    ("Beau.is.Afraid.2023.1080p.AMZN.WEBRip.1600MB.DD5.1.x264-GalaxyRG[TGx]",
     "Beau is Afraid", 2023),
    ("Blue Valentine (2010) [1080p]", "Blue Valentine", 2010),
    ("Closer (2004)", "Closer", 2004),
    ("Dogma (1999)", "Dogma", 1999),
    ("Force Majeure (2014) [BluRay] [1080p] [YTS.AM]", "Force Majeure", 2014),
    ("Her (2013) [1080p]", "Her", 2013),
    ("Nocturnal Animals 2016 1080p WEB-DL x264 AC3-JYK",
     "Nocturnal Animals", 2016),
    ("The Lobster 2015 1080p BluRay x264 DTS-JYK", "The Lobster", 2015),
    ("The Truman Show (1998) [1080p]", "The Truman Show", 1998),
    ("The.Thing.1982.REMASTERED.1080p.BluRay.x264.AAC5.0-ShAaNiG",
     "The Thing", 1982),
    ("Wild Tales 2014 Blu-ray 1080p x264 DD 5.1-HighCode", "Wild Tales", 2014),
]

SERIES_CORPUS = [
    ("Adventure Time (2010) Season 1-10 S01-S10 + Extras "
     "(1080p BluRay x265 HEVC 10bit AAC 2.0 ImE)", "Adventure Time", 2010),
    ("The.Crowded.Room.S01.COMPLETE.1080p.ATVP.WEB-DL.DDP5.1.H.264-NTb[TGx]",
     "The Crowded Room", None),
]


class ParseTitleTest(unittest.TestCase):
    def test_real_film_folders(self):
        for folder, title, year in CORPUS:
            with self.subTest(folder=folder):
                got = parse.parse_folder(folder)
                self.assertEqual(got.title, title)
                self.assertEqual(got.year, year)

    def test_real_series_folders(self):
        for folder, title, year in SERIES_CORPUS:
            with self.subTest(folder=folder):
                got = parse.parse_folder(folder)
                self.assertEqual(got.title, title)
                self.assertEqual(got.year, year)
                self.assertTrue(got.series_hint, "should look like a series")

    def test_films_are_not_flagged_as_series(self):
        for folder, _, _ in CORPUS:
            with self.subTest(folder=folder):
                self.assertFalse(parse.parse_folder(folder).series_hint)

    def test_a_title_that_is_itself_a_year_is_not_eaten(self):
        got = parse.parse_folder("2012 (2009) [1080p]")
        self.assertEqual(got.title, "2012")
        self.assertEqual(got.year, 2009)

    def test_year_only_title_without_release_year(self):
        got = parse.parse_folder("1917.2019.1080p.BluRay.x264-SPARKS")
        self.assertEqual(got.title, "1917")
        self.assertEqual(got.year, 2019)

    def test_unparseable_name_reports_low_confidence(self):
        got = parse.parse_folder("xX_rip_final_v2_Xx")
        self.assertEqual(got.confidence, "low")

    def test_year_bearing_name_is_high_confidence(self):
        self.assertEqual(parse.parse_folder("Closer (2004)").confidence, "high")


class EpisodeTest(unittest.TestCase):
    def test_season_and_episode_from_filename(self):
        got = parse.parse_episode(
            "The.Crowded.Room.S01E04.London.1080p.ATVP.WEB-DL.DDP5.1.H.264-NTb.mkv")
        self.assertEqual(got, (1, 4))

    def test_alternative_episode_notation(self):
        self.assertEqual(parse.parse_episode("Show.1x03.mkv"), (1, 3))

    def test_non_episode_returns_none(self):
        self.assertIsNone(parse.parse_episode("Her.2013.1080p.BluRay.mp4"))

    def test_season_number_from_folder(self):
        self.assertEqual(parse.parse_season_folder("Season 01"), 1)
        self.assertEqual(parse.parse_season_folder("Season 00"), 0)
        self.assertIsNone(parse.parse_season_folder("Extras"))


if __name__ == "__main__":
    unittest.main()
