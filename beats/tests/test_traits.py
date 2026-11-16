"""Sung or not, whose voice, moods, danceable (0.51, beats/traits.py): Essentia's models, scored from the sound kept.
The real models are tried when the image is built (Dockerfile), and here too when they're at hand (TRAIT_MODELS);
otherwise a stand-in."""

import os
import sys
import tempfile
import time
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from beats import traits  # noqa: E402
from beats.store import Store  # noqa: E402
from beats.traits import TRAITS, Traits  # noqa: E402


def vector(value):
    return np.full(200, value, dtype=np.float32).tobytes()


class Scored(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Store(os.path.join(self.folder.name, "beats.db"))
        self.traits = Traits(self.folder.name, self.store)
        for file in traits.MODELS:
            open(self.traits.path(file), "w").close()  # "the models are there"
        self.asked = []

        def score(vectors):  # a stand-in: every trait is the vector's first number, female one less it
            first = np.asarray(vectors)[:, 0]
            self.asked.append(len(first))
            out = {t: first for t in TRAITS}
            out["female"] = 1 - first
            return out

        self.traits.score = score

    def sound(self, song_id, value, source="audiomuse"):
        self.store.save_sound([{"song_id": song_id, "musicnn": vector(value), "energy": 0.3}], source)

    def test_every_trait_has_a_model_and_the_mirex_moods_are_five(self):
        self.assertEqual(len(TRAITS), len(set(TRAITS)))
        for t in ("voice", "female", "acoustic", "aggressive", "electronic", "happy", "party", "relaxed", "sad", "danceable"):
            self.assertIn(t, TRAITS)
        self.assertEqual([t for t in TRAITS if t.startswith("mirex_")], list(traits.MIREX))

    def test_nothing_without_every_model(self):
        os.remove(self.traits.path("gender-msd-musicnn-1.onnx"))
        self.assertFalse(self.traits.available)
        self.sound("a", 0.5)
        self.assertEqual(self.traits.catch_up(), 0)
        self.assertEqual(self.traits.of(["a"]), {})
        self.assertEqual(self.traits.count()["songs"], 0)

    def test_every_song_with_a_sound_is_scored_once(self):
        self.sound("sung-by-a-man", 0.9)
        self.sound("instrumental", 0.2)
        self.store.sound_failed("unheard", "couldn't be read")  # no vector: left alone
        self.assertEqual(self.traits.catch_up(), 2)
        got = self.traits.of(["sung-by-a-man", "instrumental", "unheard"])
        self.assertEqual((got["sung-by-a-man"]["voice"], got["sung-by-a-man"]["female"], got["sung-by-a-man"]["sad"]), (0.9, 0.1, 0.9))
        self.assertEqual(set(got["instrumental"]), set(TRAITS))
        self.assertNotIn("unheard", got)
        self.assertEqual(self.traits.catch_up(), 0)  # nothing new: the models aren't asked
        self.assertEqual(self.asked, [2])
        c = self.traits.count()
        # An instrumental song's "whose voice" isn't counted either way.
        self.assertEqual((c["songs"], c["sung"], c["female"], c["male"], c["happy"], c["danceable"]), (2, 1, 0, 1, 1, 1))

    def test_a_song_heard_again_is_scored_again(self):
        self.sound("a", 0.3)
        self.traits.catch_up()
        time.sleep(0.01)
        self.sound("a", 0.8, source="beats")
        self.assertEqual(self.traits.catch_up(), 1)
        self.assertEqual(self.traits.of(["a"])["a"]["voice"], 0.8)

    def test_a_big_library_goes_in_batches(self):
        self.store.save_sound([{"song_id": f"s{i}", "musicnn": vector(0.1)} for i in range(traits.BATCH + 5)])
        self.assertEqual(self.traits.catch_up(), traits.BATCH + 5)
        self.assertEqual(self.asked, [traits.BATCH, 5])


class ThePage(unittest.TestCase):
    """0.52: the Voice and mood page's numbers and the songs of each of its lines."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Store(os.path.join(self.folder.name, "beats.db"))
        self.traits = Traits(self.folder.name, self.store)
        for file in traits.MODELS:
            open(self.traits.path(file), "w").close()
        # song: (voice, female, happy, the strongest MIREX group)
        self.said = {"woman": (0.9, 0.95, 0.8, "mirex_cheerful"), "high-man": (0.8, 0.55, 0.45, "mirex_cheerful"),
                     "man": (0.7, 0.1, 0.2, "mirex_intense"), "low-woman": (0.95, 0.45, 0.58, "mirex_bittersweet"),
                     "piano": (0.1, 0.9, 0.3, "mirex_bittersweet")}
        order = list(self.said)

        def score(vectors):
            ids = [order[int(round(float(v[0])))] for v in np.asarray(vectors)]
            out = {t: np.zeros(len(ids), dtype=np.float32) for t in TRAITS}
            for i, song in enumerate(ids):
                voice, female, happy, top = self.said[song]
                out["voice"][i], out["female"][i], out["happy"][i] = voice, female, happy
                for m in traits.MIREX:
                    out[m][i] = 0.4 if m == top else 0.15
            return out

        self.traits.score = score
        for n, song in enumerate(order):
            self.store.add_song({"id": song, "title": song.title(), "artist": "Somebody", "album": "", "duration": 60,
                                 "suffix": "mp3", "tag_bpm": None, "genres": []})
            self.store.save_sound([{"song_id": song, "musicnn": vector(n)}])
        self.store.add_song({"id": "unheard", "title": "Unheard", "artist": "Somebody", "album": "", "duration": 60,
                             "suffix": "mp3", "tag_bpm": None, "genres": []})

    def test_the_numbers_before_and_after_scoring(self):
        before = self.traits.report()
        self.assertEqual((before["available"], before["total"], before["scored"], before["sung"]), (True, 5, 0, 0))
        self.assertTrue(all(line["songs"] == 0 for line in before["lines"]))
        self.traits.catch_up()
        after = self.traits.report()
        self.assertEqual((after["total"], after["scored"], after["sung"]), (5, 5, 4))
        songs = {line["key"]: line["songs"] for line in after["lines"]}
        # Whose voice is counted of sung songs only: the piano's "woman" isn't one. The three add up to the scored.
        self.assertEqual((songs["female"], songs["male"], songs["instrumental"]), (2, 2, 1))
        self.assertEqual((songs["happy"], songs["sad"]), (2, 0))
        # Each song is in one MIREX group, its strongest: they add up to the scored too.
        self.assertEqual(sum(songs[m] for m in traits.MIREX), 5)
        self.assertEqual((songs["mirex_cheerful"], songs["mirex_bittersweet"], songs["mirex_humorous"]), (2, 2, 0))
        self.assertEqual([line["group"] for line in after["lines"]][:4], ["voice", "voice", "voice", "moods"])
        self.assertEqual({line["key"]: line["right"] for line in after["lines"]}["female"], 85)
        self.assertEqual(set(traits.LINES), {line["key"] for line in after["lines"]})

    def test_a_lines_songs_most_sure_least_sure_and_the_close_calls(self):
        self.traits.catch_up()
        ids = lambda got: [r["id"] for r in got["rows"]]  # noqa: E731
        most = self.traits.songs("female")
        self.assertEqual((most["songs"], ids(most), most["rows"][0]["sure"], most["right"]), (2, ["woman", "high-man"], 0.95, 85))
        self.assertEqual(ids(self.traits.songs("female", "least")), ["high-man", "woman"])
        # A man's is one less the woman's share: the surest man first.
        self.assertEqual([(r["id"], r["sure"]) for r in self.traits.songs("male")["rows"]], [("man", 0.9), ("low-woman", 0.55)])
        self.assertEqual([(r["id"], r["sure"]) for r in self.traits.songs("instrumental")["rows"]], [("piano", 0.9)])
        # The close calls are on both sides of the line, and say which side; never an instrumental for whose voice.
        unsure = self.traits.songs("female", "unsure")
        self.assertEqual([(r["id"], r["holds"]) for r in unsure["rows"]], [("high-man", True), ("low-woman", False)])
        self.assertEqual([(r["id"], r["holds"]) for r in self.traits.songs("happy", "unsure")["rows"]],
                         [("low-woman", True), ("high-man", False)])
        self.assertEqual(ids(self.traits.songs("mirex_cheerful")), ["high-man", "woman"])
        # A page at a time.
        self.assertEqual(ids(self.traits.songs("female", limit=1)), ["woman"])
        second = self.traits.songs("female", limit=1, offset=1)
        self.assertEqual((ids(second), second["songs"]), (["high-man"], 2))
        self.assertEqual((self.traits.songs("sad")["songs"], self.traits.songs("sad")["rows"]), (0, []))


@unittest.skipUnless(os.environ.get("TRAIT_MODELS"), "the real models: set TRAIT_MODELS to their folder")
class RealModels(unittest.TestCase):
    def test_each_trait_is_a_share_for_each_song(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        real = Traits(os.environ["TRAIT_MODELS"], Store(os.path.join(folder.name, "beats.db")))
        self.assertTrue(real.available)
        vectors = np.random.default_rng(1).normal(0, 1, (5, 200)).astype(np.float32)
        got, again, one = real.score(vectors), real.score(vectors), real.score(vectors[:1])
        self.assertEqual(set(got), set(TRAITS))
        for t in TRAITS:
            self.assertEqual(got[t].shape, (5,))
            self.assertTrue(np.all((got[t] >= 0) & (got[t] <= 1)), (t, got[t]))
            self.assertTrue(np.allclose(got[t], again[t]))
            self.assertAlmostEqual(float(one[t][0]), float(got[t][0]), places=4)
        mirex = sum(got[t] for t in traits.MIREX)
        self.assertTrue(np.allclose(mirex, 1, atol=1e-3), mirex)


if __name__ == "__main__":
    unittest.main()
