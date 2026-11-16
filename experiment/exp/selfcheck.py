"""The image checked while it's built: Demucs itself splits a made-up song whose kick stops and comes back, and the
rule finds both. ``python -m exp.selfcheck``."""
import time

import numpy as np

from . import sections, stems


def made_up(parts, bpm=124.0):
    """A kick on each beat where asked, a bassline under it all the way, and a hi-hat: stereo float32."""
    beat, out, rng = 60.0 / bpm, [], np.random.default_rng(3)
    for seconds, kick in parts:
        t = np.arange(int(seconds * stems.RATE)) / stems.RATE
        inside = np.mod(t, beat)
        part = 0.15 * np.sin(2 * np.pi * 55 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * t / (beat * 4)))  # the bassline never stops
        part += 0.05 * rng.standard_normal(t.size) * (np.mod(t, beat / 2) < 0.02)
        if kick:
            part += 0.7 * np.sin(2 * np.pi * (50 + 90 * np.exp(-inside * 40)) * inside) * np.exp(-inside * 14)
        out.append(part)
    mono = np.concatenate(out).astype(np.float32)
    return np.stack([mono, mono])


def main():
    separator = stems.DemucsSeparator("cpu")
    started = time.monotonic()
    parts = separator(made_up([(16, True), (12, False), (16, True)]))
    took = time.monotonic() - started
    assert set(parts) == set(stems.PARTS), sorted(parts)
    levels = stems.levels(parts)
    found = sections.find(levels["kick"], levels["hop"])
    print("demucs:", separator.describe(), f"· 44 s split in {took:.1f}s on the CPU · found", found)
    assert [f["kind"] for f in found] == ["breakdown", "drop"], found
    assert abs(found[0]["seconds"] - 16) <= 2 and abs(found[1]["seconds"] - 28) <= 2, found


if __name__ == "__main__":
    main()
