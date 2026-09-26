import tempfile
import unittest
from pathlib import Path

from lazycatalog import catalog, cli, config, trash
from lazycatalog.cache import Cache


def make(root: Path, rel: str, size: int = 1024) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0" * size)
    return path


class MatchTest(unittest.TestCase):
    RECORDS = [
        {"key": "The Lobster 2015 1080p BluRay x264 DTS-JYK", "title": "The Lobster"},
        {"key": "Her (2013) [1080p]", "title": "Her"},
        {"key": "Game of Thrones Season 1 720p", "title": "Game of Thrones"},
        {"key": "Game.of.Thrones.S04.1080p", "title": "Game of Thrones"},
    ]

    def test_a_partial_title_matches(self):
        got = cli._match_records(self.RECORDS, "lobster")
        self.assertEqual([r["title"] for r in got], ["The Lobster"])

    def test_matching_ignores_case(self):
        self.assertEqual(len(cli._match_records(self.RECORDS, "LOBSTER")), 1)

    def test_the_folder_name_is_searchable_too(self):
        got = cli._match_records(self.RECORDS, "DTS-JYK")
        self.assertEqual([r["title"] for r in got], ["The Lobster"])

    def test_an_ambiguous_word_returns_every_match(self):
        got = cli._match_records(self.RECORDS, "thrones")
        self.assertEqual(len(got), 2)

    def test_an_exact_title_wins_over_a_partial_one(self):
        records = [{"key": "a", "title": "Her"},
                   {"key": "b", "title": "Hereditary"}]
        self.assertEqual([r["title"] for r in cli._match_records(records, "Her")],
                         ["Her"])

    def test_no_match_returns_nothing(self):
        self.assertEqual(cli._match_records(self.RECORDS, "casablanca"), [])


class TrashSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "TV"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_path_outside_the_library_is_refused(self):
        outside = Path(self.tmp.name) / "elsewhere.mkv"
        outside.write_bytes(b"0")
        ok, message = trash.check(outside, self.root)
        self.assertFalse(ok)
        self.assertIn("outside", message)

    def test_the_library_root_itself_is_refused(self):
        ok, message = trash.check(self.root, self.root)
        self.assertFalse(ok)
        self.assertIn("library", message)

    def test_something_already_gone_is_refused(self):
        ok, message = trash.check(self.root / "nope.mkv", self.root)
        self.assertFalse(ok)
        self.assertIn("does not exist", message)

    def test_a_real_item_inside_the_library_passes(self):
        video = make(self.root, "Her (2013)/Her.mkv")
        self.assertEqual(trash.check(video.parent, self.root), (True, ""))

    def test_a_symlink_escaping_the_library_is_refused(self):
        outside = Path(self.tmp.name) / "secret"
        outside.mkdir()
        link = self.root / "innocent"
        link.symlink_to(outside)
        ok, message = trash.check(link, self.root)
        self.assertFalse(ok)
        self.assertIn("outside", message)


class DeleteCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "TV"
        self.root.mkdir()
        make(self.root, "Her (2013) [1080p]/Her.mkv", 2048)
        make(self.root, "Leviticus.2026.1080p.mkv", 4096)
        self.cfg = dict(config.DEFAULTS, library_path=str(self.root))
        catalog.update(self.cfg, settle_rounds=0)
        self.trashed = []
        self.said = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_delete(self, needle, answer="y", force=False):
        return cli.delete_title(
            self.cfg, needle, force=force,
            confirm=lambda prompt: answer,
            trasher=lambda path: (self.trashed.append(path), (True, "ok"))[1],
            report=self.said.append)

    def cache(self):
        return Cache.load(config.state_dir(self.cfg) / catalog.CACHE_NAME)

    def test_a_confirmed_delete_moves_the_folder_and_drops_the_record(self):
        code = self.run_delete("her")
        self.assertEqual(code, 0)
        self.assertEqual(self.trashed[0].name, "Her (2013) [1080p]")
        self.assertIsNone(self.cache().get("Her (2013) [1080p]"))

    def test_a_loose_file_is_deleted_as_the_file_itself(self):
        self.run_delete("leviticus")
        self.assertEqual(self.trashed[0].name, "Leviticus.2026.1080p.mkv")

    def test_answering_no_deletes_nothing(self):
        code = self.run_delete("her", answer="n")
        self.assertEqual(code, 1)
        self.assertEqual(self.trashed, [])
        self.assertIsNotNone(self.cache().get("Her (2013) [1080p]"))

    def test_silence_is_not_consent(self):
        self.run_delete("her", answer="")
        self.assertEqual(self.trashed, [])

    def test_an_ambiguous_name_refuses_and_lists_the_options(self):
        """Sequels are the common case: "blade" must not pick one at random."""
        make(self.root, "Blade Runner (1982)/x.mkv")
        make(self.root, "Blade Runner Black Lotus (2021)/y.mkv")
        catalog.update(self.cfg, settle_rounds=0, force_ready=True)
        code = self.run_delete("blade")
        self.assertEqual(code, 1)
        self.assertEqual(self.trashed, [])
        self.assertTrue(any("Black Lotus" in line for line in self.said))

    def test_an_exact_title_is_not_blocked_by_a_longer_one(self):
        """"Blade Runner" exactly names one film, even though another
        contains it."""
        make(self.root, "Blade Runner (1982)/x.mkv")
        make(self.root, "Blade Runner Black Lotus (2021)/y.mkv")
        catalog.update(self.cfg, settle_rounds=0, force_ready=True)
        code = self.run_delete("Blade Runner")
        self.assertEqual(code, 0)
        self.assertEqual(self.trashed[0].name, "Blade Runner (1982)")

    def test_no_match_says_so_and_deletes_nothing(self):
        code = self.run_delete("casablanca")
        self.assertEqual(code, 1)
        self.assertEqual(self.trashed, [])

    def test_force_skips_the_question(self):
        asked = []
        cli.delete_title(self.cfg, "her", force=True,
                         confirm=lambda p: asked.append(p) or "n",
                         trasher=lambda path: (self.trashed.append(path), (True, "ok"))[1],
                         report=self.said.append)
        self.assertEqual(asked, [])
        self.assertEqual(len(self.trashed), 1)

    def test_the_prompt_states_what_will_go_and_how_big_it_is(self):
        self.run_delete("her")
        prompt = " ".join(self.said)
        self.assertIn("Her", prompt)
        self.assertIn("2 KB", prompt)

    def test_a_failed_move_leaves_the_record_in_place(self):
        code = cli.delete_title(
            self.cfg, "her", force=True, confirm=lambda p: "y",
            trasher=lambda path: (False, "Finder said no"),
            report=self.said.append)
        self.assertEqual(code, 1)
        self.assertIsNotNone(self.cache().get("Her (2013) [1080p]"))

    def test_contents_md_is_rewritten_without_the_deleted_title(self):
        self.run_delete("her")
        text = (self.root / catalog.CONTENTS_NAME).read_text(encoding="utf-8")
        self.assertNotIn("**Her**", text)
        self.assertIn("**Leviticus**", text)


if __name__ == "__main__":
    unittest.main()


class DeleteByKeyTest(unittest.TestCase):
    """The shared mechanism, used by both the CLI and the web endpoint."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "TV"
        self.root.mkdir()
        make(self.root, "Her (2013) [1080p]/Her.mkv", 2048)
        make(self.root, "Dogma (1999)/Dogma.mkv", 1024)
        self.cfg = dict(config.DEFAULTS, library_path=str(self.root))
        catalog.update(self.cfg, settle_rounds=0)
        self.trashed = []

    def tearDown(self):
        self.tmp.cleanup()

    def trasher(self, path):
        self.trashed.append(path)
        return True, "Moved to Trash"

    def cache(self):
        return Cache.load(config.state_dir(self.cfg) / catalog.CACHE_NAME)

    def test_an_exact_key_is_deleted_without_any_matching(self):
        ok, message = catalog.delete_by_key(
            self.cfg, "Her (2013) [1080p]", trasher=self.trasher)
        self.assertTrue(ok)
        self.assertIn("Her", message)
        self.assertIsNone(self.cache().get("Her (2013) [1080p]"))

    def test_an_unknown_key_is_refused(self):
        ok, message = catalog.delete_by_key(self.cfg, "Nope", trasher=self.trasher)
        self.assertFalse(ok)
        self.assertEqual(self.trashed, [])

    def test_a_key_escaping_the_library_is_refused(self):
        ok, message = catalog.delete_by_key(
            self.cfg, "../../etc", trasher=self.trasher)
        self.assertFalse(ok)
        self.assertEqual(self.trashed, [])

    def test_a_failed_move_keeps_the_record(self):
        ok, _ = catalog.delete_by_key(
            self.cfg, "Dogma (1999)", trasher=lambda p: (False, "Finder refused"))
        self.assertFalse(ok)
        self.assertIsNotNone(self.cache().get("Dogma (1999)"))

    def test_both_views_are_rewritten_after_a_delete(self):
        catalog.delete_by_key(self.cfg, "Her (2013) [1080p]", trasher=self.trasher)
        contents = (self.root / catalog.CONTENTS_NAME).read_text(encoding="utf-8")
        page = (config.state_dir(self.cfg) / catalog.WEB_NAME).read_text(encoding="utf-8")
        self.assertNotIn("**Her**", contents)
        self.assertNotIn('"Her (2013) [1080p]"', page)
