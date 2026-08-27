import io
import json
import unittest

from lazycatalog import cache, pick


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def responder(text):
    def opener(request, timeout=None):
        return FakeResponse(json.dumps({"response": text}).encode())
    return opener


def record(key, title, year, **kw):
    rec = cache.new_record(key, title, year, kw.pop("kind", "film"))
    rec["status"] = "ready"
    rec.update(kw)
    return rec


LIBRARY = [
    record("a", "Dogma", 1999, runtime=130, genres=["Comedy"], moods=["funny"]),
    record("b", "The Thing", 1982, runtime=109, genres=["Horror"], rating=8.2),
    record("c", "Adventure Time", 2010, kind="series", episode_count=112),
]


class PromptTest(unittest.TestCase):
    def test_every_title_is_numbered_for_the_model(self):
        lines = pick.catalog_lines(LIBRARY)
        self.assertTrue(lines[0].startswith("1. Dogma (1999)"))
        self.assertIn("[130 min]", lines[0])
        self.assertIn("[series, 112 eps]", lines[2])

    def test_watched_is_stated_so_the_model_can_avoid_it(self):
        seen = record("d", "Her", 2013, watched=True)
        self.assertIn("already watched", pick.catalog_lines([seen])[0])


class ParseTest(unittest.TestCase):
    def call(self, text, records=LIBRARY):
        return pick.choose(records, "something funny", "http://x", "m",
                           opener=responder(text))

    def test_happy_path(self):
        result, error = self.call(
            '{"picks":[{"n":1,"tier":"S","why":"Quotable and light."}],'
            '"honorable":[{"n":2,"why":"Not funny but great."}],'
            '"skipped":[{"n":3,"why":"A series, not a film."}]}')
        self.assertIsNone(error)
        self.assertEqual(result["picks"][0]["n"], 1)
        self.assertEqual(result["honorable"][0]["n"], 2)
        self.assertEqual(result["skipped"][0]["n"], 3)

    def test_a_number_outside_the_library_is_dropped(self):
        result, _ = self.call(
            '{"picks":[{"n":1,"tier":"S","why":"ok"},{"n":99,"tier":"A","why":"made up"}]}')
        self.assertEqual([p["n"] for p in result["picks"]], [1])

    def test_duplicate_picks_are_collapsed(self):
        result, _ = self.call(
            '{"picks":[{"n":2,"tier":"S","why":"a"},{"n":2,"tier":"A","why":"b"}]}')
        self.assertEqual(len(result["picks"]), 1)

    def test_tiers_sort_s_before_a_before_b(self):
        result, _ = self.call(
            '{"picks":[{"n":1,"tier":"B","why":"c"},{"n":2,"tier":"S","why":"a"},'
            '{"n":3,"tier":"A","why":"b"}]}')
        self.assertEqual([p["tier"] for p in result["picks"]], ["S", "A", "B"])

    def test_unknown_tier_falls_back_to_b(self):
        result, _ = self.call('{"picks":[{"n":1,"tier":"gold","why":"x"}]}')
        self.assertEqual(result["picks"][0]["tier"], "B")

    def test_prose_around_the_json_is_tolerated(self):
        result, error = self.call(
            'Sure!\n{"picks":[{"n":1,"tier":"S","why":"ok"}]}\nHope that helps.')
        self.assertIsNone(error)

    def test_unusable_reply_reports_an_error_rather_than_guessing(self):
        result, error = self.call("I would watch something good.")
        self.assertIsNone(result)
        self.assertIn("didn't return a usable answer", error)

    def test_all_picks_invalid_is_an_error_not_an_empty_list(self):
        result, error = self.call('{"picks":[{"n":50,"tier":"S","why":"x"}]}')
        self.assertIsNone(result)

    def test_empty_library_says_so(self):
        result, error = pick.choose([], "anything", "http://x", "m")
        self.assertIn("lazy-catalog update", error)


class FormatTest(unittest.TestCase):
    def test_output_names_titles_and_tiers(self):
        result = {"picks": [{"n": 1, "tier": "S", "why": "Quotable."}],
                  "honorable": [{"n": 2, "why": "Also good."}],
                  "skipped": [{"n": 3, "why": "Series."}]}
        out = pick.format_result(result, LIBRARY, colour=False)
        self.assertIn("S  Dogma (1999) · 2h 10m", out)
        self.assertIn("Quotable.", out)
        self.assertIn("Honorable mentions", out)
        self.assertIn("Ruled out: Adventure Time", out)

    def test_series_show_episode_counts_not_runtimes(self):
        result = {"picks": [{"n": 3, "tier": "S", "why": ""}],
                  "honorable": [], "skipped": []}
        out = pick.format_result(result, LIBRARY, colour=False)
        self.assertIn("112 eps", out)


if __name__ == "__main__":
    unittest.main()
