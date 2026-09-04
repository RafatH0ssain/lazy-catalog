import io
import json
import unittest
from datetime import datetime

from lazycatalog import cache, render_md, suggest, tmdb
from tests.test_tmdb import FakeResponse, opener_for


def responder(text):
    def opener(request, timeout=None):
        return FakeResponse(json.dumps({"response": text}).encode())
    return opener


def owned(key, title, year, **kw):
    rec = cache.new_record(key, title, year, "film")
    rec["status"] = "ready"
    rec.update(kw)
    return rec


LIBRARY = [
    owned("a", "The Lobster", 2015, genres=["Comedy"], moods=["deadpan"],
          tmdb_id=264644, rating=7.0, watched=True),
    owned("b", "Her", 2013, genres=["Romance"], moods=["melancholy"],
          tmdb_id=152601, rating=7.8),
]


def details(tmdb_id, title, year="2008-10-24", **kw):
    payload = {"id": tmdb_id, "title": title, "release_date": year,
               "overview": kw.get("overview", "A film."),
               "genres": [{"name": g} for g in kw.get("genres", ["Drama"])],
               "runtime": kw.get("runtime", 100),
               "vote_average": kw.get("rating", 7.5),
               "credits": {"crew": [{"job": "Director", "name": kw.get("director", "D")}],
                           "cast": []}}
    return payload


class ProfileTest(unittest.TestCase):
    def test_watched_titles_come_first_and_are_marked(self):
        profile = suggest.taste_profile(LIBRARY)
        self.assertTrue(profile.startswith("- The Lobster"))
        self.assertIn("WATCHED", profile.splitlines()[0])

    def test_prompt_lists_previous_suggestions_to_avoid(self):
        prompt = suggest.build_prompt(LIBRARY, "bleak", 5, avoid=["Synecdoche"])
        self.assertIn("do not repeat", prompt)
        self.assertIn("Synecdoche", prompt)

    def test_prompt_without_a_request_still_asks_for_something(self):
        self.assertIn("anything I'd probably like",
                      suggest.build_prompt(LIBRARY, "", 5))


class ParseTest(unittest.TestCase):
    def test_reads_title_year_and_reason(self):
        got = suggest.parse(
            '{"suggestions":[{"title":"Dogtooth","year":2009,"why":"Like The Lobster."}]}')
        self.assertEqual(got[0]["title"], "Dogtooth")
        self.assertEqual(got[0]["year"], 2009)

    def test_an_impossible_year_is_discarded_but_the_title_kept(self):
        got = suggest.parse('{"suggestions":[{"title":"X","year":3400,"why":""}]}')
        self.assertEqual(got[0]["title"], "X")
        self.assertIsNone(got[0]["year"])

    def test_entries_without_a_title_are_skipped(self):
        got = suggest.parse('{"suggestions":[{"title":"","year":2000},{"title":"Y"}]}')
        self.assertEqual([g["title"] for g in got], ["Y"])

    def test_a_bare_json_array_is_accepted(self):
        """gemma3 answers with a list; mistral-small answers with an object."""
        got = suggest.parse(
            '[{"title": "Brazil", "year": 1985, "why": "Like Donnie Darko."}]')
        self.assertEqual(got[0]["title"], "Brazil")
        self.assertEqual(got[0]["year"], 1985)

    def test_a_fenced_code_block_is_accepted(self):
        got = suggest.parse(
            '```json\n[{"title": "Safe", "year": 1995, "why": "Dread."}]\n```')
        self.assertEqual(got[0]["title"], "Safe")

    def test_an_object_with_a_differently_named_list_is_accepted(self):
        got = suggest.parse('{"movies":[{"title":"Possessor","year":2020}]}')
        self.assertEqual(got[0]["title"], "Possessor")

    def test_a_single_bare_object_is_accepted(self):
        got = suggest.parse('{"title":"Brazil","year":1985,"why":"x"}')
        self.assertEqual(got[0]["title"], "Brazil")

    def test_reason_key_alias_is_read(self):
        got = suggest.parse('[{"title":"X","year":2000,"reason":"because"}]')
        self.assertEqual(got[0]["why"], "because")

    def test_unparseable_output_gives_nothing(self):
        self.assertEqual(suggest.parse("I recommend Dogtooth."), [])


class VerifyTest(unittest.TestCase):
    def client(self, payloads):
        return tmdb.Client("key", opener=opener_for(payloads))

    def test_a_film_tmdb_cannot_find_is_treated_as_invented(self):
        client = self.client({"search/movie": {"results": []}})
        accepted, dropped = suggest.verify(
            client, [{"title": "The Silent Orchard", "year": 2011, "why": ""}],
            set(), set(), set())
        self.assertEqual(accepted, [])
        self.assertIn("no such film", dropped[0][1])

    def test_a_verified_film_carries_tmdb_facts_not_the_models(self):
        client = self.client({
            "search/movie": {"results": [{"id": 1381, "title": "Synecdoche, New York",
                                          "release_date": "2008-10-24",
                                          "popularity": 9.0}]},
            "/movie/1381": details(1381, "Synecdoche, New York",
                                   genres=["Drama"], runtime=124, rating=7.3,
                                   director="Charlie Kaufman")})
        accepted, _ = suggest.verify(
            client, [{"title": "Synecdoche New York", "year": 2009,
                      "why": "Because you own Her."}],
            set(), set(), set())
        entry = accepted[0]
        self.assertEqual(entry["tmdb_id"], 1381)
        self.assertEqual(entry["year"], 2008)          # TMDB wins over the model's 2009
        self.assertEqual(entry["runtime"], 124)
        self.assertEqual(entry["director"], "Charlie Kaufman")
        self.assertEqual(entry["why"], "Because you own Her.")

    def test_a_film_already_owned_is_dropped_by_id(self):
        client = self.client({
            "search/movie": {"results": [{"id": 152601, "title": "Her",
                                          "release_date": "2013-01-01",
                                          "popularity": 9.0}]},
            "/movie/152601": details(152601, "Her", "2013-01-01")})
        accepted, dropped = suggest.verify(
            client, [{"title": "Her", "year": 2013, "why": ""}],
            {"152601"}, set(), set())
        self.assertEqual(accepted, [])
        self.assertIn("already in your library", dropped[0][1])

    def test_a_film_already_owned_under_another_folder_name_is_dropped(self):
        client = self.client({
            "search/movie": {"results": [{"id": 999, "title": "The Lobster",
                                          "release_date": "2015-01-01",
                                          "popularity": 9.0}]},
            "/movie/999": details(999, "The Lobster", "2015-01-01")})
        accepted, dropped = suggest.verify(
            client, [{"title": "The Lobster", "year": 2015, "why": ""}],
            set(), {"the lobster"}, set())
        self.assertEqual(accepted, [])

    def test_something_already_on_the_watchlist_is_not_suggested_again(self):
        client = self.client({
            "search/movie": {"results": [{"id": 1381, "title": "Synecdoche",
                                          "release_date": "2008-01-01",
                                          "popularity": 9.0}]},
            "/movie/1381": details(1381, "Synecdoche")})
        accepted, dropped = suggest.verify(
            client, [{"title": "Synecdoche", "year": 2008, "why": ""}],
            set(), set(), {"1381"})
        self.assertEqual(accepted, [])
        self.assertIn("watchlist", dropped[0][1])

    def test_the_same_film_twice_in_one_reply_is_only_kept_once(self):
        client = self.client({
            "search/movie": {"results": [{"id": 1381, "title": "Synecdoche",
                                          "release_date": "2008-01-01",
                                          "popularity": 9.0}]},
            "/movie/1381": details(1381, "Synecdoche")})
        accepted, _ = suggest.verify(
            client, [{"title": "Synecdoche", "year": 2008, "why": "a"},
                     {"title": "Synecdoche", "year": 2008, "why": "b"}],
            set(), set(), set())
        self.assertEqual(len(accepted), 1)


class ProposeTest(unittest.TestCase):
    def test_an_empty_library_says_so_before_calling_anything(self):
        _, _, error = suggest.propose(
            [], "", tmdb.Client("k", opener=opener_for({})), "http://x", "m")
        self.assertIn("lazy-catalog update", error)

    def test_a_model_that_answers_in_prose_is_reported_not_guessed_at(self):
        _, _, error = suggest.propose(
            LIBRARY, "", tmdb.Client("k", opener=opener_for({})), "http://x", "m",
            opener=responder("You should watch Dogtooth."))
        self.assertIn("didn't return a usable answer", error)


class WatchlistFileTest(unittest.TestCase):
    def entry(self, **kw):
        base = {"tmdb_id": 1381, "title": "Synecdoche, New York", "year": 2008,
                "genres": ["Drama"], "runtime": 124, "rating": 7.3,
                "why": "Because you own Anomalisa.", "overview": "A director.",
                "director": "Charlie Kaufman", "tmdb_url": "https://x",
                "watched": False}
        base.update(kw)
        return base

    def test_the_file_shows_the_reason_and_the_facts(self):
        out = render_md.render_watchlist([self.entry()],
                                         now=datetime(2026, 9, 4, 12, 0))
        self.assertIn("**Synecdoche, New York** (2008)", out)
        self.assertIn("2h 4m", out)
        self.assertIn("★ 7.3", out)
        self.assertIn("Because you own Anomalisa.", out)

    def test_ticking_one_off_survives_a_rerun(self):
        out = render_md.render_watchlist([self.entry()]).replace("- [ ]", "- [x]")
        self.assertEqual(render_md.read_watched(out)["tmdb:1381"], True)

    def test_an_empty_watchlist_explains_how_to_fill_it(self):
        self.assertIn("lazy-suggest", render_md.render_watchlist([]))

    def test_seen_entries_are_counted(self):
        out = render_md.render_watchlist(
            [self.entry(), self.entry(tmdb_id=2, title="B", watched=True)])
        self.assertIn("2 suggestions · 1 seen", out)


class CacheWatchlistTest(unittest.TestCase):
    def test_suggestions_are_keyed_by_tmdb_id(self):
        c = cache.Cache(path=None if False else __import__("pathlib").Path("/tmp/x.json"))
        c.add_suggestion({"tmdb_id": 1381, "title": "S"})
        c.add_suggestion({"tmdb_id": 1381, "title": "S again"})
        self.assertEqual(len(c.watchlist_entries()), 1)
        self.assertEqual(c.suggested_ids(), {"1381"})

    def test_owned_ids_come_from_enriched_library_records(self):
        c = cache.Cache(__import__("pathlib").Path("/tmp/y.json"))
        rec = cache.new_record("k", "Her", 2013, "film")
        rec["tmdb_id"] = 152601
        c.put(rec)
        self.assertEqual(c.owned_ids(), {"152601"})


if __name__ == "__main__":
    unittest.main()
