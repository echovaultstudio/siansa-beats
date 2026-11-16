"""A song split into its parts, and how loud each part is over time.

``decode`` reads any file with ffmpeg; a separator splits it into drums, bass, other and vocals (``DemucsSeparator``:
Demucs' htdemucs, on the GPU when there is one); ``levels`` measures each part every 46 ms. The kick is the drums'
part under 150 Hz: with the bassline taken away by the split, what's left there is the kick drum alone."""
import subprocess
import time

import numpy as np

RATE = 44100
FFT = 4096
HOP = 2048
KICK_HZ = (20.0, 150.0)
FLOOR_DB = -90.0
PARTS = ("drums", "bass", "other", "vocals")


def decode(path):
    """The file as stereo float32 at 44.1 kHz: an array of shape (2, samples)."""
    done = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "2", "-ar", str(RATE), "-"],  # noqa: S603, S607
                          capture_output=True, check=False)
    if done.returncode != 0 or not done.stdout:
        raise RuntimeError("ffmpeg couldn't read the file: " + (done.stderr.decode(errors="replace").strip()[-200:] or "no sound"))
    return np.frombuffer(done.stdout, np.float32).reshape(-1, 2).T.copy()


def _frames(mono):
    count = 1 + max(0, (mono.size - FFT) // HOP)
    index = (np.arange(count)[:, None] * HOP) + np.arange(FFT)[None, :]
    return index if mono.size >= FFT else np.zeros((0, FFT), int)


def _db(power):
    return np.round(10.0 * np.log10(power + 1e-10), 1).clip(FLOOR_DB, None)


def levels(parts):
    """``{"hop": seconds, "kick": [...], "drums": [...], "bass": [...], "other": [...], "vocals": [...]}``: each part's
    level in dB every ``hop`` seconds (a full-scale tone is about 0), from ``parts``: ``{name: (2, samples) array}``."""
    window = np.hanning(FFT).astype(np.float32)
    scale = float(window.sum()) ** 2
    freqs = np.fft.rfftfreq(FFT, 1.0 / RATE)
    low, high = (int(np.searchsorted(freqs, f)) for f in KICK_HZ)
    out = {"hop": HOP / RATE}
    for name in PARTS:
        mono = parts[name].mean(axis=0).astype(np.float32)
        index = _frames(mono)
        total, kick = [], []
        for start in range(0, len(index), 1024):  # a thousand frames at a time: little memory for a long song
            power = np.abs(np.fft.rfft((mono[index[start:start + 1024]] * window).astype(np.float64), axis=1)) ** 2 / scale
            total.append(power.sum(axis=1))
            if name == "drums":
                kick.append(power[:, low:high].sum(axis=1))
        out[name] = _db(np.concatenate(total)).tolist() if total else []
        if name == "drums":
            out["kick"] = _db(np.concatenate(kick)).tolist() if kick else []
    return out


class DemucsSeparator:
    """Demucs' htdemucs (Meta, MIT): drums, bass, other, vocals. Loaded at the first song."""
    name = "htdemucs"

    def __init__(self, device="auto"):
        self.wanted, self.device, self.model, self.load_seconds = device, None, None, None

    def _load(self):
        import torch
        from demucs.pretrained import get_model
        started = time.monotonic()
        self.device = ("cuda" if torch.cuda.is_available() else "cpu") if self.wanted == "auto" else self.wanted
        self.model = get_model(self.name).eval()
        self.load_seconds = round(time.monotonic() - started, 1)

    def describe(self):
        if self.model is None:
            return f"{self.name}, not loaded yet"
        import torch
        where = torch.cuda.get_device_name(0) if self.device == "cuda" else "the CPU"
        return f"{self.name} on {where}, loaded in {self.load_seconds}s"

    def __call__(self, audio):
        import torch
        from demucs.apply import apply_model
        if self.model is None:
            self._load()
        wav = torch.from_numpy(audio)
        ref = wav.mean(0)
        mean, std = ref.mean(), ref.std() + 1e-8
        with torch.no_grad():
            # In pieces of a few seconds, each moved to the GPU and back: a long song needs no more memory than a short one.
            out = apply_model(self.model, ((wav - mean) / std)[None], device=self.device, split=True, overlap=0.25, progress=False)[0]
        out = (out * std + mean).cpu().numpy()
        if self.device == "cuda":
            torch.cuda.empty_cache()
        return {name: out[i] for i, name in enumerate(self.model.sources)}


class FakeSeparator:
    """For the tests, without a model: everything under 200 Hz is "drums", the rest "other"."""
    name = "fake"

    def describe(self):
        return "a stand-in for the tests (no model)"

    def __call__(self, audio):
        spectrum = np.fft.rfft(audio.astype(np.float64), axis=1)  # in double: single-precision FFTs of minutes of sound differ between numpy builds
        cut = int(200.0 * audio.shape[1] / RATE)
        low = spectrum.copy()
        low[:, cut:] = 0
        drums = np.fft.irfft(low, n=audio.shape[1], axis=1).astype(np.float32)
        silent = np.zeros_like(audio)
        return {"drums": drums, "bass": silent, "other": audio - drums, "vocals": silent}
