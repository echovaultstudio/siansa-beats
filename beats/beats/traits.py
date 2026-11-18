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

# ---- the page's Voice and mood (0.52): its lines, each with the songs it holds for ----
# Songs right of 100, as each model's makers measured it (the comments above): said on the page beside each line.
RIGHT = {"voice": 98, "female": 85, "acoustic": 93, "aggressive": 97, "electronic": 93, "happy": 84, "party": 90,
         "relaxed": 89, "sad": 85, "danceable": 95, "mirex": 67}
_TOP = f"MAX({', '.join('t.' + m for m in MIREX)})"  # a song's strongest MIREX group: the one it is counted in
# line: (its card on the page, when it holds for a song, how sure of it (0 to 1), the songs it is asked of, right of
# 100). Whose voice is asked of sung songs only; a MIREX group holds for the songs it is the strongest of (the five
# add up to 1, so hardly any reaches a half).
LINES = {
    "female": ("voice", f"t.voice >= {HOLDS} AND t.female >= {HOLDS}", "t.female", f"t.voice >= {HOLDS}", RIGHT["female"]),
    "male": ("voice", f"t.voice >= {HOLDS} AND t.female < {HOLDS}", "(1 - t.female)", f"t.voice >= {HOLDS}", RIGHT["female"]),
    "instrumental": ("voice", f"t.voice < {HOLDS}", "(1 - t.voice)", "1", RIGHT["voice"]),
    **{m: ("moods", f"t.{m} >= {HOLDS}", f"t.{m}", "1", RIGHT[m]) for m in ("happy", "sad", "relaxed", "party", "aggressive")},
    **{m: ("sound", f"t.{m} >= {HOLDS}", f"t.{m}", "1", RIGHT[m]) for m in ("danceable", "acoustic", "electronic")},
    **{m: ("groups", f"t.{m} >= {_TOP}", f"t.{m}", "1", RIGHT["mirex"])
       for m in ("mirex_cheerful", "mirex_bittersweet", "mirex_passionate", "mirex_intense", "mirex_humorous")},
}
ORDERS = ("most", "least", "unsure")
UNSURE = (0.4, 0.6)  # a close call: the songs most likely wrong, on either side of the line


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
                self.store.writes += 1  # the page's kept numbers are worked out again
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

    def report(self, server=None):
        """The page's numbers (0.52), of ``server``'s songs (every server's without one): ``{"available", "total":
        songs with a sound, "scored", "sung", "lines": [{"key", "group", "songs": it holds for, "right": of 100 in its
        makers' tests}]}``, the lines in the page's order."""
        of, args = self.store._of(server, "t.song_id")
        sums = ", ".join(f"COALESCE(SUM({holds}), 0) AS {key}" for key, (_, holds, *_) in LINES.items())
        r = self.store._rows(
            f"SELECT COUNT(*) AS scored, COALESCE(SUM(t.voice >= {HOLDS}), 0) AS sung, {sums} "  # noqa: S608 - names are ours
            f"FROM traits t JOIN songs s ON s.id = t.song_id WHERE 1=1{of}", args)[0]
        of, args = self.store._of(server, "o.song_id")
        total = self.store._rows(
            "SELECT COUNT(*) AS n FROM sound o JOIN songs s ON s.id = o.song_id "
            f"WHERE o.musicnn IS NOT NULL AND length(o.musicnn) = 800{of}", args)[0]["n"]
        return {"available": self.available, "total": max(total, r["scored"]), "scored": r["scored"], "sung": r["sung"],
                "lines": [{"key": key, "group": group, "songs": r[key], "right": right}
                          for key, (group, _, _, _, right) in LINES.items()]}

    def songs(self, line, order="most", limit=50, offset=0, server=None):
        """The songs of one line of the page (0.52): ``{"line", "group", "right", "order", "songs": how many there
        are, "rows": [{"id", "title", "artist", "sure": 0 to 1, "holds", "genres"}]}``, ``limit`` of them from
        ``offset``. ``order``: "most" sure first or "least" (of the songs it holds for), or "unsure": the close calls
        on either side of the line, which is where the wrong ones are."""
        group, holds, sure, asked, right = LINES[line]
        where = f"({asked}) AND {sure} BETWEEN {UNSURE[0]} AND {UNSURE[1]}" if order == "unsure" else f"({holds})"
        of, args = self.store._of(server, "t.song_id")
        base = f"FROM traits t JOIN songs s ON s.id = t.song_id WHERE {where}{of}"
        count = self.store._rows(f"SELECT COUNT(*) AS n {base}", args)[0]["n"]  # noqa: S608 - names are ours, values are ?
        rows = self.store._rows(
            f"SELECT s.id, s.title, s.artist, {sure} AS sure, ({holds}) AS holds {base} "  # noqa: S608
            f"ORDER BY sure {'ASC' if order == 'least' else 'DESC'}, s.id LIMIT ? OFFSET ?", (*args, int(limit), int(offset)))
        genres = self.store._genres_of([r["id"] for r in rows]) if rows else {}
        return {"line": line, "group": group, "right": right, "order": order, "songs": count,
                "rows": [{"id": r["id"], "title": r["title"], "artist": r["artist"], "sure": round(r["sure"], 3),
                          "holds": bool(r["holds"]), "genres": genres.get(r["id"], [])} for r in rows]}
