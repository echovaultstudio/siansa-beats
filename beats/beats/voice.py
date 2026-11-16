"""Whether a song is sung, by a woman or a man, and whether it is acoustic (0.51): three small Essentia models.

The owner (16 Nov): vibes should find vocal songs, female or male voices, and a DJ blend shouldn't lay one singer over
another. The feelings were here already (``other``: danceable, aggressive, happy, party, relaxed, sad, as AudioMuse-AI
makes them); these three weren't.

The models (MTG, UPF; CC BY-NC-SA 4.0; ONNX, 82 KB each, in the image) read the MusiCNN vector that is kept for every
song with a sound, as the energy's model does (:mod:`beats.drive`): a whole library is scored from what is already
kept, in seconds, with no song read again. What their makers measured, on their own collections: voice or
instrumental right for 98 songs in 100, female or male for 85, acoustic for 93.

Each is a share from 0 to 1: ``voice`` (0 instrumental, 1 sung), ``female`` (of the voice: 0 a man's, 1 a woman's;
only worth reading where ``voice`` is high) and ``acoustic``. Kept in the table ``voice`` beside the sound, each row
with the sound it was made from; :meth:`Voice.catch_up` scores what is new or changed. An image without the models has
none, and everything else is as before.
"""

import os
import threading

import numpy as np

from . import log, memory

_log = log.get("voice")

# name: (file, the class whose share is kept, the model's classes in its order)
MODELS = {
    "voice": ("voice_instrumental-msd-musicnn-1.onnx", "voice", ("instrumental", "voice")),
    "female": ("gender-msd-musicnn-1.onnx", "female", ("female", "male")),
    "acoustic": ("mood_acoustic-msd-musicnn-1.onnx", "acoustic", ("acoustic", "non_acoustic")),
}
NAMES = tuple(MODELS)
BATCH = 2000
SUNG = 0.5  # voice at or over this: a sung song


class Voice:
    def __init__(self, models_dir, store, threads=None):
        self.models_dir, self.store, self.threads = models_dir, store, threads
        self._sessions = None
        self._lock = threading.Lock()
        with store.lock:
            store.db.execute("CREATE TABLE IF NOT EXISTS voice (song_id TEXT PRIMARY KEY, voice REAL, female REAL, "
                             "acoustic REAL, sound_at REAL)")
            store.db.commit()

    def path(self, name):
        return os.path.join(self.models_dir, MODELS[name][0])

    @property
    def available(self):
        return all(os.path.exists(self.path(name)) for name in NAMES)

    @property
    def loaded(self):
        return self._sessions is not None

    def unload(self):
        with self._lock:
            had, self._sessions = self._sessions is not None, None
            return had

    def score(self, vectors):
        """``{"voice": [...], "female": [...], "acoustic": [...]}``: each share, 0 to 1, for each MusiCNN vector (rows
        of 200 float32)."""
        with self._lock:
            if self._sessions is None:
                import onnxruntime

                self._sessions = {name: onnxruntime.InferenceSession(self.path(name), memory.session_options(onnxruntime, self.threads),
                                                                     providers=["CPUExecutionProvider"]) for name in NAMES}
            rows = np.asarray(vectors, dtype=np.float32).reshape(-1, 200)
            out = {}
            for name, session in self._sessions.items():
                _, kept, classes = MODELS[name]
                out[name] = session.run(None, {session.get_inputs()[0].name: rows})[0][:, classes.index(kept)]
            return out

    def catch_up(self, most=None):
        """Scores every song whose sound is new or changed since it was scored; the number scored. Nothing without
        the models."""
        if not self.available:
            return 0
        done = 0
        while most is None or done < most:
            rows = self.store._rows(
                "SELECT o.song_id, o.musicnn, o.at FROM sound o LEFT JOIN voice v ON v.song_id = o.song_id "
                "WHERE o.musicnn IS NOT NULL AND length(o.musicnn) = 800 AND (v.song_id IS NULL OR v.sound_at IS NOT o.at) "
                "LIMIT ?", (BATCH,))
            if not rows:
                break
            got = self.score(np.stack([np.frombuffer(r["musicnn"], dtype=np.float32) for r in rows]))
            with self.store.lock:
                self.store.db.executemany(
                    "INSERT OR REPLACE INTO voice (song_id, voice, female, acoustic, sound_at) VALUES (?, ?, ?, ?, ?)",
                    [(r["song_id"], float(got["voice"][i]), float(got["female"][i]), float(got["acoustic"][i]), r["at"])
                     for i, r in enumerate(rows)])
                self.store.db.commit()
            done += len(rows)
        if done:
            self.unload()
            _log.info("Worked out the voice of %d songs (sung or not, a woman's or a man's, acoustic), from the sound kept for each", done)
        return done

    def of(self, song_ids):
        """``{song id: {"voice", "female", "acoustic"}}`` of the songs among ``song_ids`` that have them, each rounded
        to three places."""
        out, ids = {}, list(dict.fromkeys(song_ids))
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            for r in self.store._rows(f"SELECT song_id, voice, female, acoustic FROM voice WHERE song_id IN ({', '.join('?' for _ in chunk)})", chunk):  # noqa: S608 - only question marks are put in
                out[r["song_id"]] = {name: round(r[name], 3) for name in NAMES}
        return out

    def count(self):
        """``{"songs", "sung", "female", "male", "acoustic"}``: how many songs are scored, and how many fall each way."""
        r = self.store._rows(
            "SELECT COUNT(*) AS songs, COALESCE(SUM(voice >= ?), 0) AS sung, "
            "COALESCE(SUM(voice >= ? AND female >= 0.5), 0) AS female, COALESCE(SUM(voice >= ? AND female < 0.5), 0) AS male, "
            "COALESCE(SUM(acoustic >= 0.5), 0) AS acoustic FROM voice", (SUNG, SUNG, SUNG))[0]
        return dict(r)
