import unittest
from datetime import datetime

from lazycatalog import cache, render_md


def film(key, title, year, **kw):
    rec = cache.new_record(key, title, year, "film")
    rec["status"] = "ready"
    rec.update(kw)
    return rec


class RenderTest(unittest.TestCase):
    def test_film_entry_has_facts_and_anchor(self):
        rec = film("The.Thing.1982.REMASTERED", "The Thing", 1982,
                   genres=["Horror", "Sci-Fi"], runtime=109, rating=8.2,
                   overview="A research team is hunted.", enriched=True,
                   moods=["bleak", "paranoid"], total_size=12_400_000_000,
                   tmdb_url="https://www.themoviedb.org/movie/1091",
                   tech={"resolution": "1080p", "video": "h264",
                         "audio": "AAC", "channels": "5.0", "subs": []})
        out = render_md.render([rec], now=datetime(2026, 8, 28, 14, 32))
        self.assertIn("**The Thing** (1982)", out)
        self.assertIn("Horror, Sci-Fi", out)
        self.assertIn("1h 49m", out)
        self.assertIn("★ 8.2", out)
        self.assertIn("*bleak · paranoid*", out)
        self.assertIn("no subs", out)
        self.assertIn("11.5 GB", out)
        self.assertIn("<!--k:The.Thing.1982.REMASTERED-->", out)
        self.assertIn("2026-08-28 14:32", out)

    def test_unenriched_facts_are_marked_unverified(self):
        rec = film("X (2020)", "X", 2020, genres=["Drama"], runtime=90,
                   rating=7.0, enriched=False)
        out = render_md.render([rec])
        self.assertIn("~Drama", out)
        self.assertIn("~★ 7.0", out)

    def test_series_shows_seasons_not_runtime(self):
        rec = cache.new_record("Adventure Time (2010)", "Adventure Time", 2010, "series")
        rec.update(status="ready", seasons={"1": 26, "2": 26}, episode_count=52,
                   genres=["Animation"], enriched=True)
        out = render_md.render([rec])
        self.assertIn("Seasons 1–2", out)
        self.assertIn("52 episodes", out)
        self.assertIn("## Series", out)

    def test_watched_roundtrips_through_the_file(self):
        seen = film("Her (2013) [1080p]", "Her", 2013, watched=True)
        unseen = film("Dogma (1999)", "Dogma", 1999, watched=False)
        out = render_md.render([seen, unseen])
        state = render_md.read_watched(out)
        self.assertEqual(state["Her (2013) [1080p]"], True)
        self.assertEqual(state["Dogma (1999)"], False)

    def test_watched_survives_a_folder_rename_in_the_heading(self):
        rec = film("Her (2013) [1080p]", "Her", 2013)
        out = render_md.render([rec]).replace("- [ ]", "- [x]")
        self.assertTrue(render_md.read_watched(out)["Her (2013) [1080p]"])

    def test_issues_get_their_own_section(self):
        rec = film("Broken (2020)", "Broken", 2020, issues=["no video files found"])
        out = render_md.render([rec])
        self.assertIn("## Needs attention", out)
        self.assertIn("no video files found", out)

    def test_stats_line_counts_films_and_series(self):
        rec_a = film("A (2001)", "A", 2001, total_size=1_073_741_824, runtime=60,
                     enriched=True)
        rec_b = cache.new_record("B (2002)", "B", 2002, "series")
        rec_b["status"] = "ready"
        out = render_md.render([rec_a, rec_b])
        self.assertIn("2 titles · 1 films · 1 series", out)
        self.assertIn("1.0 GB", out)

    def test_empty_library_still_renders(self):
        out = render_md.render([])
        self.assertIn("# TV Library", out)
        self.assertIn("0 titles", out)

    def test_human_size_and_duration(self):
        self.assertEqual(render_md.human_size(0), "0 B")
        self.assertEqual(render_md.human_size(1536), "2 KB")
        self.assertEqual(render_md.human_duration(109), "1h 49m")
        self.assertEqual(render_md.human_duration(60), "1h")
        self.assertEqual(render_md.human_duration(None), "")


if __name__ == "__main__":
    unittest.main()


class SubtitleListTest(unittest.TestCase):
    def test_a_short_list_is_shown_in_full(self):
        self.assertEqual(render_md.format_subs(["eng", "spa"]), "eng, spa")

    def test_english_is_pulled_to_the_front(self):
        self.assertEqual(render_md.format_subs(["spa", "fre", "eng"]),
                         "eng, spa, fre")

    def test_a_long_list_is_truncated_with_a_count(self):
        codes = ["eng", "ara", "bul", "chi", "cze", "dan", "ger"]
        self.assertEqual(render_md.format_subs(codes), "eng, ara, bul +4")

    def test_duplicates_are_collapsed(self):
        self.assertEqual(render_md.format_subs(["eng", "eng", "spa"]), "eng, spa")

    def test_undetermined_is_dropped_when_real_codes_exist(self):
        self.assertEqual(render_md.format_subs(["und", "eng"]), "eng")

    def test_undetermined_alone_is_still_reported(self):
        self.assertEqual(render_md.format_subs(["und"]), "und")

    def test_no_subtitles_gives_an_empty_string(self):
        self.assertEqual(render_md.format_subs([]), "")

    def test_a_thirty_five_track_rip_stays_one_short_line(self):
        codes = ["eng"] + ["l{}".format(i) for i in range(34)]
        out = render_md.format_subs(codes)
        self.assertLess(len(out), 24)
        self.assertTrue(out.endswith("+32"))


class SpecialsTest(unittest.TestCase):
    def test_specials_are_counted_apart_from_episodes(self):
        rec = cache.new_record("Adventure Time", "Adventure Time", 2010, "series")
        rec.update(status="ready", seasons={"0": 14, "1": 26}, episode_count=26,
                   specials=14, enriched=True)
        out = render_md.render([rec])
        self.assertIn("Season 1 · 26 episodes · 14 specials", out)

    def test_a_show_with_no_specials_says_nothing_about_them(self):
        rec = cache.new_record("Show", "Show", 2020, "series")
        rec.update(status="ready", seasons={"1": 8}, episode_count=8, specials=0)
        out = render_md.render([rec])
        self.assertIn("8 episodes", out)
        self.assertNotIn("specials", out)


class CriticScoresTest(unittest.TestCase):
    def rec(self, ratings):
        r = cache.new_record("k", "The Thing", 1982, "film")
        r.update(status="ready", enriched=True, rating=8.1, genres=["Horror"],
                 ratings=ratings)
        return r

    def test_scores_appear_beside_the_tmdb_rating(self):
        out = render_md.render([self.rec(
            {"rotten_tomatoes": 84, "metacritic": 57, "imdb": 8.2})])
        self.assertIn("★ 8.1", out)
        self.assertIn("RT 84%", out)
        self.assertIn("MC 57", out)
        self.assertIn("IMDb 8.2", out)

    def test_a_title_without_scores_reads_as_before(self):
        out = render_md.render([self.rec({})])
        self.assertIn("★ 8.1", out)
        self.assertNotIn("RT ", out)
