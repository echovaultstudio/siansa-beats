"""What a song is like, by Essentia's small trained models (0.51): sung or not, whose voice, its moods, danceable.

The owner (16 Nov): vibes and the search by words should find vocal songs, a woman's or a man's voice and the feeling
behind them, and a DJ blend shouldn't lay one singer over another. Beats had a song's feelings already, as
AudioMuse-AI makes them (``other``: how near the song's CLAP vector sits to a word); these are Essentia's models trained
for each trait, on listeners' own labels.

Every model (MTG, UPF; CC BY-NC-SA 4.0; ONNX, 82 KB each, in the image) reads the MusiCNN vector that is kept for every
song with a sound, as the energy's model does (:mod:`beats.drive`): a whole library is scored once from what is
already kept, in seconds, with no song read again, and new songs as they come.

Each trait is a share from 0 to 1 (``TRAITS``). ``female`` is of the voice: only worth reading where ``voice`` is high.
The five MIREX moods are one model's answer, shared out between them (they add up to 1). Kept in the table ``traits``
beside the sound, each row with the sound it was made from; :meth:`Traits.catch_up` scores what is new or changed. An
image without the models has none, and everything else is as before.
"""

import os
import threading

import numpy as np

from . import log, memory

_log = log.get("traits")

# model file: (the model's classes in its order, {trait: the class it is the share of}); what its makers measured
# (5-fold, on their own collections) in the comment.
MODELS = {
    "voice_instrumental-msd-musicnn-1.onnx": (("instrumental", "voice"), {"voice": "voice"}),  # 98 %
    "gender-msd-musicnn-1.onnx": (("female", "male"), {"female": "female"}),  # 85 %
    "mood_acoustic-msd-musicnn-1.onnx": (("acoustic", "non_acoustic"), {"acoustic": "acoustic"}),  # 93 %
    "mood_aggressive-msd-musicnn-1.onnx": (("aggressive", "not_aggressive"), {"aggressive": "aggressive"}),  # 97 %
    "mood_electronic-msd-musicnn-1.onnx": (("electronic", "non_electronic"), {"electronic": "electronic"}),  # 93 %
    "mood_happy-msd-musicnn-1.onnx": (("happy", "non_happy"), {"happy": "happy"}),  # 84 %
    "mood_party-msd-musicnn-1.onnx": (("non_party", "party"), {"party": "party"}),  # 90 %
    "mood_relaxed-msd-musicnn-1.onnx": (("non_relaxed", "relaxed"), {"relaxed": "relaxed"}),  # 89 %
    "mood_sad-msd-musicnn-1.onnx": (("non_sad", "sad"), {"sad": "sad"}),  # 85 %
    "danceability-msd-musicnn-1.onnx": (("danceable", "not_danceable"), {"danceable": "danceable"}),  # 95 %
    # MIREX's five mood clusters (67 %): one answer shared out between them.
    "moods_mirex-msd-musicnn-1.onnx": (("passionate", "cheerful", "bittersweet", "humorous", "intense"),
                                       {f"mirex_{c}": c for c in ("passionate", "cheerful", "bittersweet", "humorous", "intense")}),
}
TRAITS = tuple(t for _, wanted in MODELS.values() for t in wanted)
# What each MIREX cluster stands for, as its makers put it.
MIREX = {
    "mirex_passionate": "passionate, rousing, confident, boisterous, rowdy",
    "mirex_cheerful": "rollicking, cheerful, fun, sweet, amiable",
    "mirex_bittersweet": "literate, poignant, wistful, bittersweet, autumnal, brooding",
    "mirex_humorous": "humorous, silly, campy, quirky, whimsical, witty",
    "mirex_intense": "aggressive, fiery, tense, anxious, intense, volatile, visceral",
}
BATCH = 2000
HOLDS = 0.5  # a trait at or over this holds for the song (counted on the page)


class Traits:
    def __init__(self, models_dir, store, threads=None):
        self.models_dir, self.store, self.threads = models_dir, store, threads
        self._sessions = None
        self._lock = threading.Lock()
        with store.lock:
            store.db.execute(f"CREATE TABLE IF NOT EXISTS traits (song_id TEXT PRIMARY KEY, {', '.join(t + ' REAL' for t in TRAITS)}, sound_at REAL)")
            store.db.commit()

    def path(self, file):
        return os.path.join(self.models_dir, file)

    @property
    def available(self):
        return all(os.path.exists(self.path(f)) for f in MODELS)

    @property
    def loaded(self):
        return self._sessions is not None

    def unload(self):
        with self._lock:
            had, self._sessions = self._sessions is not None, None
            return had

    def score(self, vectors):
        """``{trait: [...]}``: each trait's share, 0 to 1, for each MusiCNN vector (rows of 200 float32)."""
        with self._lock:
            if self._sessions is None:
                import onnxruntime

                self._sessions = {f: onnxruntime.InferenceSession(self.path(f), memory.session_options(onnxruntime, self.threads),
                                                                  providers=["CPUExecutionProvider"]) for f in MODELS}
            rows = np.asarray(vectors, dtype=np.float32).reshape(-1, 200)
            out = {}
            for file, session in self._sessions.items():
                classes, wanted = MODELS[file]
                answer = session.run(None, {session.get_inputs()[0].name: rows})[0]
                for trait, cls in wanted.items():
                    out[trait] = answer[:, classes.index(cls)]
            return out

    def catch_up(self, most=None):
        """Scores every song whose sound is new or changed since it was scored; the number scored. Nothing without
        the models."""
        if not self.available:
            return 0
        done = 0
        names = ", ".join(TRAITS)
        marks = ", ".join("?" for _ in TRAITS)
        while most is None or done < most:
            rows = self.store._rows(
                "SELECT o.song_id, o.musicnn, o.at FROM sound o LEFT JOIN traits t ON t.song_id = o.song_id "
                "WHERE o.musicnn IS NOT NULL AND length(o.musicnn) = 800 AND (t.song_id IS NULL OR t.sound_at IS NOT o.at) "
                "LIMIT ?", (BATCH,))
            if not rows:
                break
            got = self.score(np.stack([np.frombuffer(r["musicnn"], dtype=np.float32) for r in rows]))
            with self.store.lock:
                self.store.db.executemany(
                    f"INSERT OR REPLACE INTO traits (song_id, {names}, sound_at) VALUES (?, {marks}, ?)",  # noqa: S608 - names are ours
                    [(r["song_id"], *(float(got[t][i]) for t in TRAITS), r["at"]) for i, r in enumerate(rows)])
                self.store.db.commit()
            done += len(rows)
        if done:
            self.unload()
            _log.info("Worked out the voice, moods and danceability of %d songs, from the sound kept for each", done)
        return done

    def of(self, song_ids):
        """``{song id: {trait: share}}`` of the songs among ``song_ids`` that have them, each to three places."""
        out, ids = {}, list(dict.fromkeys(song_ids))
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            for r in self.store._rows(f"SELECT song_id, {', '.join(TRAITS)} FROM traits WHERE song_id IN ({', '.join('?' for _ in chunk)})", chunk):  # noqa: S608 - names are ours, values are ?
                out[r["song_id"]] = {t: round(r[t], 3) for t in TRAITS}
        return out

    def count(self):
        """``{"songs", "sung", "female", "male", <each trait>: how many songs it holds for}``."""
        sums = ", ".join(f"COALESCE(SUM({t} >= {HOLDS}), 0) AS {t}" for t in TRAITS if t not in ("voice", "female"))
        r = self.store._rows(
            f"SELECT COUNT(*) AS songs, COALESCE(SUM(voice >= {HOLDS}), 0) AS sung, "  # noqa: S608 - names are ours
            f"COALESCE(SUM(voice >= {HOLDS} AND female >= 0.5), 0) AS female, COALESCE(SUM(voice >= {HOLDS} AND female < 0.5), 0) AS male, "
            f"{sums} FROM traits")[0]
        return dict(r)
