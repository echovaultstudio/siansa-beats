"""The AI service that names the mixes (beats/ai.py): the app's providers and their addresses, the key kept sealed,
a chat completion asked and read, and only names that can be used kept."""

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from beats import ai as A  # noqa: E402
from beats.store import Store  # noqa: E402
from beats.vault import Vault  # noqa: E402


class FakeAi:
    """An AI service's stand-in: answers ``reply`` (or raises ``fail``), and keeps what it was sent."""

    def __init__(self, reply="ready", fail=None):
        self.reply, self.fail, self.sent = reply, fail, []

    def __call__(self, request, timeout=None):
        self.sent.append((request.full_url, dict(request.header_items()), json.loads(request.data)))
        if self.fail:
            raise self.fail
        body = self.reply if isinstance(self.reply, str) and self.reply.startswith('{"error') else \
            json.dumps({"choices": [{"message": {"content": self.reply}}]})
        return io.BytesIO(body.encode())


class Providers(unittest.TestCase):
    def test_the_apps_providers_and_their_addresses(self):
        self.assertEqual(list(A.PROVIDERS), ["OPENROUTER", "OPENAI", "ANTHROPIC", "GEMINI", "MISTRAL", "GROQ", "OLLAMA", "OTHER"])
        self.assertEqual(A.completions_url("OPENROUTER"), "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(A.completions_url("ANTHROPIC"), "https://api.anthropic.com/v1/chat/completions")
        self.assertEqual(A.completions_url("GEMINI"), "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
        # One on your network, typed as you'd type it.
        self.assertEqual(A.completions_url("OLLAMA", "192.168.1.10:11434"), "http://192.168.1.10:11434/v1/chat/completions")
        self.assertEqual(A.completions_url("OTHER", "https://lm.local:1234/v1/"), "https://lm.local:1234/v1/chat/completions")
        self.assertIsNone(A.completions_url("OLLAMA", ""))
        self.assertIsNone(A.completions_url("NOPE"))

    def test_only_names_that_can_be_used_are_kept(self):
        got = A.clean_names('Sure! {"a": "Velvet Undertow", "b": "Sunny Side Up", "c": "velvet undertow", "d": "A Name Far Too Long To Fit On A Card", '
                            '"e": " \\"Low Lanterns.\\" ", "f": 7, "z": "Not Asked"}', ["a", "b", "c", "d", "e", "f", "g"])
        self.assertEqual(got, {"a": {"name": "Velvet Undertow"}, "e": {"name": "Low Lanterns"}})
        self.assertEqual(A.clean_names("no json here", ["a"]), {})
        self.assertEqual(A.clean_names('{"a": "Midnight Drive", "b": "Winter Coat", "c": "Rainy Days"}', ["a", "b", "c"]), {})
        # A name with a line on what's in it (0.55): the line kept when it's short and promises no weather.
        got = A.clean_names('{"a": {"name": "Velvet Undertow", "about": "Slow synths and hazy voices."}, '
                            '"b": {"name": "Glass Rooms", "about": "Bright pop for summer days"}, '
                            '"c": {"name": "Long Way", "about": "' + "word " * 20 + '"}}', ["a", "b", "c"])
        self.assertEqual(got, {"a": {"name": "Velvet Undertow", "about": "Slow synths and hazy voices"},
                               "b": {"name": "Glass Rooms"}, "c": {"name": "Long Way"}})


class TheService(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Store(os.path.join(self.folder.name, "beats.db"))
        self.fake = FakeAi()
        self.ai = A.Ai(self.store, Vault(self.folder.name), opener=self.fake)

    def test_set_up_with_its_key_kept_sealed_and_never_shown(self):
        first = self.ai.settings()
        self.assertEqual((first["on"], first["provider"], first["model"], first["has_key"], first["ready"]),
                         (False, "OPENROUTER", "google/gemini-2.5-flash", False, False))
        self.assertEqual(len(first["providers"]), 8)
        saved = self.ai.save(on=True, provider="OPENAI", model="gpt-4.1-mini", key="sk-secret")
        self.assertEqual((saved["has_key"], saved["ready"]), (True, True))
        self.assertNotIn("sk-secret", json.dumps(saved))
        self.assertNotIn("sk-secret", json.dumps(self.store.setting("ai")))  # sealed in the database
        self.ai.save(model="gpt-4.1")  # a key isn't lost when something else changes
        self.assertTrue(self.ai.settings()["has_key"])
        self.assertFalse(self.ai.save(key="")["ready"])  # removed
        self.assertTrue(self.ai.save(provider="OLLAMA", address="192.168.1.10:11434")["ready"])  # no key needed
        with self.assertRaises(A.AiError):
            self.ai.save(provider="NOPE")

    def test_a_call_as_the_app_makes_it(self):
        self.ai.save(on=True, provider="OPENROUTER", key="sk-secret")
        self.assertEqual(self.ai.complete("sys", "hi"), "ready")
        url, headers, body = self.fake.sent[0]
        self.assertEqual(url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual((headers["Authorization"], headers["X-title"]), ("Bearer sk-secret", "Siansa Beats"))
        self.assertEqual((body["model"], [m["role"] for m in body["messages"]]), ("google/gemini-2.5-flash", ["system", "user"]))
        # What went wrong, in the provider's name.
        self.fake.reply = '{"error": {"message": "Invalid key"}}'
        with self.assertRaisesRegex(A.AiError, "OpenRouter: Invalid key"):
            self.ai.complete("sys", "hi")
        self.fake.fail = urllib.error.URLError("refused")
        self.assertEqual(self.ai.test(), {"ok": False, "said": "OpenRouter can't be reached: refused"})

    def test_a_test_with_what_is_typed_before_it_is_saved(self):
        got = self.ai.test(provider="GROQ", key="gsk-typed")
        self.assertEqual(got, {"ok": True, "said": "ready"})
        self.assertEqual(self.fake.sent[0][1]["Authorization"], "Bearer gsk-typed")
        self.assertFalse(self.ai.settings()["has_key"])  # nothing saved
        self.assertEqual(A.Ai(self.store, Vault(self.folder.name), opener=self.fake).test(provider="OPENAI")["said"], "No OpenAI key set")

    def test_naming_mixes(self):
        self.assertEqual(self.ai.name_mixes([{"id": "now-1"}]), {})  # not set up: nothing asked
        self.assertEqual(self.fake.sent, [])
        self.ai.save(on=True, provider="OPENAI", key="k")
        self.fake.reply = '```json\n{"now-1": {"name": "Velvet Undertow", "about": "Hazy synths, slow pulse"}, "now-2": "Sunshine Pop"}\n```'
        got = self.ai.name_mixes([{"id": "now-1", "genres": ["Ambient"], "energy": "calm", "mood": "dark", "artists": ["A"], "tags": []},
                                  {"id": "now-2", "genres": ["Pop"], "energy": "high-energy", "mood": "bright", "artists": ["B"], "tags": []}])
        self.assertEqual(got, {"now-1": {"name": "Velvet Undertow", "about": "Hazy synths, slow pulse"}})
        sent = self.fake.sent[0][2]["messages"]
        self.assertIn("never says weather", sent[0]["content"])
        self.assertIn("no artist or song names", sent[0]["content"])
        self.assertIn('"genres": ["Ambient"]', sent[1]["content"])
        # Names its other mixes have are said, so none comes back (0.60.5).
        self.ai.name_mixes([{"id": "now-3"}], taken=["On repeat", "Night Drive"])
        self.assertIn("Night Drive, On repeat", self.fake.sent[-1][2]["messages"][1]["content"])
        # 0.61.2: a mix for right now may say the moment it's given; one with its own artist in its name is left out.
        self.fake.reply = '{"now-1": {"name": "Rainy Saturday Static"}, "now-2": {"name": "Rainy Days"}, "now-3": {"name": "Loathe Forever"}}'
        got = self.ai.name_mixes([{"id": "now-1", "moment": {"weather": "rain", "day": "Saturday"}}, {"id": "now-2"},
                                  {"id": "now-3", "artists": ["Loathe"]}])
        self.assertEqual(got, {"now-1": {"name": "Rainy Saturday Static"}})
        self.assertIn('"moment": {"weather": "rain"', self.fake.sent[-1][2]["messages"][1]["content"])
        self.fake.fail = urllib.error.URLError("down")
        self.assertEqual(self.ai.name_mixes([{"id": "now-1"}]), {})
        self.assertIn("can't be reached", self.ai.settings()["error"])


if __name__ == "__main__":
    unittest.main()


class Plans(unittest.TestCase):
    """0.57: the app's plans (a vibe, Today's mix, Flow's words, a mood radio) made here, with the app's prompt."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Store(os.path.join(self.folder.name, "beats.db"))
        self.fake = FakeAi(reply='Sure: {"title": " Coffee before the storm ", "query": "warm acoustic guitar, soft vocals, slow", '
                                 '"description": "Easy start.", "steer": [{"term": "piano", "direction": "MORE"}, '
                                 '{"term": "drums", "direction": "sideways"}, "loud", {"term": "a", "direction": "less"}, '
                                 '{"term": "b", "direction": "less"}, {"term": "c", "direction": "less"}]}')
        self.ai = A.Ai(self.store, Vault(self.folder.name), opener=self.fake)

    def test_not_set_up(self):
        with self.assertRaises(A.AiError):
            self.ai.plan("Time slot: Morning")
        self.assertEqual(self.fake.sent, [])

    def test_a_plan_from_the_apps_brief(self):
        self.ai.save(on=True, provider="OPENAI", key="sk-secret")
        plan = self.ai.plan("Time slot: Morning\nGuidance: calm")
        self.assertEqual(plan, {"title": "Coffee before the storm", "query": "warm acoustic guitar, soft vocals, slow",
                                "description": "Easy start.",
                                "steer": [{"term": "piano", "direction": "more"}, {"term": "a", "direction": "less"},
                                          {"term": "b", "direction": "less"}]})
        _, _, body = self.fake.sent[0]
        self.assertEqual(body["messages"][0]["content"], A.PLAN_SYSTEM)
        self.assertEqual(body["messages"][1]["content"], "Time slot: Morning\nGuidance: calm")
        with self.assertRaises(A.AiError):
            self.ai.plan("   ")

    def test_an_incomplete_or_failed_answer(self):
        self.ai.save(on=True, provider="OPENAI", key="sk-secret")
        for reply in ('{"title": "Hi", "query": "x"}', '{"query": "warm synths"}', "no json", "[1]"):
            self.fake.reply = reply
            with self.assertRaises(A.AiError, msg=reply):
                self.ai.plan("Time slot: Morning")
        self.fake.reply = '{"error": {"message": "quota"}}'
        with self.assertRaises(A.AiError):
            self.ai.plan("Time slot: Morning")
        self.assertIn("quota", self.ai.last_error)
