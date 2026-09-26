import os
import tempfile
import unittest
from pathlib import Path

from lazycatalog import catalog, config, render_md
from lazycatalog.cache import Cache


def make(root: Path, rel: str, size: int = 1024) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0" * size)
    return path


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "TV"
        self.root.mkdir()
        self.cfg = dict(config.DEFAULTS, library_path=str(self.root))
        make(self.root, "Her (2013) [1080p]/Her.mp4")
        make(self.root, "Dogma (1999)/Dogma.mkv")

    def tearDown(self):
        self.tmp.cleanup()

    def run_update(self, **kw):
        kw.setdefault("settle_rounds", 0)
        return catalog.update(self.cfg, **kw)

    def contents(self) -> str:
        return (self.root / catalog.CONTENTS_NAME).read_text(encoding="utf-8")

    def cache(self) -> Cache:
        return Cache.load(config.state_dir(self.cfg) / catalog.CACHE_NAME)

    # -- first import --------------------------------------------------

    def test_first_run_publishes_immediately(self):
        result = self.run_update()
        self.assertEqual(result["total"], 2)
        self.assertIn("**Her** (2013)", self.contents())
        self.assertIn("**Dogma** (1999)", self.contents())

    def test_state_lives_beside_the_library_not_inside_the_listing(self):
        self.run_update()
        self.assertTrue((self.root / ".lazy" / "cache.json").is_file())
        self.assertNotIn(".lazy", self.contents())

    # -- settling ------------------------------------------------------

    def test_a_folder_added_later_waits_one_pass_before_publishing(self):
        self.run_update()
        make(self.root, "Closer (2004)/Closer.mkv")

        first = self.run_update()
        self.assertIn("Closer (2004)", first["pending"])
        self.assertNotIn("**Closer**", self.contents())

        second = self.run_update()
        self.assertEqual(second["pending"], [])
        self.assertIn("**Closer**", self.contents())

    def test_a_growing_download_stays_pending(self):
        self.run_update()
        make(self.root, "Growing (2021)/film.mkv", 100)
        self.run_update()
        make(self.root, "Growing (2021)/film.mkv", 900)   # still downloading
        result = self.run_update()
        self.assertIn("Growing (2021)", result["pending"])

    def test_incomplete_marker_blocks_publication_even_when_size_is_stable(self):
        self.run_update()
        make(self.root, "Torrenting (2022)/film.mkv.part", 100)
        self.run_update()
        result = self.run_update()
        self.assertIn("Torrenting (2022)", result["pending"])

    def test_now_publishes_without_waiting(self):
        self.run_update()
        make(self.root, "Closer (2004)/Closer.mkv")
        result = self.run_update(force_ready=True)
        self.assertEqual(result["pending"], [])
        self.assertIn("**Closer**", self.contents())

    # -- deletion and watched state -----------------------------------

    def test_deleting_a_folder_removes_it_from_the_file(self):
        self.run_update()
        for child in (self.root / "Dogma (1999)").iterdir():
            child.unlink()
        (self.root / "Dogma (1999)").rmdir()
        result = self.run_update()
        self.assertEqual(result["removed"], ["Dogma (1999)"])
        self.assertNotIn("**Dogma**", self.contents())

    def test_ticking_a_box_survives_the_next_run(self):
        self.run_update()
        text = self.contents().replace(
            "- [ ] **Her**", "- [x] **Her**")
        (self.root / catalog.CONTENTS_NAME).write_text(text, encoding="utf-8")

        self.run_update()
        state = render_md.read_watched(self.contents())
        self.assertTrue(state["Her (2013) [1080p]"])
        self.assertFalse(state["Dogma (1999)"])

    def test_rebuild_keeps_watched_state(self):
        self.run_update()
        text = self.contents().replace("- [ ] **Her**", "- [x] **Her**")
        (self.root / catalog.CONTENTS_NAME).write_text(text, encoding="utf-8")

        catalog.rebuild(self.cfg)
        self.assertTrue(render_md.read_watched(self.contents())["Her (2013) [1080p]"])

    # -- enrichment ----------------------------------------------------

    def test_enrich_runs_once_per_title_and_not_again(self):
        seen = []

        def enrich(record, entry):
            seen.append(record["key"])
            record["enriched"] = True

        self.run_update(enrich=enrich)
        self.assertEqual(sorted(seen), ["Dogma (1999)", "Her (2013) [1080p]"])

        seen.clear()
        self.run_update(enrich=enrich)
        self.assertEqual(seen, [])

    def test_pending_titles_are_not_enriched(self):
        self.run_update()
        make(self.root, "Closer (2004)/Closer.mkv")
        seen = []
        self.run_update(enrich=lambda r, e: seen.append(r["key"]))
        self.assertNotIn("Closer (2004)", seen)

    def test_local_facts_refresh_even_for_settled_titles(self):
        self.run_update()
        make(self.root, "Her (2013) [1080p]/Her.mp4", 5000)
        self.run_update()
        self.assertEqual(self.cache().get("Her (2013) [1080p]")["total_size"], 5000)

    # -- loose files ---------------------------------------------------

    def test_a_loose_file_reaches_contents_md(self):
        make(self.root, "Coyote.vs.Acme.2026.1080p.HEVC.x265.RMTeam.mkv")
        self.run_update()
        self.assertIn("**Coyote vs Acme** (2026)", self.contents())

    def test_a_loose_file_records_a_playable_path(self):
        make(self.root, "Leviticus.2026.1080p.mkv")
        self.run_update()
        record = self.cache().get("Leviticus.2026.1080p.mkv")
        self.assertEqual(record["video"], "Leviticus.2026.1080p.mkv")

    def test_deleting_a_loose_file_removes_it(self):
        make(self.root, "Leviticus.2026.1080p.mkv")
        self.run_update()
        (self.root / "Leviticus.2026.1080p.mkv").unlink()
        result = self.run_update()
        self.assertEqual(result["removed"], ["Leviticus.2026.1080p.mkv"])

    def test_a_loose_file_still_being_written_stays_pending(self):
        self.run_update()
        make(self.root, "Leviticus.2026.1080p.mkv", 100)
        self.run_update()
        make(self.root, "Leviticus.2026.1080p.mkv", 900)   # still growing
        result = self.run_update()
        self.assertIn("Leviticus.2026.1080p.mkv", result["pending"])

    def test_a_finished_loose_file_publishes_on_the_next_pass(self):
        self.run_update()
        make(self.root, "Leviticus.2026.1080p.mkv", 500)
        self.run_update()
        result = self.run_update()
        self.assertEqual(result["pending"], [])
        self.assertIn("**Leviticus**", self.contents())

    def test_missing_library_raises(self):
        cfg = dict(self.cfg, library_path=str(self.root / "nope"))
        with self.assertRaises(FileNotFoundError):
            catalog.update(cfg, settle_rounds=0)


if __name__ == "__main__":
    unittest.main()
