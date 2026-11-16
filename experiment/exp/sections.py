"""Breakdowns and drops from the kick, and how they compare with the owner's taps.

The rule under trial: the kick is "in" while its loud moments stay within ``gap`` dB of what's usual for the song,
and "out" otherwise; a state counts once it has held for ``hold`` seconds. Where it goes out is a breakdown, where it
comes back a drop. Plain Python: the same rule can be tried again on the saved levels with other numbers."""
import statistics

GAP_DB = 12.0  # the kick this far under the song's usual kick is "out"
HOLD_SECONDS = 4.0  # a state shorter than this is a fill or a pause, not a section
STEP_SECONDS = 0.5
WINDOW_SECONDS = 1.0


def kick_line(kick, hop, step=STEP_SECONDS, window=WINDOW_SECONDS):
    """The kick's loud moments: every ``step`` seconds, the level that the loudest tenth of the next ``window`` reaches."""
    size, jump = max(1, round(window / hop)), max(1, round(step / hop))
    out = []
    for start in range(0, max(1, len(kick) - size + 1), jump):
        part = sorted(kick[start:start + size])
        if part:
            out.append(part[min(len(part) - 1, int(len(part) * 0.9))])
    return out, jump * hop


def find(kick, hop, gap=GAP_DB, hold=HOLD_SECONDS):
    """``[{"seconds", "kind"}]``: where the kick goes out (``breakdown``) and comes back (``drop``), in order. A song
    whose kick is in from its first second starts with no drop; one with an intro without it gets the drop."""
    line, step = kick_line(kick, hop)
    if len(line) < 4:
        return []
    usual = statistics.median(sorted(line)[len(line) // 2:])
    on = [v >= usual - gap for v in line]
    # Runs of one state; short ones join what's around them (the first run stands whatever its length).
    runs = []
    for i, state in enumerate(on):
        if runs and runs[-1][0] == state:
            runs[-1][2] = i + 1
        else:
            runs.append([state, i, i + 1])
    need = max(1, round(hold / step))
    kept = []
    for state, a, b in runs:
        if kept and (b - a < need or kept[-1][0] == state):
            kept[-1][2] = b
        else:
            kept.append([state, a, b])
    merged = []
    for state, a, b in kept:
        if merged and merged[-1][0] == state:
            merged[-1][2] = b
        else:
            merged.append([state, a, b])
    return [{"seconds": round(a * step, 2), "kind": "drop" if state else "breakdown"} for state, a, _ in merged[1:]]


def score(found, marks, bpm):
    """How ``found`` compares with the taps ``marks`` (``[[seconds, kind]]``): a tap is found when the same kind is
    within a bar of it. Build-up taps are shown, not scored (the rule has no build-up). ``extra``: what was found
    between the first and last tap with no tap of any kind within a bar, counted only for a song tapped three times or
    more (elsewhere a spot without a tap may just not have been tapped)."""
    bar = 4 * 60.0 / bpm if bpm else 2.0
    near = bar + 0.3
    taps = []
    for seconds, kind in marks:
        hit = None
        if kind in ("drop", "breakdown"):
            close = [f for f in found if f["kind"] == kind and abs(f["seconds"] - seconds) <= near]
            hit = min(close, key=lambda f: abs(f["seconds"] - seconds))["seconds"] if close else False
        taps.append({"seconds": seconds, "kind": kind, "found": hit})
    scored = [t for t in taps if t["found"] is not None]
    out = {"taps": taps, "scored": len(scored), "hits": sum(1 for t in scored if t["found"] is not False),
           "between": None, "extra": None}
    if len(marks) >= 3:
        first, last = marks[0][0] - bar, marks[-1][0] + bar
        between = [f for f in found if first <= f["seconds"] <= last]
        out["between"] = len(between)
        out["extra"] = sum(1 for f in between if not any(abs(f["seconds"] - s) <= near for s, _ in marks))
    return out


def total(scores):
    """All songs' scores as one: ``{"songs", "scored", "hits", "between", "extra"}``."""
    out = {"songs": len(scores), "scored": 0, "hits": 0, "between": 0, "extra": 0}
    for s in scores:
        out["scored"] += s["scored"]
        out["hits"] += s["hits"]
        out["between"] += s["between"] or 0
        out["extra"] += s["extra"] or 0
    return out
