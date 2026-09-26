import unittest
import urllib.error

from lazycatalog import omdb
from tests.test_tmdb import opener_for

FULL = {
    "Title": "The Thing", "Response": "True", "imdbRating": "8.2",
    "Metascore": "57",
    "Ratings": [
        {"Source": "Internet Movie Database", "Value": "8.2/10"},
        {"Source": "Rotten Tomatoes", "Value": "84%"},
        {"Source": "Metacritic", "Value": "57/100"},
    ],
}


class RatingsTest(unittest.TestCase):
    def client(self, payload):
        return omdb.Client("key", opener=opener_for({"omdbapi.com": payload}))

    def test_all_three_scores_are_read(self):
        got = self.client(FULL).ratings("tt0084787")
        self.assertEqual(got["rotten_tomatoes"], 84)
        self.assertEqual(got["metacritic"], 57)
        self.assertEqual(got["imdb"], 8.2)

    def test_a_film_with_only_an_imdb_score_returns_just_that(self):
        got = self.client({"Response": "True", "imdbRating": "6.4",
                           "Ratings": [{"Source": "Internet Movie Database",
                                        "Value": "6.4/10"}]}).ratings("tt1")
        self.assertEqual(got, {"imdb": 6.4})

    def test_an_unknown_film_gives_nothing_rather_than_raising(self):
        got = self.client({"Response": "False", "Error": "Movie not found!"})
        self.assertEqual(got.ratings("tt0"), {})

    def test_n_a_values_are_not_recorded_as_zero(self):
        got = self.client({"Response": "True", "imdbRating": "N/A",
                           "Metascore": "N/A",
                           "Ratings": []}).ratings("tt1")
        self.assertEqual(got, {})

    def test_a_bad_key_is_reported_clearly(self):
        client = self.client({"Response": "False", "Error": "Invalid API key!"})
        with self.assertRaises(omdb.AuthError):
            client.ratings("tt0084787")

    def test_an_empty_key_is_refused_before_any_request(self):
        with self.assertRaises(omdb.AuthError):
            omdb.Client("")

    def test_a_network_failure_is_not_fatal(self):
        def boom(request, timeout=None):
            raise urllib.error.URLError("offline")
        self.assertEqual(omdb.Client("k", opener=boom).ratings("tt1"), {})

    def test_the_imdb_id_is_what_gets_queried(self):
        opener = opener_for({"omdbapi.com": FULL})
        omdb.Client("key", opener=opener).ratings("tt0084787")
        self.assertIn("i=tt0084787", opener.calls[0][0])

    def test_an_absent_imdb_id_skips_the_call_entirely(self):
        opener = opener_for({"omdbapi.com": FULL})
        self.assertEqual(omdb.Client("key", opener=opener).ratings(""), {})
        self.assertEqual(opener.calls, [])

    def test_verify_accepts_a_working_key(self):
        self.assertTrue(self.client(FULL).verify())


class FormatTest(unittest.TestCase):
    def test_scores_render_compactly(self):
        self.assertEqual(
            omdb.summary({"rotten_tomatoes": 84, "metacritic": 57, "imdb": 8.2}),
            "RT 84% · MC 57 · IMDb 8.2")

    def test_missing_scores_are_left_out(self):
        self.assertEqual(omdb.summary({"imdb": 6.4}), "IMDb 6.4")

    def test_nothing_gives_an_empty_string(self):
        self.assertEqual(omdb.summary({}), "")


if __name__ == "__main__":
    unittest.main()
