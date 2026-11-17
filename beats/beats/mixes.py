"""Mixes made for a listener from their own listening (0.53, the owner, 17 Nov: "sunshine mixes in Finland at 6:40 am,
it's winter and dark outside"; can Siansa Beats "have its own algorithm to generate better mixes according to when you
listen, what you listen to and how you listen").

The app's mixes for the time of day were a fixed list by the clock. These are made from what Siansa Beats keeps:

- **when you listen**: every listen's hour and day, on the listener's own clock. The week is cut in ten *slots*: five
  parts of the day (:data:`PARTS`) on weekdays and at the weekend. A slot's songs are the ones played in it, a recent
  listen counting for more (:data:`HALF_LIFE` days halve it) and a listen from the same weeks of an earlier year for a
  little more again (:data:`SEASON_DAYS`, :data:`SEASON_WEIGHT`): December sounds like last December;
- **what you listen to**: the slot's songs fall into a few groups that sound alike (their MusiCNN vectors, the same the
  similar songs come from). Each group is a mix: some of its own songs, and around them songs that sound like them and
  weren't played lately (:data:`FRESH_DAYS`), at most :data:`PER_ARTIST` by one artist;
- **what it's like outside**: where the sun is, worked out from the day and the place (the time zone's city, or a
  latitude and longitude from the app): no weather service is asked. In the dark the calmer, darker groups come
  first; the less is known of a slot, the more the hour and the daylight count (:data:`LEAN`);
- **what each is called**: by its sound (its energy and valence against the library's, and the genre most of its songs
  are in): "Calm Indie Rock", "Driving Techno". A name never promises weather.

A slot with too little listening (:data:`ENOUGH` songs) borrows from that part of the day on any day, then from all
the listening; with none at all the mixes are made from the library, so there is always something to play.

Beside the slot's mixes: the listener's all-time groups ("Made for you"), **On repeat** (the most played of the last
:data:`REPEAT_DAYS` days), **Rediscover** (played often, not for :data:`FORGOTTEN_DAYS` days) and **New for you**
(never played, close to what is).

A mix is the same all day: what's picked by chance is picked by the day's date, and what's made is kept until the
part of the day, the light or the date changes (or the library or the listening grows by much: :meth:`Mixes._grown`),
not every time a song is heard. Not counted: skips (the app sends finished listens only).

**Names** (0.54): with an AI service set up (:mod:`beats.ai`), the mixes of a kind of music are named by it, from
their description only ("Velvet Undertow"); the names are kept for the day and the mix shows its sound's name until
they come, so nothing waits on the AI. On repeat, Rediscover and New for you keep their names.

**Ahead** (0.54): :meth:`Mixes.ahead` makes the next part of the day's mixes (and names them) a few minutes before it
starts, for every listener the app has asked for, so the app finds them made.

Plain Python and numpy, on :mod:`beats.sound`'s matrix and :mod:`beats.listens`' books.
"""

import datetime
import hashlib
import math
import os
import random
import sqlite3
import threading
import time

import numpy as np

from . import genres as genres_module
from . import log
from .listens import AT, SONG, zone
from .sound import unit

_log = log.get("mixes")

# part of the day: (key, as it's said, first hour, hour it ends before)
PARTS = (("early", "early morning", 5, 9), ("morning", "morning", 9, 12), ("afternoon", "afternoon", 12, 17),
         ("evening", "evening", 17, 22), ("night", "night", 22, 5))
DAYS = ("weekdays", "weekend")
HALF_LIFE = 120  # days after which a listen counts half
SEASON_DAYS = 30  # a listen within this many days of today's date in an earlier year…
SEASON_WEIGHT = 0.35  # …counts this much more, however old
ENOUGH = 25  # songs a slot needs to stand on its own
A_FEW = 8  # the fewest songs anything is made from, and the fewest a mix has
SIZE = 40  # songs in a mix
FAMILIAR = 0.4  # the share of a mix that's the listener's own songs of that group
FRESH_DAYS = 45  # the songs around them weren't played for this long
PER_ARTIST = 2
REPEAT_DAYS = 30
FORGOTTEN_DAYS = 180
# How much the hour and the daylight move a group up or down, by what the mixes are made from: the less Siansa Beats
# knows of the slot, the more they count.
LEAN = {"slot": 0.15, "part": 0.35, "all": 0.6, "library": 0.8}
# The energy that suits each part of the day when nothing else says, from 0 (the library's calmest) to 1.
SUITS = {"early": 0.3, "morning": 0.5, "afternoon": 0.6, "evening": 0.5, "night": 0.25}
DARK_SUITS = -0.12  # in the dark, a little calmer still
# A group's name: its energy (rows: low, middle, high) and its valence (columns: dark, middle, bright).
NAMES = (("Hushed", "Calm", "Gentle"), ("Moody", "Easy", "Warm"), ("Driving", "Lively", "Upbeat"))
LOW, HIGH = 0.42, 0.58  # where low ends and high starts, as a share of the library
AHEAD_MINUTES = 10  # the next part of the day's mixes are made this long before it starts
KEPT = 64  # answers kept
SAME = 0.5  # two groups are one when their centres are nearer than this share of their songs' own distance to them
REACH = 1.3  # a mix reaches this far past where most of its group's songs are (REACH_OF of them), and no further
REACH_OF = 0.9
GROUP = 12  # songs per group, at least, when deciding how many groups to look for


def part_of(hour):
    """The part of the day ``hour`` is in: its key."""
    for key, _, first, end in PARTS:
        if first <= hour < end or (first > end and (hour >= first or hour < end)):
            return key
    return "night"


def days_of(weekday):
    """"weekdays" or "weekend" for a day of the week (0 Monday … 6 Sunday)."""
    return DAYS[1] if weekday >= 5 else DAYS[0]


def said(part):
    return next(name for key, name, _, _ in PARTS if key == part)


def hours(part):
    """"05:00–09:00"."""
    first, end = next((f, e) for key, _, f, e in PARTS if key == part)
    return f"{first:02d}:00–{end:02d}:00"


# ---- the sun ----

_places = None


def place(tz_name):
    """``(latitude, longitude)`` of the city a time zone is named after ("Europe/Helsinki": 60.17, 24.97), from the
    zone tables that come with the zones; None when they don't say."""
    global _places
    if _places is None:
        found = {}
        for text in _zone_tables():
            for line in text.splitlines():
                cells = line.split("\t")
                if line.startswith("#") or len(cells) < 3:
                    continue
                spot = _coordinates(cells[1])
                if spot:
                    found.setdefault(cells[2], spot)
        _places = found
    return _places.get(tz_name or "")


def _zone_tables():
    for name in ("zone1970.tab", "zone.tab"):
        try:
            from importlib import resources

            yield resources.files("tzdata").joinpath("zoneinfo", name).read_text(encoding="utf-8")
            continue
        except Exception:  # noqa: S110 - no tzdata package here: the system's zones
            pass
        try:
            with open(os.path.join("/usr/share/zoneinfo", name), encoding="utf-8") as file:
                yield file.read()
        except OSError:
            pass


def _coordinates(text):
    """``+6010+02458`` (degrees and minutes, ISO 6709) as ``(60.17, 24.97)``."""
    cut = max(text.rfind("+"), text.rfind("-"))
    if cut <= 0:
        return None

    def degrees(part, whole):
        sign = -1.0 if part[0] == "-" else 1.0
        digits = part[1:]
        if not digits.isdigit() or len(digits) < whole + 2:
            return None
        value = int(digits[:whole]) + int(digits[whole:whole + 2]) / 60.0
        if len(digits) >= whole + 4:
            value += int(digits[whole + 2:whole + 4]) / 3600.0
        return sign * value

    lat, lon = degrees(text[:cut], 2), degrees(text[cut:], 3)
    return (round(lat, 2), round(lon, 2)) if lat is not None and lon is not None else None


def elevation(lat, lon, at):
    """How high the sun stands at ``(lat, lon)`` at ``at`` (seconds since 1970), in degrees over the horizon: the
    almanac's short formula, right to a fraction of a degree."""
    d = (at - 946728000) / 86400.0  # days since 1 January 2000, noon UTC
    g = math.radians((357.528 + 0.9856003 * d) % 360)
    lam = math.radians((280.460 + 0.9856474 * d) % 360 + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.0000004 * d)
    ascension = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    declination = math.asin(math.sin(eps) * math.sin(lam))
    sidereal = math.radians(((18.697374558 + 24.06570982441908 * d) % 24) * 15 + lon)
    hour_angle = sidereal - ascension
    phi = math.radians(lat)
    return math.degrees(math.asin(math.sin(phi) * math.sin(declination) + math.cos(phi) * math.cos(declination) * math.cos(hour_angle)))


RISEN = -0.833  # the sun's upper edge at the horizon, through the air
DUSK = -6.0  # civil twilight: under this it's dark


def daylight(lat, lon, at, tz_name=None):
    """What it's like outside at ``at``: ``{"light": "dark", "twilight" or "light", "elevation", "sunrise", "sunset"
    ("08:21" on the clock of ``tz_name``; None on a day the sun doesn't rise or doesn't set), "said"}``."""
    tz = zone(tz_name)
    now = datetime.datetime.fromtimestamp(at, tz)
    start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    high = elevation(lat, lon, at)
    rise = sets = None
    before = elevation(lat, lon, start) > RISEN
    for minute in range(5, 24 * 60 + 5, 5):
        up = elevation(lat, lon, start + minute * 60) > RISEN
        if up != before:
            clock = datetime.datetime.fromtimestamp(start + minute * 60 - 150, tz).strftime("%H:%M")
            if up and rise is None:
                rise = clock
            elif not up and sets is None:
                sets = clock
        before = up
    light = "light" if high > RISEN else "twilight" if high > DUSK else "dark"
    clock = now.strftime("%H:%M")
    if light == "light":
        text = f"Light outside until {sets}" if sets else "Light outside all day"
    elif rise is None and sets is None:
        text = "The sun doesn't rise today"
    elif rise and clock < rise:
        text = ("Getting light" if light == "twilight" else "Dark outside") + f": the sun rises at {rise}"
    else:
        text = ("Getting dark" if light == "twilight" else "Dark outside") + (f": the sun set at {sets}" if sets else "")
    return {"light": light, "elevation": round(high, 1), "sunrise": rise, "sunset": sets, "said": text}


# ---- groups of songs that sound alike ----

def groups(vectors, weights, k, rounds=12):
    """``vectors`` (rows of length one) in at most ``k`` groups that sound alike, the songs with more ``weights``
    pulling harder: ``[rows of each group]``, the heaviest group first. The same every time: it starts from the
    heaviest song and then, each time, the song least like any start so far."""
    n = len(vectors)
    k = max(1, min(k, n))
    starts = [int(np.argmax(weights))]
    while len(starts) < k:
        nearest = (vectors @ vectors[starts].T).max(axis=1)
        nearest[starts] = np.inf
        starts.append(int(np.argmin(nearest)))
    centres = vectors[starts].copy()
    belongs = np.zeros(n, int)
    for _ in range(rounds):
        now = np.argmax(vectors @ centres.T, axis=1)
        if _ and np.array_equal(now, belongs):
            break
        belongs = now
        for g in range(k):
            own = belongs == g
            if own.any():
                centres[g] = unit((vectors[own] * weights[own, None]).sum(axis=0))[0]
    # A group of a song or two is no mix: its songs join the group they're most like.
    sizes = np.bincount(belongs, minlength=k)
    big = [g for g in range(k) if sizes[g] >= min(4, max(1, n // k))] or [int(np.argmax(sizes))]
    if len(big) < k:
        belongs = np.array(big)[np.argmax(vectors @ centres[big].T, axis=1)]
    out = [np.flatnonzero(belongs == g) for g in big]
    # Two halves of one kind of music are one group: their centres are nearer each other than their own songs are
    # to them (SAME of that). The nearest two first, until none are.
    while len(out) > 1:
        middles = [unit((vectors[rows] * weights[rows, None]).sum(axis=0))[0] for rows in out]
        spread = [float((1.0 - vectors[rows] @ middle).mean()) for rows, middle in zip(out, middles)]
        apart, a, b = min((1.0 - float(middles[a] @ middles[b]), a, b) for a in range(len(out)) for b in range(a + 1, len(out)))
        if apart >= SAME * max(1e-6, (spread[a] + spread[b]) / 2):
            break
        out[a] = np.sort(np.concatenate([out[a], out[b]]))
        del out[b]
    return sorted(out, key=lambda rows: -float(weights[rows].sum()))


# ---- the mixes ----

class Mixes:
    def __init__(self, store, sound, listens, traits=None, arousal=None, now=time.time, ai=None, background=True):
        self.store, self.sound, self.listens, self.traits, self.arousal, self.now = store, sound, listens, traits, arousal, now
        self.ai, self.background = ai, background
        self._lock = threading.Lock()
        self._kept = {}  # what was asked -> its answer, while nothing it's made from changed
        self._names = {}  # (listener, day, mix id, its songs) -> the AI's name for it
        self._naming = set()  # what's being named now
        self.asked = {}  # listener -> (tz, lat, lon, server, size): how the app last asked, to make theirs ahead
        self._scale = None  # (the store's writes it was read at, energies sorted, valences sorted, {song: (energy, valence)})

    def listeners(self):
        """Who mixes can be made for: the listeners, most listens first."""
        return [u["user"] for u in self.listens.users() if u["listens"]]

    def make(self, user, tz=None, at=None, server=None, lat=None, lon=None, part=None, days=None, size=SIZE):
        """The mixes for ``user`` at ``at`` (now) on the clock of ``tz``: ``{"user", "at", "tz", "part", "days",
        "said", "hours", "basis", "based", "listens", "songs", "daylight", "shelves": [{"key", "title", "note",
        "mixes": [{"id", "name", "why", "tags", "artists", "energy", "mood", "own", "songs": [{"id", "title",
        "artist", "album", "own"}]}]}]}``. ``part`` and ``days`` ask for another slot than ``at``'s (the page's look
        at another time); ``lat`` and ``lon`` say where the listener is, instead of the time zone's city."""
        user = self.listens.who(user)
        at = int(at if at is not None else self.now())
        kept, light = self._made(user, tz, at, server, lat, lon, part, days, size)
        return {"user": user, "at": at, "tz": tz, **self._named(user, kept)}

    def _made(self, user, tz, at, server, lat, lon, part, days, size):
        """The mixes of that slot, made or kept; and the light they were made for."""
        local = self.listens._local(tz)
        year, month, day, hour, weekday, ordinal = local(at)
        slot_part = part if part in SUITS else part_of(hour)
        slot_days = days if days in DAYS else days_of(weekday)
        if part in SUITS and part != part_of(hour):  # another time of today: an hour inside it, for the sun
            first = next(f for key, _, f, _ in PARTS if key == part)
            at += ((first + 1 - hour) % 24) * 3600 if first > hour else -((hour - first - 1) % 24) * 3600
        spot = (float(lat), float(lon)) if lat is not None and lon is not None else place(tz)
        sun = daylight(spot[0], spot[1], at, tz) if spot else None
        size = max(A_FEW, min(100, int(size)))
        self.sound._load()
        key = (user, tz, server, ordinal, slot_part, slot_days, spot and (round(spot[0], 1), round(spot[1], 1)),
               sun and sun["light"], size, self._grown(user))
        with self._lock:
            kept = self._kept.get(key)
        if kept is None:
            started = time.monotonic()
            kept = self._make(user, tz, at, server, slot_part, slot_days, sun, size, local, ordinal)
            with self._lock:
                if len(self._kept) > KEPT:
                    self._kept.clear()
                self._kept[key] = kept
            _log.info("Mixes for %s, %s on %s: %d made from %s in %.1fs", user or "nobody", said(slot_part), slot_days,
                      sum(len(s["mixes"]) for s in kept["shelves"]), kept["basis"], time.monotonic() - started)
        if self.ai is not None and self.ai.ready:
            self._name_soon(user, ordinal, kept)
        return kept, sun and sun["light"]

    def _grown(self, user):
        """What the mixes are made from, roughly: the songs whose sound is known (by the thousand) and the listener's
        listens (by the 500). Made again when either moves on, not at every listen."""
        return (len(self.sound.ids) // 1000, (self.listens.count(user) // 500) if user else 0)

    # ---- names from the AI ----

    def _named(self, user, kept):
        """``kept`` with the AI's names put in where it gave one: each mix has ``named`` ("ai" or "sound")."""
        shelves = []
        for shelf in kept["shelves"]:
            mixes = []
            for m in shelf["mixes"]:
                name = self._names.get((user, kept["day"], m["id"], m["signature"])) if m.get("signature") else None
                mixes.append({k: v for k, v in m.items() if k != "signature"} | {"name": name or m["name"], "named": "ai" if name else "sound"})
            shelves.append(dict(shelf, mixes=mixes))
        return {k: v for k, v in kept.items() if k != "day"} | {"shelves": shelves}

    def _name_soon(self, user, day, kept):
        """Has the AI name the mixes of a kind of music that have no name yet, in the background (at once without it)."""
        wanted = [m for shelf in kept["shelves"] for m in shelf["mixes"]
                  if m.get("signature") and (user, day, m["id"], m["signature"]) not in self._names]
        token = (user, day, tuple(m["signature"] for m in wanted))
        with self._lock:
            if not wanted or token in self._naming:
                return
            self._naming.add(token)

        def work():
            try:
                described = [{"id": m["id"], "genres": m["genres"][:2], "artists": m["artists"][:3], "tags": m["tags"],
                              "energy": _word(m["energy"], ("calm", "steady", "high-energy")),
                              "mood": _word(m["mood"], ("dark", "even", "bright"))} for m in wanted]
                names = self.ai.name_mixes(described)
                with self._lock:
                    if len(self._names) > 2000:
                        self._names.clear()
                    for m in wanted:
                        if m["id"] in names:
                            self._names[(user, day, m["id"], m["signature"])] = names[m["id"]]
                if names:
                    _log.info("The AI named %d of %d mixes for %s", len(names), len(wanted), user or "nobody")
            finally:
                with self._lock:
                    self._naming.discard(token)
        if self.background:
            threading.Thread(target=work, name="mix-names", daemon=True).start()
        else:
            work()

    # ---- made ahead ----

    def remember(self, user, tz, lat=None, lon=None, server=None, size=SIZE):
        """How the app asked for ``user``'s mixes: theirs are made ahead the same way."""
        user = self.listens.who(user)
        with self._lock:
            if len(self.asked) > 50:
                self.asked.clear()
            self.asked[user] = (tz, lat, lon, server, size)

    def ahead(self, minutes=AHEAD_MINUTES, default_tz=None, servers=(None,)):
        """Makes, for each listener the app has asked for (else the one with most listens), the mixes of now and of
        ``minutes`` from now: when the part of the day or the light is about to change, the next ones are ready (and
        named) before the app asks. How many were made fresh."""
        with self._lock:
            asked = dict(self.asked)
        if not asked:
            first = next(iter(self.listeners()), None)
            asked = {first: (default_tz, None, None, server, SIZE) for server in servers} if first is not None else {}
        made = 0
        for user, (tz, lat, lon, server, size) in asked.items():
            for at in (self.now(), self.now() + minutes * 60):
                before = len(self._kept)
                try:
                    self._made(self.listens.who(user), tz or default_tz, int(at), server, lat, lon, None, None, size)
                except Exception:  # noqa: BLE001 - made again when asked; never stops the loop
                    _log.exception("The mixes for %s weren't made ahead", user or "nobody")
                    continue
                made += len(self._kept) > before
        return made

    # ---- what the listener played ----

    def _played(self, user, at, server, local, ordinal):
        """The listener's listens of songs whose sound is known (and that ``server`` has), by row of the sound's
        matrix: ``{"slots": {(part, days): {row: weight}}, "parts": {part: {…}}, "all": {…}, "last": {row: at},
        "count": {row: listens}, "recent": {row: listens in the last REPEAT_DAYS days}, "listens": how many}``."""
        index, mask = self.sound.index, self.sound._mask(server)
        slots, parts, everything, last, count, recent = {}, {}, {}, {}, {}, {}
        first_of_year, listens = {}, 0
        today = datetime.date.fromordinal(ordinal)
        day_of_year = today.timetuple().tm_yday
        for r in self.listens.book(user).rows if user else ():
            row = index.get(r[SONG]) if r[SONG] else None
            if row is None or (mask is not None and not mask[row]) or r[AT] > at:
                continue
            year, _, _, hour, weekday, day = local(r[AT])
            age = max(0, ordinal - day)
            weight = 0.5 ** (age / HALF_LIFE)
            if age > 300:  # the same weeks of an earlier year
                start = first_of_year.get(year)
                if start is None:
                    start = first_of_year[year] = datetime.date(year, 1, 1).toordinal()
                apart = abs(day - start + 1 - day_of_year)
                if min(apart, 365 - apart) <= SEASON_DAYS:
                    weight += SEASON_WEIGHT
            part = part_of(hour)
            for into in (slots.setdefault((part, days_of(weekday)), {}), parts.setdefault(part, {}), everything):
                into[row] = into.get(row, 0.0) + weight
            count[row] = count.get(row, 0) + 1
            if age <= REPEAT_DAYS:
                recent[row] = recent.get(row, 0) + 1
            if r[AT] > last.get(row, 0):
                last[row] = r[AT]
            listens += 1
        return {"slots": slots, "parts": parts, "all": everything, "last": last, "count": count, "recent": recent,
                "listens": listens}

    # ---- what a group of songs is like ----

    def _scales(self):
        """Every song's energy and valence, and each sorted, to say where a mix stands in the library."""
        if self._scale is None or self._scale[0] != self.store.writes:
            try:
                rows = self.store._rows("SELECT song_id, value, valence FROM arousal WHERE value IS NOT NULL")
            except sqlite3.OperationalError:  # no such table: a store nothing has scored the energy of
                rows = []
            self._scale = (self.store.writes, np.sort([r["value"] for r in rows]),
                           np.sort([r["valence"] for r in rows if r["valence"] is not None]),
                           {r["song_id"]: (r["value"], r["valence"]) for r in rows})
        return self._scale[1:]

    def _like(self, rows, weights=None):
        """What the songs ``rows`` are like together: ``{"energy", "mood" (0 the library's lowest … 1; None unknown),
        "genres": [most first], "tags": […], "artists": [the three most in it]}``."""
        ids = [self.sound.ids[row] for row in rows]
        weights = np.ones(len(rows)) if weights is None else np.asarray(weights, float)
        energies, valences, of = self._scales()

        def share(which, sorted_values):
            pairs = [(np.searchsorted(sorted_values, of[i][which]) / len(sorted_values), w) for i, w in zip(ids, weights)
                     if i in of and of[i][which] is not None]
            return round(float(sum(p * w for p, w in pairs) / sum(w for _, w in pairs)), 3) if len(pairs) >= 3 and len(sorted_values) else None

        energy, mood = share(0, energies), share(1, valences)
        # The genre most of its songs are in by their sound; else by their tags.
        tally = {}
        heard = self.store.heard_of(ids, genres_module.HEARD_MIN, 1)
        for song_id, weight in zip(ids, weights):
            for label, _ in heard.get(song_id, ())[:1]:
                name = label.partition("---")[2] or label
                tally[name] = tally.get(name, 0.0) + weight
        if not tally:
            tags = self.store._genres_of(ids)
            for song_id, weight in zip(ids, weights):
                for g in [g for g in tags.get(song_id, ()) if g["source"] == "tag"][:1]:
                    tally[g["label"]] = tally.get(g["label"], 0.0) + weight
        genres = [name for name, _ in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))][:3]
        tags = []
        traits = self.traits.of(ids) if self.traits is not None else {}
        if len(traits) >= 3:
            mean = lambda t: sum(v[t] for v in traits.values()) / len(traits)  # noqa: E731
            if mean("voice") < 0.35:
                tags.append("Mostly instrumental")
            elif mean("voice") > 0.8:
                tags.append("Sung")
            for trait, word in (("acoustic", "Acoustic"), ("electronic", "Electronic"), ("danceable", "Danceable")):
                if mean(trait) > 0.6:
                    tags.append(word)
        artists = {}
        for row, weight in zip(rows, weights):
            name = self.sound.rows[row]["artist"] or ""
            if name:
                artists[name] = artists.get(name, 0.0) + weight
        return {"energy": energy, "mood": mood, "genres": genres, "tags": tags,
                "artists": [name for name, _ in sorted(artists.items(), key=lambda kv: (-kv[1], kv[0]))][:3]}

    @staticmethod
    def _name(like, taken):
        """A mix's name from its sound: "Calm Indie Rock"; never one of ``taken``."""
        def band(share):
            return 0 if share < LOW else 2 if share > HIGH else 1

        word = NAMES[band(like["energy"])][1 if like["mood"] is None else band(like["mood"])] if like["energy"] is not None else None
        for genre in like["genres"] or [None]:
            name = " ".join(w for w in (word, genre) if w) or "Mix"
            if genre is None and word:
                name = f"{word} mix"
            if name not in taken:
                break
        number = 2
        while name in taken:
            name = f"{name.rstrip(' 0123456789')} {number}"
            number += 1
        taken.add(name)
        return name

    # ---- a mix's songs ----

    def _fill(self, centre, own, stale, server, size, rng, taken=(), familiar=FAMILIAR, reach=None):
        """Up to ``size`` songs around ``centre``: ``familiar`` of them from ``own`` (the listener's rows of this
        group, the heaviest first), the rest the nearest songs not in ``stale`` (played lately), in turns, none
        further off than ``reach`` (a mix is of one kind: a small library gives a shorter mix, not another kind's
        songs); ``[(row, own)]``."""
        near = self.sound.near(centre, server, wanted=min(len(self.sound.ids), size * 8 + 50))
        if reach is not None:
            near = [f for f in near if f[1] <= reach]
        wanted = min(len(own), round(size * familiar))
        pool = list(own[:wanted * 2])
        mine = sorted(rng.sample(pool, wanted), key=pool.index) if wanted else []
        avoid = set(mine) | set(stale) | set(taken)
        around = [(row, d) for row, d in near if row not in avoid][:max(0, size - wanted) * 3]
        fresh = sorted(rng.sample(around, min(len(around), size - wanted)), key=lambda f: f[1])
        distance = {row: d for row, d in near}
        found, mine_left, fresh_left = [], list(mine), list(fresh)
        while mine_left or fresh_left:  # one of the listener's own, then two around it
            if mine_left:
                row = mine_left.pop(0)
                found.append((row, distance.get(row, 1.0 - float(self.sound.matrix[row] @ centre))))
            found += [fresh_left.pop(0) for _ in range(min(2, len(fresh_left)))]
        picked = self.sound._pick(found, size, taken=set(taken), per_artist=PER_ARTIST)
        if len(picked) < size:  # an artist too often, a song twice: the next nearest fill the places
            have = {row for row, _ in picked}
            picked += self.sound._pick([f for f in near if f[0] not in have and f[0] not in avoid], size - len(picked),
                                       taken=have | set(taken), per_artist=PER_ARTIST)
        mine = set(mine)
        return [(row, row in mine) for row, _ in picked]

    def _mix(self, mix_id, picked, why, taken, name=None, like=None):
        rows = [row for row, _ in picked]
        like = like or self._like(rows)
        # What the AI's name is kept by (none for a mix with a name of its own): the same songs the same day.
        signature = None if name else hashlib.sha256(",".join(sorted(self.sound.ids[row] for row in rows)).encode()).hexdigest()[:16]
        return {"id": mix_id, "name": name or self._name(like, taken), "signature": signature, "why": why, "tags": like["tags"],
                "genres": like["genres"], "artists": like["artists"], "energy": like["energy"], "mood": like["mood"],
                "own": sum(1 for _, own in picked if own),
                "songs": [{"id": self.sound.ids[row], "title": self.sound.rows[row]["title"] or "",
                           "artist": self.sound.rows[row]["artist"] or "", "album": self.sound.rows[row]["album"] or "",
                           "own": own} for row, own in picked]}

    def _grouped(self, weights, most, k):
        """The heaviest ``most`` songs of ``weights`` (``{row: weight}``) in groups: ``[(rows heaviest first, their
        weights, the group's centre, its reach)]``."""
        top = sorted(weights, key=lambda row: (-weights[row], row))[:most]
        rows, w = np.array(top), np.array([weights[row] for row in top], np.float32)
        out = []
        for members in groups(self.sound.matrix[rows], w, k):
            order = members[np.argsort(-w[members], kind="stable")]
            own, own_w = rows[order], w[order]
            out.append((own, own_w, *self._middle(own, own_w)))
        return out

    def _middle(self, rows, weights):
        """A group's centre, and how far a mix of it reaches."""
        centre = unit((self.sound.matrix[rows] * weights[:, None]).sum(axis=0))[0]
        return centre, max(0.02, REACH * float(np.quantile(1.0 - self.sound.matrix[rows] @ centre, REACH_OF)))

    def _make(self, user, tz, at, server, part, days, sun, size, local, ordinal):
        played = self._played(user, at, server, local, ordinal)
        seed = lambda what: random.Random(int(hashlib.sha256(f"{user}|{ordinal}|{what}".encode()).hexdigest()[:12], 16))  # noqa: E731
        stale = {row for row, when in played["last"].items() if at - when < FRESH_DAYS * 86400}
        weekly = "weekdays" if days == DAYS[0] else "the weekend"
        slot = played["slots"].get((part, days), {})
        if len(slot) >= ENOUGH:
            basis, weights = "slot", slot
            based = f"From what you play in the {said(part)} on {weekly}."
        elif len(played["parts"].get(part, {})) >= ENOUGH:
            basis, weights = "part", played["parts"][part]
            based = f"From what you play in the {said(part)} on any day: not enough on {weekly} alone yet."
        elif len(played["all"]) >= A_FEW:
            basis, weights = "all", played["all"]
            based = f"From all your listening: not enough in the {said(part)} yet."
        else:
            basis, weights = "library", None
            based = "From your library: not enough of your listening is known yet. Play more and these become yours."
        mask = self.sound._mask(server)
        have = np.flatnonzero(mask) if mask is not None else np.arange(len(self.sound.ids))
        shelves, taken = [], set()  # taken: the names in one shelf, where no two are the same

        # For now: the slot's groups, the ones that suit the hour and the light first.
        if weights is None:
            rng = seed("library")
            sample = np.array(sorted(rng.sample(list(map(int, have)), min(len(have), 1500)))) if len(have) else np.array([], int)
            ones = np.ones(len(sample), np.float32)
            found = [(sample[members], ones[members], *self._middle(sample[members], ones[members]))
                     for members in groups(self.sound.matrix[sample], ones, 6)] if len(sample) >= A_FEW else []
        else:
            found = self._grouped(weights, 150, min(4, max(1, len(weights) // GROUP)))
        suits = SUITS[part] + (DARK_SUITS if sun and sun["light"] == "dark" else 0.0)
        ranked = []
        for own, own_w, centre, reach in found:
            like = self._like(own[:60], own_w[:60])
            fit = 1.0 - LEAN[basis] * 2 * abs(like["energy"] - suits) if like["energy"] is not None else 1.0
            if sun and sun["light"] == "dark" and like["mood"] is not None:  # in the dark, the brightest wait
                fit -= LEAN[basis] * max(0.0, like["mood"] - 0.5)
            ranked.append((float(own_w.sum()) / max(1e-9, sum(float(f[1].sum()) for f in found)) * max(0.05, fit), own, centre, like, reach))
        ranked.sort(key=lambda r: -r[0])
        mixes = []
        for n, (_, own, centre, like, reach) in enumerate(ranked[:4]):
            picked = self._fill(centre, list(map(int, own)) if weights is not None else [], stale, server, size, seed(f"now-{n}"), reach=reach)
            if len(picked) >= A_FEW:
                why = ("Like " + _and(like["artists"]) + ".") if like["artists"] and weights is not None else "From your library."
                mixes.append(self._mix(f"now-{n + 1}", picked, why, taken))
        note = " · ".join(x for x in (f"{weekly.capitalize()}, {hours(part)}", sun and sun["said"]) if x)
        shelves.append({"key": "now", "title": f"Your {said(part)}", "note": note, "mixes": mixes})

        # Made for you: the listener's all-time groups.
        taken = set()
        everything = played["all"]
        daily = self._grouped(everything, 300, min(5, len(everything) // GROUP)) if len(everything) >= ENOUGH else []
        mixes = []
        for n, (own, own_w, centre, reach) in enumerate(daily):
            picked = self._fill(centre, list(map(int, own)), stale, server, size, seed(f"daily-{n}"), reach=reach)
            if len(picked) >= A_FEW:
                like = self._like(own[:60], own_w[:60])
                mixes.append(self._mix(f"daily-{n + 1}", picked, "Like " + _and(like["artists"]) + "." if like["artists"] else "", taken, like=like))
        if mixes:
            shelves.append({"key": "daily", "title": "Made for you", "note": "The kinds of music you play most, each with more like it.", "mixes": mixes})

        # More of you: on repeat, to rediscover, and new.
        mixes, taken = [], set()
        repeat = sorted((row for row, n in played["recent"].items() if n >= 2), key=lambda row: (-played["recent"][row], row))[:size]
        if len(repeat) >= A_FEW:
            mixes.append(self._mix("repeat", [(row, True) for row in repeat], f"What you played most in the last {REPEAT_DAYS} days.", taken, name="On repeat"))
        forgotten = sorted((row for row, n in played["count"].items() if n >= 3 and at - played["last"][row] > FORGOTTEN_DAYS * 86400),
                           key=lambda row: (-played["count"][row], row))[:size * 3]
        if len(forgotten) >= A_FEW:
            rng = seed("rediscover")
            some = sorted(rng.sample(forgotten, min(len(forgotten), size)), key=forgotten.index)
            picked = self.sound._pick([(row, 0.0) for row in some], size, per_artist=PER_ARTIST + 1)
            if len(picked) >= A_FEW:
                mixes.append(self._mix("rediscover", [(row, True) for row, _ in picked], "Songs you played a lot, and not for six months.", taken, name="Rediscover"))
        if daily:
            ever, fresh, each = set(played["count"]), [], max(A_FEW, size // len(daily))
            for n, (_, _, centre, reach) in enumerate(daily):
                fresh += self._fill(centre, [], ever, server, each, seed(f"new-{n}"), taken={row for row, _ in fresh}, reach=reach)
            rng = seed("new")
            rng.shuffle(fresh)
            picked = self.sound._pick([(row, 0.0) for row, _ in fresh], size, per_artist=PER_ARTIST)
            if len(picked) >= A_FEW:
                mixes.append(self._mix("new", [(row, False) for row, _ in picked], "Never played by you, and close to what you play.", taken, name="New for you"))
        if mixes:
            shelves.append({"key": "more", "title": "More of you", "note": "", "mixes": mixes})
        return {"day": ordinal, "part": part, "days": days, "said": said(part), "hours": hours(part), "basis": basis, "based": based,
                "listens": played["listens"], "songs": int(len(have)), "daylight": sun, "shelves": shelves}


def _word(share, words):
    """``share`` (0 to 1, or None) as one of three ``words``."""
    if share is None:
        return None
    return words[0] if share < LOW else words[2] if share > HIGH else words[1]


def _and(names):
    """"A", "A and B", "A, B and C"."""
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""
