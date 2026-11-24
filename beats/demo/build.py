#!/usr/bin/env python3
"""Builds the demo of Siansa Beats' page: the real page, with made-up music and no server behind it.

The real service runs here for a moment on a made-up library (demo/library.py), with stand-ins for the models, as the
tests run it. Every answer the page can ask for is recorded, and the page is written out with a script in front of
it that answers from those (demo/shim.js). So the demo is always the page of this version, and nothing in it is anyone's.

    python3 demo/build.py <out folder> [name]     writes <name>.html and its three scripts there (name: beats-demo)
    python3 demo/build.py --serve [port]          the made-up service itself, to look at (default 8091)
"""

import datetime
import json
import os
import random
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "tests"))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

import library  # noqa: E402
from beats import features  # noqa: E402
from beats import sound as sound_module  # noqa: E402
from beats import vocals as vocals_module  # noqa: E402
from beats.server import App, Config, make_server  # noqa: E402
from fakes import PASSWORD, USER, FakeServer  # noqa: E402

LISTENER = "demo"
TZ = "Europe/London"
# The demo's "now": fixed, so the same version always builds the same demo.
NOW = int(datetime.datetime(2026, 11, 20, 19, 30, tzinfo=datetime.timezone.utc).timestamp())


# Kinds of music that sound a little like each other.
NEAR = {"liquid": ["neuro"], "neuro": ["liquid", "techno"], "house": ["deep"], "deep": ["house"], "techno": ["neuro"],
        "ambient": ["classical"], "classical": ["ambient"], "indie": ["pop", "folk"], "folk": ["indie"], "pop": ["indie", "synth"],
        "synth": ["pop"], "jazz": ["soul"], "soul": ["jazz", "hiphop"], "hiphop": ["soul"]}


class Samples:
    def __init__(self, song):
        self.song, self.song_id, self.seconds = song, song["id"], song["duration"]

    def __len__(self):
        return int(self.seconds * 22_050)


def stand_ins(songs):
    """The models' stand-ins: each says of a song what the library made up for it."""
    by_id = {s["id"]: s for s in songs}

    def of(path):
        with open(path) as f:
            return by_id[f.read().strip()]

    def decode(path):
        return Samples(of(path))

    class Tracker:
        loaded, load_seconds, device, device_name, device_note = True, 0.0, "cpu", "the demo's stand-in", None

        def __call__(self, samples):
            song = samples.song
            period = 60.0 / song["expect_bpm"]
            beats = [round((0.4 + i * period) / 0.02) * 0.02 for i in range(int((song["duration"] - 1.0) / period))]
            return beats, beats[::song["expect_bar"]]

    class Style:
        def __init__(self, models_dir):
            from beats import style as style_module

            self.models_dir, self.spec = models_dir, style_module.MODELS["effnet"]
            os.makedirs(models_dir, exist_ok=True)
            labels = sorted({label for s in songs for label, _ in s["heard"]})
            with open(os.path.join(models_dir, "discogs-effnet-bs64-1.json"), "w") as f:
                json.dump({"classes": labels}, f)
            self.on, self.loaded, self.load_seconds = True, True, 0.0

        def unload(self):
            self.loaded = False

        @property
        def available(self):
            return True

        def __call__(self, samples, rate=16_000):
            return [tuple(h) for h in samples.song["heard"]]

        def both(self, samples, rate=16_000):
            return {"gpu": None, "cpu": self(samples)}

    def measure_sound(path, samples, rate):
        song = samples.song
        return {"ref_lufs": song["lufs"], "start_ramp": "xAAA", "end_ramp": "xAAB", "duration_ms": int(song["duration"] * 1000),
                "key": song["key"], "scale": song["scale"], "key_strength": 0.8}

    class Hearer:
        loaded, load_seconds, available = True, 0.0, True

        def unload(self):
            return False

        def __call__(self, path):
            song = of(path)
            rng = np.random.default_rng(int(song["id"][1:9], 16))
            # Songs of a kind sound alike, and kinds that go together (NEAR) a little alike: the mixes are of a kind.
            v = rng.normal(0, 0.018, sound_module.DIMENSIONS).astype(np.float32)
            v[song["axis"]] += 1.0
            w = rng.normal(0, 0.018, sound_module.WORD_DIMENSIONS).astype(np.float32)
            w[song["axis"]] += 1.0
            for other in NEAR.get(song["kind"], ()):
                v[library.KINDS[other][6]] += 0.35
                w[library.KINDS[other][6]] += 0.35
            tag = song["genre"].lower()
            return {"musicnn": v.tobytes(), "clap": w.tobytes(), "moods": f"{tag}:0.600,electronic:0.300",
                    "other": f"danceable:{song['energy']:.2f},happy:{song['mood']:.2f}", "energy": round(song["energy"], 3)}

    return decode, Tracker(), Style, measure_sound, Hearer()


def start(folder, port=0):
    """The made-up service, analysed and listened to: ``(app, server, base address, fake music server)``."""
    songs = library.catalog()
    music = os.path.join(folder, "music")
    os.makedirs(music)
    for song in songs:
        with open(os.path.join(music, song["file"]), "w") as f:
            f.write(song["id"])
    with open(os.path.join(music, "catalog.json"), "w") as f:
        json.dump(songs, f)
    fake = FakeServer(music).start()
    decode, tracker, Style, measure_sound, hearer = stand_ins(songs)
    env = {"NAVIDROME_URL": fake.url, "NAVIDROME_USER": USER, "NAVIDROME_PASSWORD": PASSWORD, "DATA_DIR": os.path.join(folder, "data"),
           "MODELS_DIR": os.path.join(folder, "models"), "PORT": str(port)}
    app = App(Config(env), tracker=tracker, decode=decode, measure=lambda samples: features.measure(synth(samples.song)), style=Style(os.path.join(folder, "models")), sound=measure_sound, hearer=hearer)
    server = make_server(app, host="127.0.0.1", port=port)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    pretend_models(app)
    app.worker.start()
    return app, server, base, fake, songs


def call(base, path, method="GET", body=None, raw=False):
    request = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=60) as r:
        data = r.read()
        return (r, data) if raw else json.loads(data)


def analyse(base, timeout=600):
    libraries = call(base, "/api/libraries")
    print("libraries:", json.dumps(libraries)[:300])
    print(call(base, "/api/libraries", "POST", {"ids": ["1"]}))
    end = time.time() + timeout
    while time.time() < end:
        counts = call(base, "/api/status")["counts"]
        if counts.get("songs") and counts["songs"] == counts.get("done", 0) + counts.get("failed", 0) + counts.get("skipped", 0):
            return counts
        time.sleep(0.5)
    raise SystemExit(f"The made-up library wasn't analysed in time: {call(base, '/api/status')['counts']}")


def synth(song):
    """A song's sound for the phrase finder, made up: quiet ends, a few louder parts, a kick where it has one."""
    rng = np.random.default_rng(int(song["id"][1:9], 16) + 7)
    rate, seconds = 22_050, min(song["duration"], 240)
    t = np.arange(int(seconds * rate), dtype=np.float32) / rate
    parts = np.repeat(rng.choice([0.25, 0.5, 0.9, 1.0], size=int(seconds // 15) + 1), 15 * rate)[: t.size]
    parts[: 10 * rate] *= 0.3
    parts[-10 * rate:] *= 0.3
    beat = 60.0 / song["expect_bpm"]
    kick = (np.sin(2 * np.pi * 55 * t) * np.exp(-((t % beat) * 18))).astype(np.float32) * (0.9 if song["energy"] > 0.5 else 0.2)
    return ((rng.normal(0, 0.12, t.size).astype(np.float32) + kick) * parts).astype(np.float32)


def fill(app, songs, now):
    """What the stand-ins don't make: each song's energy and mood, its voice and feel, and where its vocals are."""
    from beats import traits as traits_module

    store = app.store
    at = {r[0]: r[1] for r in store.db.execute("SELECT song_id, at FROM sound")}
    with store.lock:
        for s in songs:
            rng = random.Random(s["id"] + "feel")
            store.db.execute("INSERT OR REPLACE INTO arousal (song_id, value, valence, sound_at) VALUES (?, ?, ?, ?)",
                             (s["id"], round(2.2 + 5.6 * s["energy"], 3), round(2.2 + 5.6 * s["mood"], 3), at.get(s["id"])))
            electronic = s["kind"] in ("liquid", "neuro", "house", "deep", "techno", "ambient", "synth")
            acoustic = s["kind"] in ("folk", "jazz", "classical", "soul")
            near = lambda x: round(min(0.99, max(0.01, x + rng.uniform(-0.08, 0.08))), 3)  # noqa: E731
            feel = {"voice": near(0.9 if s["sung"] else 0.08), "female": near(0.8 if rng.random() < 0.45 else 0.15),
                    "acoustic": near(0.85 if acoustic else 0.1), "aggressive": near(0.85 if s["kind"] in ("metal", "neuro") else 0.1),
                    "electronic": near(0.9 if electronic else 0.12), "happy": near(s["mood"]), "party": near(s["energy"] * s["mood"] + 0.1),
                    "relaxed": near(1 - s["energy"]), "sad": near((1 - s["mood"]) * (1 - s["energy"]) + 0.05),
                    "danceable": near(0.85 if s["kind"] in ("house", "deep", "techno", "liquid", "neuro", "synth", "pop") else 0.3)}
            mirex = [rng.random() + (2 if i == {"metal": 4, "neuro": 4, "techno": 4, "pop": 1, "house": 1, "folk": 2, "ambient": 2,
                                                "classical": 2}.get(s["kind"], 0) else 0) for i in range(5)]
            for name, value in zip([t for t in traits_module.TRAITS if t.startswith("mirex_")], mirex):
                feel[name] = round(value / sum(mirex), 3)
            names = ", ".join(traits_module.TRAITS)
            store.db.execute(f"INSERT OR REPLACE INTO traits (song_id, {names}, sound_at) VALUES (?, {', '.join('?' * len(traits_module.TRAITS))}, ?)",  # noqa: S608
                             (s["id"], *[feel[t] for t in traits_module.TRAITS], at.get(s["id"])))
        store.db.commit()
        store.writes += 1
    frame = vocals_module.FRAME_SECONDS
    for s in songs:
        rng = random.Random(s["id"] + "vocals")
        if not s["sung"]:
            store.save_vocals(s["id"], "none", None, vocals_module.VERSION, seconds=0.0)
            continue
        bar = 60.0 / s["expect_bpm"] * s["expect_bar"]
        downs = [0.4 + i * bar for i in range(int((s["duration"] - 1) / bar))]
        first, last = bar * rng.choice([8, 16, 16, 24]), s["duration"] - bar * rng.choice([8, 16, 16, 32])
        flags = np.zeros(int(s["duration"] / frame), dtype=bool)
        t = first
        while t < last:
            length = bar * rng.choice([8, 16])
            flags[int(t / frame): int(min(last, t + length) / frame)] = True
            t += length + bar * rng.choice([4, 8])
        summary = vocals_module.summary([(0.0, flags)], downs, None, None)
        store.save_vocals(s["id"], "separated", summary, vocals_module.VERSION, seconds=round(rng.uniform(4, 9), 1))


# What the demo's listener plays, and when: (kind, how much, the hours it's mostly played in, weekend more).
TASTE = [("liquid", 10, (17, 23), 1.0), ("neuro", 5, (20, 24), 1.6), ("house", 6, (15, 22), 2.2), ("deep", 4, (9, 13), 1.0),
         ("techno", 3, (21, 24), 2.0), ("ambient", 5, (6, 10), 0.8), ("indie", 6, (12, 19), 1.0), ("folk", 3, (7, 11), 1.2),
         ("metal", 1.5, (16, 20), 0.7), ("jazz", 4, (19, 23), 1.0), ("hiphop", 3, (13, 18), 1.0), ("soul", 4, (10, 15), 1.5),
         ("synth", 4, (18, 23), 1.2), ("classical", 1.5, (6, 9), 0.6), ("pop", 2.5, (12, 17), 1.3)]


def listen(app, songs, now, days=760):
    """Two years of made-up listening for the demo's listener: favourites, hours of the day, weekends, and a few
    artists found along the way."""
    rng = random.Random("the demo's listener")
    by_kind = {}
    for s in songs:
        by_kind.setdefault(s["kind"], []).append(s)
    love = {s["id"]: rng.paretovariate(1.3) for s in songs}  # a few songs are played far more than the rest
    found = {artist: rng.randint(0, days - 30) if n % 3 == 0 else days for n, (artist, _, _) in enumerate(library.ARTISTS)}
    zone = datetime.timezone.utc
    rows, skips = [], []
    start = datetime.datetime.fromtimestamp(now, zone).replace(hour=0, minute=0, second=0, microsecond=0)
    for back in range(days, -1, -1):
        day = start - datetime.timedelta(days=back)
        weekend = day.weekday() >= 5
        for _ in range(rng.choice([0, 1, 1, 2, 2, 3]) + (1 if weekend else 0)):
            kinds = [(k, w * (more if weekend else 1.0), hours) for k, w, hours, more in TASTE]
            kind, _, (low, high) = rng.choices(kinds, weights=[w for _, w, _ in kinds])[0]
            pool = [s for s in by_kind[kind] if found[s["artist"]] >= back]
            if not pool:
                continue
            at = day + datetime.timedelta(hours=rng.uniform(low, high - 0.5))
            for s in rng.choices(pool, weights=[love[s["id"]] for s in pool], k=rng.randint(3, 9)):
                when = at.timestamp()
                if when > now:
                    break
                if rng.random() < 0.06:
                    skips.append({"id": s["id"], "at": int(when), "heard": rng.randint(4, 25)})
                    at += datetime.timedelta(seconds=20)
                    continue
                rows.append({"id": s["id"], "at": int(when), "artist": s["artist"], "title": s["title"], "album": s["album"],
                             "duration": s["duration"], "client": "Siansa"})
                at += datetime.timedelta(seconds=s["duration"] + 3)
    kept = app.listens.add(LISTENER, rows)
    app.listens.add_skips(LISTENER, skips)
    return kept, len(skips)


def pretend_models(app):
    """The models the demo has no files of count as there: what they'd have scored is filled in by :func:`fill`."""
    for part in (app.traits, app.arousal):
        cls = type("Demo" + type(part).__name__, (type(part),), {"available": property(lambda self: True),
                                                                   "catch_up": lambda self, most=None: 0})
        part.__class__ = cls


DROPPED = ("tz", "user", "server")  # what the page adds of its own: the demo has one listener, one server, one clock


def key_of(path):
    """An answer's key: its address without what the page adds of its own, its other parts in order."""
    from urllib.parse import parse_qsl, urlencode, urlsplit

    parts = urlsplit(path)
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in DROPPED)
    return parts.path.lstrip("/") + ("?" + urlencode(query) if query else "")


def record(base, app, songs):
    """Every answer the page can ask the made-up service for: ``(answers by key, each song's own page by id)``."""
    from urllib.parse import quote

    answers = {}

    def keep(path, into=None):
        try:
            value = call(base, path)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"The made-up service didn't answer {path}: {e.code} {e.read()[:200]!r}") from e
        (answers if into is None else into)[key_of(path) if into is None else path] = value
        return value

    for path in ("/api/status", "/api/libraries", "/api/bad-blends", "/api/analysis/checks", "/api/clean/preview", "/api/mixes/settings",
                 "/api/ai", "/api/listens/import", "/api/genres", "/api/vocals", "/api/style/models", "/api/loudness", "/api/voice",
                 "/api/servers", "/api/v1/capabilities", "/api/log?after=0&limit=1000"):
        keep(path)
    # The table: every song once, and which of them each of the page's filters shows.
    every = answers["songs:all"] = call(base, "/api/songs?show=all&limit=1000")
    if len(every) != len(songs):
        raise SystemExit(f"The table has {len(every)} of the demo's {len(songs)} songs")
    for show in FILTERS:
        answers[f"songs:{show}"] = [row["id"] for row in call(base, f"/api/songs?show={show}&limit=1000")]
    # Listening: all time, each year and each month of it; the listener's profile; each artist's own page.
    whole = keep(f"/api/listens?tz={TZ}")
    for year in [y["year"] for y in whole["years"]]:
        keep(f"/api/listens?tz={TZ}&year={year}")
        for month in range(1, 13):
            keep(f"/api/listens?tz={TZ}&year={year}&month={month}")
    keep(f"/api/listens/profile?tz={TZ}")
    for artist in sorted({s["artist"] for s in songs}):
        keep(f"/api/listens/artist?tz={TZ}&name={quote(artist)}")
    # The mixes: now's, each part of the week's, and two more picks for "Make the mixes again".
    now = keep(f"/api/mixes?tz={TZ}")
    for part in now["parts"]:
        for days in ("weekdays", "weekend"):
            keep(f"/api/mixes?tz={TZ}&part={part['key']}&days={days}")
    again = []
    for _ in range(2):
        call(base, "/api/mixes/again", "POST", {"user": LISTENER, "tz": TZ})
        again.append(call(base, f"/api/mixes?tz={TZ}"))
    answers["mixes:again"] = again
    # Voice and mood: each line's songs, in each order, whole (the page asks for them a page at a time).
    for line in [x["key"] for x in answers["api/voice"]["lines"]]:
        for order in ("most", "least", "unsure"):
            keep(f"/api/voice/songs?line={line}&order={order}&limit=1000&offset=0")
    # Similar music, for each song the page can offer.
    for row in every:
        for kind in ("albums", "artists"):
            try:
                answers[key_of(f"/api/v1/similar/{kind}?track_id={row['id']}")] = call(base, f"/api/v1/similar/{kind}?track_id={quote(row['id'])}")
            except urllib.error.HTTPError:
                pass  # a song without a sound has none
    details = {}
    for row in every:
        details[row["id"]] = call(base, f"/api/songs/{quote(row['id'])}")
    return answers, details


FILTERS = ("differ", "done", "failed")


def tidy(answers, vocals, address):
    """What only this machine would say, said as a real one would: the models are there, the vocals are found, and
    the music server has a name that's no one's."""
    status = answers["api/status"]
    found = {**vocals, "available": True, "on": True, "chosen": True, "state": "all done", "loaded": False, "stuck": 0}
    status["vocals"].update(found)
    answers["api/vocals"].update(found)
    status.update({"device_name": "a made-up machine", "uptime_seconds": 86_400 * 12, "memory_mb": 412})

    def renamed(value):
        if isinstance(value, dict):
            return {k: ("demo" if k == "user" and v == USER else renamed(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [renamed(v) for v in value]
        return value.replace(address, "https://music.example") if isinstance(value, str) else value

    return renamed(answers)


def write(out, answers, details, at, name="beats-demo"):
    """The demo, in ``out``, as four plain files side by side, so a website with strict rules can serve it (no script
    in the page itself, no folders): ``<name>.html`` (the page), ``<name>.js`` (the answers and demo/shim.js),
    ``<name>-page.js`` (the page's own script) and ``<name>-songs.js`` (each song's own page, fetched when one is
    first opened). Each is linked by its content's hash, so a new demo is never a cached old one."""
    import hashlib

    from beats import __version__

    with open(os.path.join(HERE, "..", "beats", "page.html"), encoding="utf-8") as f:
        page = f.read()
    with open(os.path.join(HERE, "shim.js"), encoding="utf-8") as f:
        shim = f.read()
    # The page's pictures come from the music server: in the demo they're drawn (shim.js).
    if page.count(ART) != 1:
        raise SystemExit("The page's artUrl isn't as the demo knows it: update ART in demo/build.py")
    page = page.replace(ART, "function artUrl(kind, song, size) { return window.demoArt(kind, song, size); }")
    # And there are no files to play: each song gets a sound of its own tempo and key, made in the browser.
    if page.count(AUDIO) != 1:
        raise SystemExit("The page's player isn't as the demo knows it: update AUDIO in demo/build.py")
    page = page.replace(AUDIO, "player.src = window.demoAudio(id);")
    if page.count("<script>") != 1 or page.count("</script>") != 1:
        raise SystemExit("The page has more than its one script: the demo takes exactly one out")
    start, end = page.index("<script>"), page.index("</script>")
    own = page[start + len("<script>"):end]
    files = {
        f"{name}-songs.js": "window.demoSongs = " + json.dumps(details, separators=(",", ":")) + ";\n",
        f"{name}-page.js": own,
    }
    version = lambda text: hashlib.sha256(text.encode()).hexdigest()[:8]  # noqa: E731
    data = json.dumps({"at": int(at * 1000), "version": __version__, "answers": answers,
                       "songs": f"{name}-songs.js?v={version(files[f'{name}-songs.js'])}"}, separators=(",", ":"))
    files[f"{name}.js"] = "window.demoData = " + data + ";\n" + shim
    tags = "".join(f'<script src="{file}?v={version(files[file])}"></script>\n' for file in (f"{name}.js", f"{name}-page.js"))
    files[f"{name}.html"] = (page[:start] + tags + page[end + len("</script>"):]).replace(
        "<title>Siansa Beats</title>", '<title>Siansa Beats demo</title>\n<meta name="robots" content="noindex">', 1)
    os.makedirs(out, exist_ok=True)
    for file, text in files.items():
        with open(os.path.join(out, file), "w", encoding="utf-8") as f:
            f.write(text)
    return {file: len(text.encode()) for file, text in files.items()}


# Every address the page names, and what the demo does with it (tests/test_demo.py holds the page to this list: a new
# address has to be taught to demo/shim.js, then named here).
ADDRESSES = {
    # answered from what the made-up service said
    "answered": {"api/status", "api/libraries", "api/bad-blends", "api/analysis/checks", "api/clean/preview", "api/mixes/settings",
                 "api/ai", "api/listens/import", "api/genres", "api/vocals", "api/style/models", "api/loudness", "api/voice",
                 "api/servers", "api/log", "api/songs", "api/songs/", "api/listens", "api/listens/profile", "api/listens/artist",
                 "api/mixes", "api/voice/songs", "api/v1/similar/"},
    # made in the browser: pictures drawn, a sound for each song
    "made": {"api/art/", "api/audio/"},
    # a switch or a number, kept until the page is closed
    "kept": {"api/mixes/keep", "api/mixes/again", "api/log/level", "api/pause", "api/resume", "api/listens/memory", "api/signout"},
    # needs a real service: the demo says so, and changes nothing
    "not here": {"api/", "api/access/key", "api/access/password", "api/ai/test", "api/analyse-again", "api/analyse-all",
                 "api/analysis/start", "api/bad-blends/", "api/clean", "api/genres/about/fetch", "api/libraries/",
                 "api/libraries/read", "api/listens/lastfm", "api/listens/remove", "api/listens/rename", "api/servers/",
                 "api/servers/test", "api/style/model",
                 # files to download, and the API's own description
                 "api/bad-blends/export", "api/debug", "api/export.csv", "api/export.json", "api/failed/export",
                 "api/log/download", "api/v1/capabilities", "api/v1/openapi.json"},
}


def named(page):
    """The addresses ``page`` (the page's source) names."""
    import re

    return set(re.findall(r'["`](api/[A-Za-z0-9_./-]*)', page))


AUDIO = 'player.src = "api/audio/" + encodeURIComponent(id);'
ART = "function artUrl(kind, song, size) { return `api/art/${kind}/${encodeURIComponent(song)}?size=${size}`; }"


def build(out, name="beats-demo"):
    folder = tempfile.mkdtemp(prefix="beats-demo-")
    app, server, base, fake, songs = start(folder)
    try:
        analyse(base)
        at = time.time()
        fill(app, songs, at)
        listen(app, songs, at)
        app.config.secrets_left = []  # the stand-in's settings are no one's to tidy
        answers, details = record(base, app, songs)
        fresh = app.vocals.status(fresh=True)
        return write(out, tidy(answers, {k: fresh[k] for k in ("separated", "none", "failed", "waiting")}, fake.url), details, at, name)
    finally:
        app.worker.stop()
        server.shutdown()
        fake.stop()


if __name__ == "__main__":
    folder = tempfile.mkdtemp(prefix="beats-demo-")
    if sys.argv[1:2] == ["--serve"]:
        app, server, base, fake, songs = start(folder, int(sys.argv[2]) if len(sys.argv) > 2 else 8091)
        print(analyse(base))
        fill(app, songs, time.time())
        print(listen(app, songs, time.time()))
        print(f"The made-up service is on {base} (data in {folder})", flush=True)
        while True:
            time.sleep(60)
    else:
        print(build(sys.argv[1] if len(sys.argv) > 1 else "demo-out", *sys.argv[2:3]))
