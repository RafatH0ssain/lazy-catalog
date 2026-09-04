import io
import json
import unittest
import urllib.error

from lazycatalog import tmdb


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def opener_for(payloads):
    """Serve canned JSON by URL substring, and record what was asked for."""
    calls = []

    def opener(request, timeout=None):
        url = request.full_url
        calls.append((url, dict(request.headers)))
        for needle, payload in payloads.items():
            if needle in url:
                if isinstance(payload, int):
                    raise urllib.error.HTTPError(url, payload, "err", {}, None)
                return FakeResponse(json.dumps(payload).encode())
        return FakeResponse(b'{"results": []}')

    opener.calls = calls
    return opener


MOVIE_DETAILS = {
    "id": 1091,
    "title": "The Thing",
    "overview": "A research team in Antarctica is hunted.",
    "genres": [{"name": "Horror"}, {"name": "Science Fiction"}],
    "runtime": 109,
    "vote_average": 8.229,
    "vote_count": 9000,
    "release_date": "1982-06-25",
    "poster_path": "/abc.jpg",
    "credits": {
        "crew": [{"job": "Writer", "name": "Bill Lancaster"},
                 {"job": "Director", "name": "John Carpenter"}],
        "cast": [{"name": "Kurt Russell"}, {"name": "Wilford Brimley"}],
    },
}

TV_DETAILS = {
    "id": 15260,
    "name": "Adventure Time",
    "overview": "Finn and Jake.",
    "genres": [{"name": "Animation"}],
    "episode_run_time": [11],
    "vote_average": 8.5,
    "first_air_date": "2010-04-05",
    "created_by": [{"name": "Pendleton Ward"}],
    "credits": {"crew": [], "cast": []},
}


class KeyStyleTest(unittest.TestCase):
    def test_v4_token_goes_in_the_header(self):
        opener = opener_for({"/configuration": {"images": {}}})
        tmdb.Client("eyJhbGci.payload.sig", opener=opener).verify()
        url, headers = opener.calls[0]
        self.assertIn("Authorization", headers)
        self.assertNotIn("api_key", url)

    def test_v3_key_goes_in_the_query(self):
        opener = opener_for({"/configuration": {"images": {}}})
        tmdb.Client("0123456789abcdef0123456789abcdef", opener=opener).verify()
        url, headers = opener.calls[0]
        self.assertIn("api_key=0123456789abcdef", url)
        self.assertNotIn("Authorization", headers)

    def test_empty_key_is_rejected_before_any_request(self):
        with self.assertRaises(tmdb.AuthError):
            tmdb.Client("")

    def test_rejected_key_raises_auth_error(self):
        opener = opener_for({"/configuration": 401})
        with self.assertRaises(tmdb.AuthError):
            tmdb.Client("bad", opener=opener).verify()


class MatchTest(unittest.TestCase):
    def test_exact_title_and_year_beats_a_more_popular_result(self):
        results = [
            {"id": 1, "title": "The Thing", "release_date": "2011-10-14",
             "popularity": 90.0},
            {"id": 2, "title": "The Thing", "release_date": "1982-06-25",
             "popularity": 30.0},
        ]
        best = tmdb._best_match(results, "The Thing", 1982, "film")
        self.assertEqual(best["id"], 2)

    def test_punctuation_and_case_do_not_block_a_match(self):
        results = [{"id": 7, "title": "WALL·E", "release_date": "2008-06-27",
                    "popularity": 1.0}]
        self.assertEqual(tmdb._best_match(results, "Wall E", 2008, "film")["id"], 7)

    def test_a_year_either_side_still_matches(self):
        results = [{"id": 3, "title": "Closer", "release_date": "2004-12-03",
                    "popularity": 5.0}]
        self.assertEqual(tmdb._best_match(results, "Closer", 2005, "film")["id"], 3)

    def test_a_well_known_film_beats_an_obscure_one_a_year_apart(self):
        """TMDB dates Under the Skin to 2014; a 20-vote short holds 2013.

        Release years shift between festival and wide release, so an exact
        year is not worth more than the difference between 3925 votes and 20.
        """
        results = [
            {"id": 1, "title": "Under the Skin", "release_date": "2014-03-14",
             "popularity": 9.45, "vote_count": 3925},
            {"id": 2, "title": "Under the Skin", "release_date": "2013-01-01",
             "popularity": 0.92, "vote_count": 20},
        ]
        self.assertEqual(
            tmdb._best_match(results, "Under the Skin", 2013, "film")["id"], 1)

    def test_a_wrong_year_still_loses_to_the_right_one(self):
        results = [
            {"id": 1, "title": "The Thing", "release_date": "2011-10-14",
             "popularity": 90.0, "vote_count": 5000},
            {"id": 2, "title": "The Thing", "release_date": "1982-06-25",
             "popularity": 30.0, "vote_count": 4000},
        ]
        self.assertEqual(tmdb._best_match(results, "The Thing", 1982, "film")["id"], 2)

    def test_spelled_out_numbers_match_digits(self):
        """A folder says "12 Monkeys"; TMDB says "Twelve Monkeys"."""
        results = [{"id": 63, "title": "Twelve Monkeys",
                    "release_date": "1995-12-29", "popularity": 20.0,
                    "vote_count": 8000}]
        self.assertEqual(tmdb._best_match(results, "12 Monkeys", 1995, "film")["id"], 63)

    def test_digits_match_spelled_out_numbers(self):
        results = [{"id": 1, "title": "8 1/2", "release_date": "1963-02-13",
                    "popularity": 10.0, "vote_count": 1500}]
        self.assertEqual(tmdb._best_match(results, "Eight 1/2", 1963, "film")["id"], 1)

    def test_an_unrelated_title_is_no_match_at_all(self):
        """Better to report nothing than to attach the wrong film's facts."""
        results = [{"id": 9, "title": "Possession", "release_date": "1981-05-25",
                    "popularity": 12.0, "vote_count": 900}]
        self.assertIsNone(tmdb._best_match(results, "Possessor", 2020, "film"))

    def test_no_results_gives_none(self):
        self.assertIsNone(tmdb._best_match([], "Nothing", 2000, "film"))

    def test_search_retries_without_the_year_when_nothing_matched(self):
        opener = opener_for({
            "search/movie&": {"results": []},
            "year=1982": {"results": []},
            "search/movie": {"results": [
                {"id": 1091, "title": "The Thing", "release_date": "1982-06-25",
                 "popularity": 20.0}]},
        })
        client = tmdb.Client("key", opener=opener)
        found = client.search("The Thing", 1982, "film")
        self.assertEqual(found["id"], 1091)
        self.assertGreaterEqual(len(opener.calls), 2)


class NormaliseTest(unittest.TestCase):
    def test_movie_fields(self):
        out = tmdb.normalise(MOVIE_DETAILS, "film")
        self.assertEqual(out["director"], "John Carpenter")
        self.assertEqual(out["runtime"], 109)
        self.assertEqual(out["rating"], 8.2)
        self.assertEqual(out["genres"], ["Horror", "Science Fiction"])
        self.assertEqual(out["year"], 1982)
        self.assertEqual(out["cast"][0], "Kurt Russell")
        self.assertTrue(out["poster_url"].endswith("/abc.jpg"))
        self.assertEqual(out["tmdb_url"], "https://www.themoviedb.org/movie/1091")
        self.assertEqual(out["title"], "The Thing")

    def test_series_uses_creator_and_episode_runtime(self):
        out = tmdb.normalise(TV_DETAILS, "series")
        self.assertEqual(out["title"], "Adventure Time")
        self.assertEqual(out["director"], "Pendleton Ward")
        self.assertEqual(out["runtime"], 11)
        self.assertEqual(out["year"], 2010)
        self.assertIn("/tv/", out["tmdb_url"])

    def test_missing_optional_fields_do_not_crash(self):
        out = tmdb.normalise({"id": 5, "credits": {}}, "film")
        self.assertIsNone(out["runtime"])
        self.assertIsNone(out["rating"])
        self.assertEqual(out["genres"], [])

    def test_lookup_joins_search_and_details(self):
        opener = opener_for({
            "search/movie": {"results": [
                {"id": 1091, "title": "The Thing", "release_date": "1982-06-25",
                 "popularity": 20.0}]},
            "/movie/1091": MOVIE_DETAILS,
        })
        out = tmdb.Client("key", opener=opener).lookup("The Thing", 1982, "film")
        self.assertEqual(out["tmdb_id"], 1091)
        self.assertEqual(out["runtime"], 109)


if __name__ == "__main__":
    unittest.main()
