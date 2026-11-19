"""Where a song's vocals are, bar by bar (beats/vocals.py, 0.60): what counts as sung, the bars and ends the app
blends by, which songs are separated, and the fields the app gets."""

import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from beats import vocals as V  # noqa: E402
from beats.store import Store  # noqa: E402

F = V.FRAME_SECONDS


def flags(*spans, seconds):
    """Sung frames from (from, to) seconds spans, over ``seconds``."""
    out = np.zeros(int(round(seconds / F)), dtype=bool)
    for a, b in spans:
        out[int(round(a / F)):int(round(b / F))] = True
    return out


class WhatCountsAsSung(unittest.TestCase):
    def test_loud_vocals_count_quiet_bleed_and_reverb_do_not(self):
        mix = np.full(100, 0.3)
        vocal = np.full(100, 0.0005)  # -66 dB: bleed
        vocal[20:60] = 0.15  # -16 dB: singing
        vocal[60:64] = 0.004  # a reverb tail, 31 dB under the singing
        sung = V.activity(vocal, mix)
        self.assertTrue(sung[20:60].all())
        self.assertFalse(sung[:20].any() or sung[64:].any())
        self.assertFalse(sung[61:64].any())

    def test_a_song_without_vocals_has_none(self):
        self.assertFalse(V.activity(np.full(50, 0.003), np.full(50, 0.3)).any())  # -50 dB at its loudest
        self.assertEqual(V.activity([], []).size, 0)

    def test_vocals_drowned_by_the_music_do_not_count(self):
        vocal = np.full(40, 0.05)
        mix = np.full(40, 0.05)
        mix[10:20] = 1.0  # the vocals a fortieth of the energy there
        sung = V.activity(vocal, mix)
        self.assertFalse(sung[10:20].any())
        self.assertTrue(sung[:10].all())

    def test_breaths_are_filled_and_blips_dropped(self):
        mix, vocal = np.full(100, 0.3), np.full(100, 1e-5)
        vocal[10:30] = vocal[34:50] = 0.2  # a 0.4 s breath between two lines
        vocal[80:82] = 0.2  # a 0.2 s blip
        sung = V.activity(vocal, mix)
        self.assertTrue(sung[10:50].all())
        self.assertFalse(sung[80:82].any())


class Bars(unittest.TestCase):
    """A 120 BPM song (2 s bars) of 200 s, its ends heard 0–96 s and 104–200 s."""

    DOWNS = [i * 2.0 for i in range(101)]

    def parts(self, intro_spans, outro_spans):
        return [(0.0, flags(*intro_spans, seconds=96)), (104.0, flags(*[(a - 104, b - 104) for a, b in outro_spans], seconds=96))]

    def test_the_ends_vocal_free_bars_and_sections(self):
        # Locks at 4 s and 196 s; vocals from 20 s (bar 10) to 50 s, and in the outro until 180 s.
        s = V.summary(self.parts([(20.3, 50)], [(120, 180.2)]), self.DOWNS, 4.0, 196.0)
        self.assertEqual(s["intro_vocal_ms"], 20000)
        self.assertEqual(s["intro_vocal_free_bars"], 8)  # 4 s to 20 s
        self.assertEqual(s["outro_vocal_ms"], 180000)  # 180.2 s: a tenth of a bar isn't a quarter of it
        self.assertEqual(s["outro_vocal_free_bars"], 8)  # 180 s to 196 s
        self.assertEqual(s["vocal_sections_ms"], [[20000, 50000], [120000, 180000]])
        self.assertEqual(s["vocal_heard_ms"], [[0, 96000], [104000, 200000]])

    def test_an_instrumental_end_has_at_least_the_bars_heard(self):
        s = V.summary(self.parts([], [(110, 150)]), self.DOWNS, 4.0, 196.0)
        self.assertIsNone(s["intro_vocal_ms"])
        self.assertEqual(s["intro_vocal_free_bars"], 46)  # 4 s to 96 s, all heard without a singer
        self.assertEqual(s["outro_vocal_free_bars"], 23)  # 150 s to 196 s

    def test_vocals_before_the_lock_or_past_it(self):
        # Singing over the lock: no free bars at that end.
        s = V.summary(self.parts([(0, 30)], [(150, 200)]), self.DOWNS, 4.0, 196.0)
        self.assertEqual((s["intro_vocal_free_bars"], s["intro_vocal_ms"]), (0, 4000))
        self.assertEqual((s["outro_vocal_free_bars"], s["outro_vocal_ms"]), (0, 196000))

    def test_a_short_song_heard_whole(self):
        downs = [i * 2.0 for i in range(61)]
        s = V.summary([(0.0, flags((40, 60), seconds=120))], downs, None, None)
        self.assertEqual((s["intro_vocal_ms"], s["outro_vocal_ms"]), (40000, 60000))
        self.assertEqual((s["intro_vocal_free_bars"], s["outro_vocal_free_bars"]), (20, 30))
        self.assertIsNone(V.summary([(0.0, flags(seconds=10))], [0.0], None, None))

    def test_the_ends_separated(self):
        self.assertEqual(V.windows(180.0), [(0.0, 180.0)])
        self.assertEqual(V.windows(300.0), [(0.0, V.END_SECONDS), (300.0 - V.END_SECONDS, V.END_SECONDS)])


class FakeSeparator:
    available, model = True, None

    def __init__(self, vocal_rms):
        self.vocal_rms, self.calls = vocal_rms, []

    def vocals(self, stereo):
        self.calls.append(stereo.shape)
        n = stereo.shape[1] // int(V.RATE * F)
        return self.vocal_rms[:n], np.full(n, 0.3)


class Finder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = Store(os.path.join(self.tmp, "beats.db"))
        self.addCleanup(self.store.close)
        self.store.db.execute("CREATE TABLE IF NOT EXISTS traits (song_id TEXT PRIMARY KEY, voice REAL)")
        for i, voice in (("sung", 0.9), ("instr", 0.05), ("unscored", None)):
            self.store.db.execute("INSERT INTO jobs (song_id, state, finished_at) VALUES (?, 'done', 1)", (i,))
            if voice is not None:
                self.store.db.execute("INSERT INTO traits VALUES (?, ?)", (i, voice))
        self.store.db.commit()
        vocal = np.full(300, 1e-5)
        vocal[100:200] = 0.2  # sung from 10 s to 20 s
        self.separator = FakeSeparator(vocal)
        self.downloaded = []
        self.finder = V.Vocals(self.store, self.separator, self.download, self.grid,
                               lambda ids: {r["song_id"]: r["voice"] for r in self.store._rows("SELECT * FROM traits")},
                               lambda: False, self.tmp)
        self.finder_decode = V.decode
        V.decode = lambda path, start, seconds: np.zeros((2, int(seconds * V.RATE)), np.float32)
        self.addCleanup(setattr, V, "decode", self.finder_decode)

    def download(self, song_id, path):
        self.downloaded.append(song_id)
        return 1

    def grid(self, song_id):
        return [i * 2.0 for i in range(16)], 0.0, 30.0, 30.0

    def test_only_songs_with_vocals_are_separated_when_ticked(self):
        self.assertTrue(self.finder.only_sung())  # ticked by default
        self.assertEqual(sorted(self.store.without_vocals(V.VERSION, need_voice=True)), ["instr", "sung"])
        self.assertEqual(self.finder.one("instr"), "none")
        self.assertEqual(self.downloaded, [])  # not read at all
        self.assertEqual(self.finder.one("unscored"), "waiting")
        self.assertEqual(self.finder.one("sung"), "separated")
        self.assertEqual(self.downloaded, ["sung"])
        fields = V.fields(self.store.vocals(["sung"])["sung"])
        self.assertEqual(fields["vocals"], "separated")
        self.assertEqual((fields["intro_vocal_ms"], fields["outro_vocal_ms"]), (10000, 20000))
        self.assertEqual(fields["intro_vocal_free_bars"], 5)
        self.assertEqual(V.fields(self.store.vocals(["instr"])["instr"]), {"vocals": "none"})
        self.assertEqual(self.store.vocal_counts(V.VERSION), {"separated": 1, "none": 1, "failed": 0, "waiting": 1})

    def test_unticked_every_song_is_separated_also_those_kept_as_instrumental(self):
        self.finder.one("instr")
        self.finder.set_only_sung(False)
        self.assertFalse(self.finder.only_sung())
        self.assertIn("instr", self.store.without_vocals(V.VERSION, again_none=True))
        self.assertEqual(self.finder.one("instr"), "separated")
        self.assertEqual(self.finder.one("unscored"), "separated")
        self.assertEqual(self.store.vocal_counts(V.VERSION)["waiting"], 1)  # "sung" not done yet

    def test_without_the_voice_model_every_song_is_separated(self):
        self.finder.voice_known = lambda: False
        self.assertEqual(self.finder.one("instr"), "separated")

    def test_a_song_that_cant_be_read_is_kept_as_failed(self):
        def broken(song_id, path):
            raise RuntimeError("the server is away")
        self.finder.download = broken
        self.assertEqual(self.finder.one("sung"), "failed")
        self.assertIsNone(V.fields(self.store.vocals(["sung"])["sung"]))
        self.assertNotIn("sung", self.store.without_vocals(V.VERSION))  # not tried again and again
        self.assertEqual(self.finder.status()["failed"], 1)

    def test_a_song_without_its_beats_waits(self):
        self.finder.grid = lambda song_id: None
        self.assertEqual(self.finder.one("sung"), "waiting")


if __name__ == "__main__":
    unittest.main()
