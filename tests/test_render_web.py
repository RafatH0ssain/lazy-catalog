import json
import re
import tempfile
import unittest
from pathlib import Path

from lazycatalog import cache, config, render_web


def record(key, title, year, **kw):
    rec = cache.new_record(key, title, year, kw.pop("kind", "film"))
    rec["status"] = "ready"
    rec.update(kw)
    return rec


def payload_of(html):
    match = re.search(r"const DATA = (\[.*?\]);\n", html, re.DOTALL)
    # The page escapes < > & as \uXXXX so the blob can't close the script tag;
    # json.loads turns them back into the original characters.
    return json.loads(match.group(1))


class RenderWebTest(unittest.TestCase):
    def test_page_is_self_contained(self):
        html = render_web.render([record("a", "Her", 2013)])
        for token in ("__DATA__", "__TITLE__", "__STATS__", "__FOOTER__"):
            self.assertNotIn(token, html)
        # No CDN, no external stylesheet, no remote font: it must work offline.
        self.assertNotIn("https://fonts.", html)
        self.assertNotIn("<script src=", html)
        self.assertNotIn("cdn.", html)

    def test_data_is_valid_json_with_the_fields_the_page_reads(self):
        html = render_web.render([
            record("a", "Her", 2013, genres=["Drama"], runtime=126, rating=8.0,
                   moods=["warm"], enriched=True, overview="A writer.",
                   director="Spike Jonze", cast=["Joaquin Phoenix"],
                   total_size=2_000_000_000)])
        data = payload_of(html)[0]
        for field in ("key", "title", "sortTitle", "year", "kind", "genres",
                      "moods", "rating", "runtime", "runtimeLabel", "size",
                      "watched", "verified", "overview", "director", "cast",
                      "poster", "tmdb", "tech", "seasonLine", "haystack"):
            self.assertIn(field, data)

    def test_search_haystack_covers_cast_and_mood(self):
        html = render_web.render([
            record("a", "Her", 2013, cast=["Scarlett Johansson"], moods=["melancholy"])])
        haystack = payload_of(html)[0]["haystack"]
        self.assertIn("scarlett", haystack)
        self.assertIn("melancholy", haystack)

    def test_file_runtime_beats_the_tmdb_runtime(self):
        html = render_web.render([
            record("a", "Her", 2013, runtime=126,
                   tech={"runtime_sec": 7000})])   # 117 minutes on disk
        self.assertEqual(payload_of(html)[0]["runtimeLabel"], "1h 57m")

    def test_unenriched_records_are_marked_unverified(self):
        html = render_web.render([record("a", "Her", 2013, enriched=False)])
        self.assertFalse(payload_of(html)[0]["verified"])

    def test_series_get_a_season_line_and_no_film_runtime(self):
        html = render_web.render([
            record("a", "Adventure Time", 2010, kind="series",
                   seasons={"1": 26, "2": 26}, episode_count=52)])
        self.assertEqual(payload_of(html)[0]["seasonLine"], "Seasons 1–2 · 52 episodes")

    def test_a_title_cannot_close_the_script_tag(self):
        """A folder can be named anything, including "</script>"."""
        html = render_web.render([record("a", "<script>alert(1)</script>", 2013)])
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("</script>alert", html)
        # Exactly one script element: the page's own.
        self.assertEqual(html.count("</script>"), 1)
        # And the value survives intact once parsed.
        self.assertEqual(payload_of(html)[0]["title"], "<script>alert(1)</script>")

    def test_ampersands_in_titles_survive(self):
        html = render_web.render([record("a", "Dungeons & Dragons", 2000)])
        self.assertEqual(payload_of(html)[0]["title"], "Dungeons & Dragons")

    def test_empty_library_still_renders_a_page(self):
        html = render_web.render([])
        self.assertIn("<title>", html)
        self.assertEqual(payload_of(html), [])


class WebOutputTest(unittest.TestCase):
    def test_page_is_written_beside_the_posters_so_they_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "TV"
            root.mkdir()
            cfg = dict(config.DEFAULTS, library_path=str(root))
            from lazycatalog import catalog
            target = catalog.write_web(cfg, [record("a", "Her", 2013)])
            self.assertEqual(target.parent, config.state_dir(cfg))
            self.assertTrue(target.is_file())


if __name__ == "__main__":
    unittest.main()
