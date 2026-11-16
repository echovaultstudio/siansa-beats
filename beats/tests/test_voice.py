"""Sung or not, whose voice, acoustic (0.51, beats/voice.py): scored from the sound kept. The real models are tried
when the image is built (Dockerfile), and here too when they're at hand (VOICE_MODELS); otherwise a stand-in."""

import os
import sys
import tempfile
import time
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from beats import voice  # noqa: E402
from beats.store import Store  # noqa: E402
from beats.voice import Voice  # noqa: E402


def vector(value):
    return np.full(200, value, dtype=np.float32).tobytes()


class Scored(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Store(os.path.join(self.folder.name, "beats.db"))
        self.voice = Voice(self.folder.name, self.store)
        for name in voice.NAMES:
            open(self.voice.path(name), "w").close()  # "the models are there"
        self.asked = []

        def score(vectors):  # a stand-in: voice is the vector's first number, female one less it, acoustic half of it
            first = np.asarray(vectors)[:, 0]
            self.asked.append(len(first))
            return {"voice": first, "female": 1 - first, "acoustic": first / 2}

        self.voice.score = score

    def sound(self, song_id, value, source="audiomuse"):
        self.store.save_sound([{"song_id": song_id, "musicnn": vector(value), "energy": 0.3}], source)

    def test_nothing_without_every_model(self):
        os.remove(self.voice.path("female"))
        self.assertFalse(self.voice.available)
        self.sound("a", 0.5)
        self.assertEqual(self.voice.catch_up(), 0)
        self.assertEqual(self.voice.of(["a"]), {})
        self.assertEqual(self.voice.count(), {"songs": 0, "sung": 0, "female": 0, "male": 0, "acoustic": 0})

    def test_every_song_with_a_sound_is_scored_once(self):
        self.sound("sung-by-a-man", 0.9)
        self.sound("instrumental", 0.2)
        self.store.sound_failed("unheard", "couldn't be read")  # no vector: left alone
        self.assertEqual(self.voice.catch_up(), 2)
        got = self.voice.of(["sung-by-a-man", "instrumental", "unheard"])
        self.assertEqual(got["sung-by-a-man"], {"voice": 0.9, "female": 0.1, "acoustic": 0.45})
        self.assertEqual(got["instrumental"]["voice"], 0.2)
        self.assertNotIn("unheard", got)
        self.assertEqual(self.voice.catch_up(), 0)  # nothing new: the models aren't asked
        self.assertEqual(self.asked, [2])
        # An instrumental song's "whose voice" isn't counted either way.
        self.assertEqual(self.voice.count(), {"songs": 2, "sung": 1, "female": 0, "male": 1, "acoustic": 0})

    def test_a_song_heard_again_is_scored_again(self):
        self.sound("a", 0.3)
        self.voice.catch_up()
        time.sleep(0.01)
        self.sound("a", 0.8, source="beats")
        self.assertEqual(self.voice.catch_up(), 1)
        self.assertEqual(self.voice.of(["a"])["a"]["voice"], 0.8)

    def test_a_big_library_goes_in_batches(self):
        self.store.save_sound([{"song_id": f"s{i}", "musicnn": vector(0.1)} for i in range(voice.BATCH + 5)])
        self.assertEqual(self.voice.catch_up(), voice.BATCH + 5)
        self.assertEqual(self.asked, [voice.BATCH, 5])


@unittest.skipUnless(os.environ.get("VOICE_MODELS"), "the real models: set VOICE_MODELS to their folder")
class RealModels(unittest.TestCase):
    def test_each_model_answers_a_share_for_each_song(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        real = Voice(os.environ["VOICE_MODELS"], Store(os.path.join(folder.name, "beats.db")))
        self.assertTrue(real.available)
        vectors = np.random.default_rng(1).normal(0, 1, (5, 200)).astype(np.float32)
        got, again, one = real.score(vectors), real.score(vectors), real.score(vectors[:1])
        for name in voice.NAMES:
            self.assertEqual(got[name].shape, (5,))
            self.assertTrue(np.all((got[name] >= 0) & (got[name] <= 1)), got[name])
            self.assertTrue(np.allclose(got[name], again[name]))
            self.assertAlmostEqual(float(one[name][0]), float(got[name][0]), places=4)


if __name__ == "__main__":
    unittest.main()
