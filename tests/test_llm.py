import io
import json
import unittest
import urllib.error

from lazycatalog import llm


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


def failing(request, timeout=None):
    raise urllib.error.URLError("connection refused")


class MoodTagTest(unittest.TestCase):
    def call(self, text):
        return llm.mood_tags("http://x", "m", "Her", 2013, ["Drama"], "A man...",
                             opener=responder(text))

    def test_plain_comma_list(self):
        self.assertEqual(self.call("melancholy, warm, slow burn"),
                         ["melancholy", "warm", "slow burn"])

    def test_strips_a_chatty_preamble(self):
        self.assertEqual(
            self.call("Sure! Here are the tags:\nlonely, tender, sad"),
            ["lonely", "tender", "sad"])

    def test_drops_punctuation_and_caps(self):
        self.assertEqual(self.call("Bleak., TENSE!"), ["bleak", "tense"])

    def test_caps_at_four_tags(self):
        self.assertEqual(len(self.call("a1, b2, c3, d4, e5, f6")), 4)

    def test_ollama_being_down_is_not_fatal(self):
        self.assertEqual(
            llm.mood_tags("http://x", "m", "Her", 2013, [], "", opener=failing), [])


class CleanNameTest(unittest.TestCase):
    def test_extracts_json(self):
        out = llm.clean_name("http://x", "m", "xX_thing_Xx",
                             opener=responder('{"title": "The Thing", "year": 1982}'))
        self.assertEqual(out, ("The Thing", 1982))

    def test_tolerates_surrounding_prose(self):
        out = llm.clean_name("http://x", "m", "junk",
                             opener=responder('Here you go: {"title": "Dogma", "year": null} done'))
        self.assertEqual(out, ("Dogma", None))

    def test_absurd_year_is_discarded_but_title_kept(self):
        out = llm.clean_name("http://x", "m", "junk",
                             opener=responder('{"title": "Dogma", "year": 12}'))
        self.assertEqual(out, ("Dogma", None))

    def test_unparseable_reply_gives_none(self):
        self.assertIsNone(
            llm.clean_name("http://x", "m", "junk", opener=responder("no idea")))

    def test_empty_title_gives_none(self):
        self.assertIsNone(
            llm.clean_name("http://x", "m", "junk",
                           opener=responder('{"title": "", "year": 1999}')))


class ListModelsTest(unittest.TestCase):
    def test_returns_names(self):
        def opener(request, timeout=None):
            return FakeResponse(json.dumps(
                {"models": [{"name": "gemma3:12b"}, {"name": "camus:latest"}]}).encode())
        self.assertEqual(llm.list_models("http://x", opener=opener),
                         ["gemma3:12b", "camus:latest"])

    def test_ollama_down_gives_an_empty_list(self):
        self.assertEqual(llm.list_models("http://x", opener=failing), [])


if __name__ == "__main__":
    unittest.main()


class KeepAliveTest(unittest.TestCase):
    """A model left resident after an unattended run makes the machine slow."""

    def capture(self):
        sent = {}

        def opener(request, timeout=None):
            sent.update(json.loads(request.data.decode()))
            return FakeResponse(json.dumps({"response": "ok"}).encode())

        return sent, opener

    def test_every_call_asks_ollama_to_release_the_model(self):
        sent, opener = self.capture()
        llm.generate("http://x", "m", "hi", opener=opener)
        self.assertEqual(sent["keep_alive"], llm.KEEP_ALIVE)

    def test_the_hold_is_short_but_long_enough_to_batch(self):
        self.assertEqual(llm.KEEP_ALIVE, "60s")

    def test_mood_tagging_releases_it_too(self):
        sent, opener = self.capture()
        llm.mood_tags("http://x", "m", "Her", 2013, [], "", opener=opener)
        self.assertIn("keep_alive", sent)


class ThinkingTest(unittest.TestCase):
    """Reasoning models burn most of their output on tokens we discard."""

    def capture(self):
        sent = {}

        def opener(request, timeout=None):
            sent.update(json.loads(request.data.decode()))
            return FakeResponse(json.dumps({"response": "ok"}).encode())

        return sent, opener

    def test_thinking_is_turned_off(self):
        sent, opener = self.capture()
        llm.generate("http://x", "m", "hi", opener=opener)
        self.assertIs(sent["think"], False)

    def test_mood_tagging_turns_it_off_too(self):
        sent, opener = self.capture()
        llm.mood_tags("http://x", "m", "Her", 2013, [], "", opener=opener)
        self.assertIs(sent["think"], False)


class TimeoutTest(unittest.TestCase):
    """A slow model should report, not crash with a traceback."""

    def test_a_read_timeout_is_reported_as_an_llm_error(self):
        def opener(request, timeout=None):
            raise TimeoutError("timed out")

        with self.assertRaises(llm.LLMError) as ctx:
            llm.generate("http://x", "m", "hi", opener=opener)
        self.assertIn("did not answer", str(ctx.exception).lower())

    def test_the_message_names_the_model_and_the_limit(self):
        def opener(request, timeout=None):
            raise TimeoutError("timed out")

        with self.assertRaises(llm.LLMError) as ctx:
            llm.generate("http://x", "slow-model", "hi", opener=opener)
        self.assertIn("slow-model", str(ctx.exception))
        self.assertIn(str(llm.TIMEOUT), str(ctx.exception))

    def test_mood_tagging_survives_a_timeout(self):
        def opener(request, timeout=None):
            raise TimeoutError("timed out")

        self.assertEqual(
            llm.mood_tags("http://x", "m", "Her", 2013, [], "", opener=opener), [])
