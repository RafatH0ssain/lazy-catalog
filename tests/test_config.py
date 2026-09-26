import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from lazycatalog import config


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.json"
        os.environ[config.CONFIG_ENV] = str(self.path)

    def tearDown(self):
        os.environ.pop(config.CONFIG_ENV, None)
        self.tmp.cleanup()

    def test_missing_config_names_the_init_command(self):
        with self.assertRaises(config.ConfigError) as ctx:
            config.load()
        self.assertIn("lazy-catalog init", str(ctx.exception))

    def test_save_then_load_roundtrips(self):
        config.save({"tmdb_api_key": "abc123", "library_path": "~/TV"})
        cfg = config.load()
        self.assertEqual(cfg["tmdb_api_key"], "abc123")

    def test_defaults_fill_in_absent_keys(self):
        config.save({"tmdb_api_key": "abc123"})
        cfg = config.load()
        self.assertEqual(cfg["ollama_host"], "http://localhost:11434")
        self.assertEqual(cfg["subtitle_languages"], ["en"])
        self.assertEqual(cfg["suggest_model"], "gemma4:12b")
        self.assertEqual(cfg["ollama_model"], "gemma3:12b")

    def test_saved_config_is_not_readable_by_others(self):
        config.save({"tmdb_api_key": "secret"})
        mode = stat.S_IMODE(self.path.stat().st_mode)
        self.assertEqual(mode, 0o600, "config holds an API key")

    def test_bad_json_reports_the_path(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(config.ConfigError) as ctx:
            config.load()
        self.assertIn(str(self.path), str(ctx.exception))

    def test_library_path_is_expanded(self):
        config.save({"library_path": "~/TV"})
        cfg = config.load()
        self.assertTrue(str(config.library_path(cfg)).startswith(str(Path.home())))
        self.assertEqual(config.state_dir(cfg).name, ".lazy")


if __name__ == "__main__":
    unittest.main()


class KeyShapeTest(unittest.TestCase):
    """TMDB and OMDb keys look nothing alike; say so instead of just failing."""

    def shape(self, key):
        from lazycatalog import cli
        return cli._key_shape(key)

    def test_a_32_character_hex_key_is_tmdb_v3(self):
        self.assertEqual(self.shape("0123456789abcdef0123456789abcdef"), "tmdb")

    def test_a_jwt_is_tmdb_v4(self):
        self.assertEqual(self.shape("eyJhbGciOi.payload.signature"), "tmdb")

    def test_an_eight_character_key_is_omdb(self):
        self.assertEqual(self.shape("3271bb3b"), "omdb")

    def test_an_eight_character_alphanumeric_key_is_omdb(self):
        self.assertEqual(self.shape("ab12cd34"), "omdb")

    def test_anything_else_is_unknown(self):
        self.assertEqual(self.shape("hello"), "unknown")
        self.assertEqual(self.shape(""), "unknown")
