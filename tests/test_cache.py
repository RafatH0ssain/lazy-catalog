import json
import tempfile
import unittest
from pathlib import Path

from lazycatalog.cache import Cache, new_record


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "cache.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_gives_an_empty_cache(self):
        self.assertEqual(len(Cache.load(self.path)), 0)

    def test_roundtrip(self):
        cache = Cache.load(self.path)
        cache.put(new_record("Her (2013)", "Her", 2013, "film"))
        cache.save()
        self.assertEqual(Cache.load(self.path).get("Her (2013)")["title"], "Her")

    def test_new_records_start_pending_and_unwatched(self):
        record = new_record("X", "X", 2000, "film")
        self.assertEqual(record["status"], "pending")
        self.assertFalse(record["watched"])
        self.assertFalse(record["enriched"])

    def test_ready_filters_out_pending(self):
        cache = Cache.load(self.path)
        cache.put(new_record("a", "A", 2000, "film"))
        ready = new_record("b", "B", 2001, "film")
        ready["status"] = "ready"
        cache.put(ready)
        self.assertEqual([r["key"] for r in cache.ready()], ["b"])

    def test_sync_drops_records_whose_folder_is_gone(self):
        cache = Cache.load(self.path)
        cache.put(new_record("gone", "Gone", 2000, "film"))
        cache.put(new_record("here", "Here", 2000, "film"))
        removed = cache.sync_keys(["here"])
        self.assertEqual(removed, ["gone"])
        self.assertEqual(cache.keys(), ["here"])

    def test_corrupt_cache_is_set_aside_not_lost(self):
        self.path.write_text("{{{ not json", encoding="utf-8")
        cache = Cache.load(self.path)
        self.assertEqual(len(cache), 0)
        self.assertTrue(self.path.with_suffix(".json.corrupt").is_file())

    def test_save_is_atomic_and_leaves_no_temp_file(self):
        cache = Cache.load(self.path)
        cache.put(new_record("a", "A", 2000, "film"))
        cache.save()
        self.assertFalse(self.path.with_suffix(".json.tmp").exists())
        json.loads(self.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
