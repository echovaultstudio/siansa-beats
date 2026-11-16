# Siansa Beats experiment

A **trial**, apart from Siansa Beats and temporary (siansa-dev #63): can breakdowns and drops be found from a song's
drums? Siansa Beats finds few of them from the bass's level (9 of 50 of the owner's taps, 16 Nov 2026), and no rule
on the levels it keeps came close: the kick and the bassline share the low end. Here each song is first split into
drums, bass, vocals and the rest (Demucs' htdemucs), and the rule looks at the kick alone.

Nothing here is used by Siansa Beats or the Siansa app. It goes again when the trial is decided.

## What it does

1. **Sign in to Navidrome** on its page: address, user name, password. Kept in memory only, gone at a restart.
2. **Pick a playlist.** **Make it for me** adds a playlist "Beats experiment" to Navidrome with the tapped songs
   (the one thing it ever writes to Navidrome).
3. **Analyse**: each song is downloaded, split, and measured; nothing of the song is kept but each part's level
   every 46 ms.
4. **The result**: where the kick goes out (a breakdown) and comes back (a drop), beside the taps: found when the same
   kind is within a bar. **Download results** has every song's levels, to try other rules on without analysing again.
5. **The log** says each step and how long it took, to judge what the whole library would cost.

The bar to pass, set before the trial: **80 % of the taps found, and at most 1 in 5 finds not at a tap.**

## The answer key

`marks.json`: the owner's taps in Siansa Dev (50 on 19 songs), by the music server's song ids, double taps removed
and three corrected by him. Build-up taps are shown, not scored: the rule has no build-up.

## The rule

The kick is the drums' part from 20 to 150 Hz. It is "in" while its loud moments stay within 12 dB of what's usual
for the song; a state counts once it has held 4 seconds (`exp/sections.py`). A first guess: the numbers are tuned on
the downloaded results, on these same taps.

## Running it

On TrueNAS with an NVIDIA GPU: `truenas.yml`. Elsewhere:

```
docker run -d --name beats-experiment --gpus all -p 8095:8095 -v beats-experiment:/data ghcr.io/echovaultstudio/siansa-beats:experiment
```

Then open `http://<server>:8095`. The page has no password of its own: keep it on your home network. Without a GPU it
runs on the CPU, slowly (`EXPERIMENT_DEVICE=cpu`).

## Tests

`python3 tests/test_experiment.py`: the rule, the score and the whole service against a fake Navidrome, with a
stand-in for Demucs. Demucs itself is checked when the image is built (`python -m exp.selfcheck`).
