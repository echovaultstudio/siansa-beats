"""Where a song's vocals are, bar by bar, at each end (0.60, the owner, 19 Nov: "combat vocals clashing on dj mix or
changes. It should be that 2 vocal tracks can be mixed but not where both vocals can be heard").

The voice is pulled out of the music with Hybrid Demucs (Défossez 2021; Meta's weights, MIT, as torchaudio publishes
them: ``HDEMUCS_HIGH_MUSDB_PLUS``, trained on MUSDB-HQ and 150 songs more), which splits a song into drums, bass,
other and vocals. Only the ends are separated, the first and the last :data:`END_SECONDS` (the whole song when it's
shorter than both): a blend happens there, and a song separated whole would take three times as long.

How loud the vocal stem is, every :data:`FRAME_SECONDS`, says where someone sings (:func:`activity`): a frame is sung
when the vocals are within :data:`BELOW_PEAK_DB` of the song's own loud vocals, over :data:`QUIETEST_DB` and at least
:data:`SHARE` of the music's energy there; short gaps (a breath) are filled and lone blips dropped. Then each bar of
the song's grid is sung when a quarter of it is (:func:`summary`), and the app gets, for each end:

- ``intro_vocal_ms`` / ``outro_vocal_ms``: where the first vocals start, and where the last ones end (ms, on bar
  lines); None when that end has none.
- ``intro_vocal_free_bars`` / ``outro_vocal_free_bars``: the bars from the lock (where a blend starts or ends) to the
  first vocals, and from the last vocals to the lock: those bars blend without a singer.
- ``vocal_sections_ms``: every sung stretch heard, ``[[from, to], …]``; ``vocal_heard_ms``: the stretches that were
  separated (``[[0, 96000], [114000, 210000]]``), so the app knows where a lack of vocals is known and where it isn't.

A song the voice model (:mod:`beats.traits`) calls instrumental needn't be separated: with Setup's box "Only songs
with vocals" ticked (the default) it's kept as ``none`` (no vocals) without being read. Kept in the table ``vocals``.
"""

import json
import subprocess
import threading
import time

import numpy as np

from . import log

_log = log.get("vocals")

VERSION = 1
RATE = 44_100
END_SECONDS = 96.0  # each end separated: a 32-bar blend at 90 BPM is 85 s
FRAME_SECONDS = 0.1
SEGMENT_SECONDS = 10.0  # the model hears this much at once (with 10 % more, overlapping)
OVERLAP = 0.1
SOURCES = ("drums", "bass", "other", "vocals")
WEIGHTS = "hdemucs_high_trained.pt"
WEIGHTS_URL = "https://download.pytorch.org/torchaudio/models/hdemucs_high_trained.pt"

# What counts as sung (tuned on the ends of songs: a whisper under a full mix still counts, a reverb tail doesn't).
QUIETEST_DB = -48.0  # vocals quieter than this (dBFS, the frame's RMS) are nothing
BELOW_PEAK_DB = 18.0  # sung: within this of the song's loud vocals (their 95th percentile)
SHARE = 0.06  # sung: the vocals at least this share of all the energy there
NO_VOCALS_DB = -42.0  # a song whose loud vocals are quieter than this has none (bleed of other instruments)
GAP_SECONDS = 0.6  # a gap this short in the vocals (a breath) is filled
BLIP_SECONDS = 0.3  # vocals this short alone are dropped (a click, a stray syllable of bleed)
BAR_SUNG = 0.25  # a bar is sung when this share of it is

COUNTS_SECONDS = 10
ONLY_SUNG_SETTING = "vocals_only_sung"
SUNG = 0.3  # the voice model's share at or over which a song is separated with "only songs with vocals"


def activity(vocal_rms, mix_rms, frame=FRAME_SECONDS):
    """Per frame, whether someone sings: from the vocal stem's RMS and the whole music's (both linear, one per frame).
    The loud vocals are the stem's 95th percentile over what's given (a song's ends together)."""
    v = np.asarray(vocal_rms, dtype=np.float64)
    m = np.asarray(mix_rms, dtype=np.float64)
    if not v.size:
        return np.zeros(0, dtype=bool)
    db = 20.0 * np.log10(v + 1e-9)
    loud = float(np.percentile(db, 95))
    if loud < NO_VOCALS_DB:
        return np.zeros(v.size, dtype=bool)
    share = v ** 2 / (m ** 2 + 1e-12)
    sung = (db >= loud - BELOW_PEAK_DB) & (db >= QUIETEST_DB) & (share >= SHARE)
    return _tidy(sung, max(1, round(GAP_SECONDS / frame)), max(1, round(BLIP_SECONDS / frame)))


def _runs(flags):
    """``[(start, stop, value)]``: the runs of equal values in ``flags``."""
    out, start = [], 0
    for i in range(1, len(flags) + 1):
        if i == len(flags) or flags[i] != flags[start]:
            out.append((start, i, bool(flags[start])))
            start = i
    return out


def _tidy(sung, gap, blip):
    sung = sung.copy()
    for a, b, value in _runs(sung):  # breaths: short gaps between vocals filled
        if not value and a > 0 and b < len(sung) and b - a <= gap:
            sung[a:b] = True
    for a, b, value in _runs(sung):  # lone blips dropped
        if value and b - a < blip:
            sung[a:b] = False
    return sung


def frame_rms(samples, rate=RATE, frame=FRAME_SECONDS):
    """The RMS of each frame of mono ``samples``."""
    n = max(1, int(rate * frame))
    usable = len(samples) // n * n
    if not usable:
        return np.zeros(0)
    return np.sqrt(np.mean(np.square(samples[:usable].reshape(-1, n), dtype=np.float64), axis=1))


def summary(parts, downbeats, intro_lock, outro_lock, frame=FRAME_SECONDS):
    """The app's fields (above) from ``parts``: ``[(start seconds, sung flags per frame)]``, one for each end separated
    (one for a song separated whole), the song's ``downbeats`` (its steady grid's, seconds) and its locks (seconds;
    None for the first and last downbeat)."""
    downs = sorted(downbeats)
    heard = [(start, start + len(flags) * frame) for start, flags in parts]
    if len(downs) < 2 or not parts:
        return None
    intro = intro_lock if intro_lock is not None else downs[0]
    outro = outro_lock if outro_lock is not None else downs[-1]
    bars = []  # (start, stop, sung) of the bars heard
    for a, b in zip(downs, downs[1:]):
        for start, flags in parts:
            lo, hi = int(round((a - start) / frame)), int(round((b - start) / frame))
            if lo >= 0 and hi <= len(flags) and hi > lo:
                bars.append((a, b, float(np.mean(flags[lo:hi])) >= BAR_SUNG))
                break
    sections = []
    for a, b, sung in bars:
        if not sung:
            continue
        if sections and abs(sections[-1][1] - a) < 1e-3:
            sections[-1][1] = b
        else:
            sections.append([a, b])
    first_end, last_start = heard[0][1], heard[-1][0]
    in_intro = [s for s in sections if s[0] < first_end]
    in_outro = [s for s in sections if s[1] > last_start]
    bar_length = float(np.median(np.diff(downs)))

    def count(a, b):
        return max(0, int(round((b - a) / bar_length)))

    first = next((s for s in in_intro if s[1] > intro + 1e-3), None)
    last = next((s for s in reversed(in_outro) if s[0] < outro - 1e-3), None)
    return {
        "intro_vocal_ms": _ms(max(first[0], intro)) if first else None,
        "outro_vocal_ms": _ms(min(last[1], outro)) if last else None,
        # With no vocals in that end, the bars heard from the lock (the end has at least that many without).
        "intro_vocal_free_bars": count(intro, max(intro, first[0])) if first else count(intro, max(intro, first_end)),
        "outro_vocal_free_bars": count(min(outro, last[1]), outro) if last else count(min(outro, last_start), outro),
        "vocal_sections_ms": [[_ms(a), _ms(b)] for a, b in sections],
        "vocal_heard_ms": [[_ms(a), _ms(b)] for a, b in heard],
    }


def _ms(t):
    return round(t * 1000.0)


def windows(duration):
    """``[(start, seconds)]``: the ends to separate of a song ``duration`` seconds long; the whole song (one) when
    that's no longer than both ends."""
    if duration <= 2 * END_SECONDS + 10:
        return [(0.0, duration)]
    return [(0.0, END_SECONDS), (duration - END_SECONDS, END_SECONDS)]


def decode(path, start, seconds, rate=RATE):
    """``seconds`` of the file at ``path`` from ``start``, as stereo float32 ``(2, n)`` at ``rate`` (ffmpeg)."""
    command = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-t", f"{seconds:.3f}", "-i", path, "-vn",
               "-ac", "2", "-ar", str(rate), "-f", "f32le", "-"]
    done = subprocess.run(command, capture_output=True, timeout=600, check=False)
    if done.returncode != 0:
        why = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError("ffmpeg couldn't read the song: " + (why[-1] if why else f"exit {done.returncode}"))
    return np.frombuffer(done.stdout, dtype=np.float32).reshape(-1, 2).T.copy()


class Separator:
    """Hybrid Demucs, loaded when first needed and let go when idle (:meth:`release`). On the GPU when there is one."""

    def __init__(self, models_dir, device="auto", threads=0):
        import os

        self.path = os.path.join(models_dir, WEIGHTS)
        self.requested, self.threads = device, threads
        self.model = self.device = None
        self.load_seconds = None
        self._lock = threading.Lock()

    @property
    def available(self):
        import os

        if not os.path.exists(self.path):
            return False
        try:
            import torch  # noqa: F401
            import torchaudio  # noqa: F401
        except ImportError:
            return False
        return True

    def load(self):
        if self.model is not None:
            return self.model
        import torch
        from torchaudio.models import hdemucs_high

        started = time.monotonic()
        cuda = torch.cuda.is_available() and self.requested != "cpu"
        self.device = torch.device("cuda" if cuda else "cpu")
        if self.threads and not cuda:
            torch.set_num_threads(self.threads)
        model = hdemucs_high(sources=list(SOURCES))
        model.load_state_dict(torch.load(self.path, map_location="cpu"))
        self.model = model.to(self.device).eval()
        self.load_seconds = round(time.monotonic() - started, 1)
        return self.model

    def release(self):
        with self._lock:
            if self.model is None:
                return
            self.model = None
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001 - nothing to give back
                pass

    def vocals(self, stereo):
        """``(vocal RMS, mix RMS)`` per frame of ``stereo`` ``(2, n)`` float32 at :data:`RATE`."""
        import torch
        from torchaudio.transforms import Fade

        with self._lock:
            model = self.load()
            mix = torch.from_numpy(stereo).to(self.device)
            ref = mix.mean(0)
            mean, std = ref.mean(), ref.std() + 1e-8
            wave = ((mix - mean) / std)[None]
            length = wave.shape[-1]
            chunk = int(RATE * SEGMENT_SECONDS * (1 + OVERLAP))
            overlap = int(OVERLAP * RATE * SEGMENT_SECONDS)
            fade = Fade(fade_in_len=0, fade_out_len=overlap, fade_shape="linear")
            vocal = torch.zeros(2, length, device=self.device)
            place = SOURCES.index("vocals")
            start, end = 0, chunk
            with torch.no_grad():
                while start < length - overlap:
                    out = fade(model(wave[:, :, start:end]))[0, place]
                    vocal[:, start:start + out.shape[-1]] += out
                    if start == 0:
                        fade.fade_in_len = overlap
                        start += chunk - overlap
                    else:
                        start += chunk
                    end += chunk
                    if end >= length:
                        fade.fade_out_len = 0
            vocal = (vocal * std).mean(0).cpu().numpy()
        return frame_rms(vocal), frame_rms(stereo.mean(0))


class Vocals:
    """Finds the vocals of the analysed songs that have none kept, one at a time, while nothing else is being done.

    ``separator``: :class:`Separator`; ``download(song_id, path)``: the song's file; ``grid(song_id)``: ``(downbeats,
    intro lock, outro lock, duration)`` in seconds, or None before its beats are known; ``voice(ids)``: ``{song id:
    the voice model's share}`` (``voice_known()``: whether it's there to ask); ``busy()``: whether the analysis is using the machine now."""

    def __init__(self, store, separator, download, grid, voice, busy, data_dir, voice_known=lambda: True):
        self.store, self.separator, self.download, self.grid, self.voice, self.busy = store, separator, download, grid, voice, busy
        # Whether the voice model is there to ask: without it (an image without the models) every song is separated.
        self.voice_known = voice_known
        self.data_dir = data_dir
        self.working = None  # {"id", "title", "artist", "since"} while a song is separated
        self.last_seconds = None
        self.last_work = time.time()
        self._counts = None  # (when, the counts): kept a few seconds
        # Only vocals (0.60.2, the owner: "no way to start only it"): the rest of the analysis is paused and the vocals
        # are found without waiting for it; ``done_alone()`` is called when no song is left, to carry on with the rest.
        self.alone = False
        self.done_alone = lambda: None
        self._stop = threading.Event()
        self._wake = threading.Event()

    @property
    def available(self):
        return self.separator.available

    def only_sung(self):
        return (self.store.setting(ONLY_SUNG_SETTING) or "1") == "1"

    def set_only_sung(self, on):
        self.store.set_setting(ONLY_SUNG_SETTING, "1" if on else "0")

    def start(self):
        threading.Thread(target=self._loop, name="vocals", daemon=True).start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def wake(self):
        """Looks for songs at once, not after its next rest (a minute when there was nothing to do)."""
        self._wake.set()

    def run_alone(self, on=True):
        """Only vocals (``on``), or back to finding them while nothing else is analysed."""
        self.alone = on
        self._counts = None
        self.wake()

    def _rest(self, seconds):
        self._wake.wait(seconds)
        self._wake.clear()

    def _loop(self):
        rest = 5.0
        while not self._stop.is_set():
            self._rest(rest)
            if self._stop.is_set():
                break
            try:
                rest = self.turn()
            except Exception:  # noqa: BLE001 - tried again next round
                _log.exception("Finding vocals went wrong")
                rest = 60

    def turn(self):
        """One round: the next songs' vocals, when it may. How long to rest before the next round, in seconds."""
        if not self.available:
            return 300
        if self.busy():
            return 5.0
        only = self.only_sung() and self.voice_known()
        waiting = self.store.without_vocals(VERSION, limit=20, again_none=not only, need_voice=only)
        if not waiting:
            if self.alone:  # every song's vocals found: the rest of the analysis carries on
                self.alone = False
                self.store.event("Only vocals: every song's vocals are found; the rest carries on")
                self.done_alone()
            return 60
        for song_id in waiting:
            if self._stop.is_set() or self.busy():
                break
            self.one(song_id)
        return 5.0

    def one(self, song_id):
        """Finds and keeps one song's vocals (or why not): ``"separated"``, ``"none"`` (instrumental, by the voice
        model), ``"waiting"`` (its voice or beats aren't known yet) or ``"failed"``."""
        import os
        import tempfile

        song = self.store.song(song_id) or {"id": song_id, "title": song_id, "artist": ""}
        found = self.grid(song_id)
        if found is None:
            return "waiting"
        downbeats, intro, outro, duration = found
        if self.only_sung() and self.voice_known():
            share = self.voice([song_id]).get(song_id)
            if share is None:
                return "waiting"
            if share < SUNG:
                self.store.save_vocals(song_id, "none", None, VERSION)
                return "none"
        self.working = {"id": song_id, "title": song.get("title"), "artist": song.get("artist"), "since": time.time()}
        path = None
        started = time.monotonic()
        try:
            fd, path = tempfile.mkstemp(prefix="vocals-", dir=self.data_dir)
            os.close(fd)
            self.download(song_id, path)
            parts, vocal, mix = [], [], []
            for start, seconds in windows(duration):
                v, m = self.separator.vocals(decode(path, start, seconds))
                parts.append((start, len(v)))
                vocal.append(v)
                mix.append(m)
            sung = activity(np.concatenate(vocal), np.concatenate(mix))  # the loud vocals of both ends together
            flags, at = [], 0
            for start, n in parts:
                flags.append((start, sung[at:at + n]))
                at += n
            values = summary(flags, downbeats, intro, outro)
            self.last_seconds = round(time.monotonic() - started, 1)
            self.store.save_vocals(song_id, "separated", values, VERSION, seconds=self.last_seconds)
            _log.debug("%s – %s: vocals %s in %.1fs", song.get("artist"), song.get("title"),
                       values and values["vocal_sections_ms"], self.last_seconds)
            return "separated"
        except Exception as e:  # noqa: BLE001 - kept, so it isn't tried again and again
            _log.warning("%s – %s: couldn't find its vocals: %s", song.get("artist"), song.get("title"), e)
            self.store.save_vocals(song_id, "failed", None, VERSION, error=str(e) or e.__class__.__name__)
            return "failed"
        finally:
            self.working = None
            self.last_work = time.time()
            if path and os.path.exists(path):
                os.remove(path)

    def let_go_if_idle(self, idle=600):
        """Lets the separation model go after ``idle`` seconds without a song (it loads again with the next): True
        when it went."""
        if self.working or self.separator.model is None or time.time() - self.last_work < idle:
            return False
        self.separator.release()
        self.store.event(f"Let go of the vocal separation model after {idle // 60} minutes without a song")
        return True

    def status(self, fresh=False):
        """The page's numbers: ``{"available", "only_sung", "separated", "none", "failed", "waiting", "working",
        "last_seconds", "alone"}``. The counts are kept for :data:`COUNTS_SECONDS` (the Overview asks every 2 s) unless ``fresh``."""
        now = time.monotonic()
        if fresh or self._counts is None or now - self._counts[0] > COUNTS_SECONDS:
            self._counts = (now, self.store.vocal_counts(VERSION))
        counts = self._counts[1]
        working = self.working
        return {"available": self.available, "only_sung": self.only_sung(), **counts,
                # How long the song has been worked on, by this machine's clock (the page's may differ).
                "working": working and {**working, "for_seconds": round(time.time() - working["since"], 1)}, "alone": self.alone, "last_seconds": self.last_seconds,
                "loaded": self.separator.model is not None}


def fields(row):
    """The profile's fields of a ``vocals`` row (:meth:`beats.store.Store.vocals`): ``{"vocals": "separated"|"none",
    …}`` with :func:`summary`'s for a separated one; None for one that failed."""
    if row is None or row["how"] not in ("separated", "none"):
        return None
    out = {"vocals": row["how"]}
    if row["how"] == "separated" and row.get("summary"):
        out.update(json.loads(row["summary"]))
    return out
