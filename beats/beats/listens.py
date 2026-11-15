"""What was listened to, and when (0.29, the owner, 11 Nov: Siansa Beats keeps the listening history itself, so no
other history service is needed beside it).

- **Listens** come from the Siansa app as they happen ("Scrobble to Siansa Beats"), and from files: an export of
  Koito, of Last.fm (the JSON or CSV of the usual export tools) or of ListenBrainz (:func:`read_export`). The same
  listen twice (the same listener, second, artist and title) is kept once, so a file can be brought in again and two
  services' exports of the same years don't count double.
- Each listen is one **listener**'s (the music server's user name the app scrobbles as; chosen for a file): two
  people on one server have a history each.
- A listen is linked to the song here when there is one (by the app's id for it, or by artist and title for a file),
  so the app can be given ids to play.
- **The numbers** for a month, a year or all time (:meth:`Listens.summary`): totals, the most played songs, artists
  and albums, when in the day and week, the days, records. Days, months and hours are the listener's clock's (the
  browser says which time zone), not the container's.
- **On to Last.fm** (:class:`LastFm`, :meth:`Listens.relay`): a listener's new listens are sent on to their Last.fm
  account, with their own API account, in the background and again later when Last.fm can't be reached. Listens from
  a file never are.

Plain Python and the database of :mod:`beats.store`.
"""

import bisect
import csv
import datetime
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

from . import log

_log = log.get("listens")

SCHEMA = """
CREATE TABLE IF NOT EXISTS listens (
    id INTEGER PRIMARY KEY, user TEXT NOT NULL, at INTEGER NOT NULL, artist TEXT NOT NULL, title TEXT NOT NULL,
    album TEXT, duration INTEGER, song_id TEXT, source TEXT, client TEXT, akey TEXT NOT NULL, tkey TEXT NOT NULL,
    relayed INTEGER,  -- to Last.fm: NULL not to be sent, 0 waiting, 1 sent, 2 turned away, 3 too old to send
    album_artist TEXT,  -- 0.37: the album's artist, which Last.fm needs to find a collaboration's or compilation's cover
    UNIQUE (user, at, akey, tkey)
);
CREATE INDEX IF NOT EXISTS listens_by_artist ON listens (user, akey, at);
CREATE INDEX IF NOT EXISTS listens_waiting ON listens (relayed, user) WHERE relayed = 0;
"""

A_FEW_LISTENS = 20  # more than this added at once is a history brought in, not the app's listens as they come
SLOW_SUMMARY = 0.25  # seconds: numbers that took this long are given old at once and worked out again behind

SOURCES = {"siansa": "the Siansa app", "koito": "Koito", "lastfm": "Last.fm", "listenbrainz": "ListenBrainz"}
MOST_AT_ONCE = 500  # listens in one request from the app
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
FIRST_YEAR = 2002  # Last.fm started counting then: a listen from before is a broken date
TYPICAL_SECONDS = 210  # a listen whose song's length nothing says


def key(name):
    """A name as it's compared: any case, no spaces or punctuation ("AC/DC" and "ac dc" are one)."""
    return re.sub(r"[\W_]+", "", (name or "").casefold())


def zone(name):
    """The time zone ``name`` (IANA, "Europe/Helsinki"), or UTC when there's no such one here."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name) if name else datetime.timezone.utc
    except Exception:  # no such zone, or no zone data in this Python
        return datetime.timezone.utc


# ---- files ----

class CantRead(Exception):
    """A file that isn't an export this can read: says why, for the page."""


def _when(value):
    """Seconds since 1970 from what an export gives: a number (seconds, or milliseconds), or a written date (read as
    UTC when it names no zone). None when it's neither."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or re.fullmatch(r"\d{9,13}", str(value).strip()):
        number = float(value)
        return int(number / 1000 if number > 1e11 else number)
    text = str(value).strip()
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
        for pattern in ("%d %b %Y %H:%M", "%d %b %Y, %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
            try:
                parsed = datetime.datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return int(parsed.timestamp())


def _text(value):
    """What an export says a name is: Last.fm's own shape is ``{"#text": …}``."""
    if isinstance(value, dict):
        value = value.get("#text") or value.get("name") or ""
    return str(value or "").strip()


def _primary(aliases):
    """Koito's name of a thing: its primary alias, else its first."""
    aliases = [a for a in aliases or [] if isinstance(a, dict) and a.get("alias")]
    for a in aliases:
        if a.get("is_primary"):
            return str(a["alias"]).strip()
    return str(aliases[0]["alias"]).strip() if aliases else ""


def _koito(data):
    for item in data.get("listens") or []:
        track, artists = item.get("track") or {}, item.get("artists") or []
        names = [_primary(a.get("aliases")) for a in sorted(artists, key=lambda a: not a.get("is_primary"))]
        yield {"at": _when(item.get("listened_at")), "artist": next((n for n in names if n), ""),
               "title": _primary(track.get("aliases")), "album": _primary((item.get("album") or {}).get("aliases")),
               "duration": track.get("duration") or None, "client": item.get("client")}


def _lastfm_tracks(tracks):
    for t in tracks or []:
        if not isinstance(t, dict):
            continue
        date = t.get("date") if isinstance(t.get("date"), dict) else {}
        if not date and (t.get("@attr") or {}).get("nowplaying"):
            continue  # what was playing while the export ran: not a listen yet
        yield {"at": _when(date.get("uts") or t.get("uts") or t.get("date")), "artist": _text(t.get("artist")),
               "title": _text(t.get("name") or t.get("track")), "album": _text(t.get("album"))}


def _listenbrainz(items):
    for item in items:
        meta = item.get("track_metadata") or {}
        extra = meta.get("additional_info") or {}
        ms = extra.get("duration_ms") or (extra.get("duration") or 0) * 1000
        yield {"at": _when(item.get("listened_at")), "artist": _text(meta.get("artist_name")),
               "title": _text(meta.get("track_name")), "album": _text(meta.get("release_name")),
               "duration": int(ms / 1000) if ms else None, "client": extra.get("media_player")}


def _json_rows(data):
    """``(format, rows)`` of an export read as JSON."""
    if isinstance(data, dict):
        if isinstance(data.get("listens"), list):
            return "koito", _koito(data)
        if isinstance(data.get("scrobbles"), list):  # lastfmstats.com
            return "lastfm", _lastfm_tracks(data["scrobbles"])
        if isinstance(data.get("track"), list):  # one page of Last.fm's own answer
            return "lastfm", _lastfm_tracks(data["track"])
        if isinstance((data.get("recenttracks") or {}).get("track"), list):
            return "lastfm", _lastfm_tracks(data["recenttracks"]["track"])
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and "track_metadata" in first:
            return "listenbrainz", _listenbrainz(data)
        if isinstance(first, dict) and isinstance(first.get("track"), list):  # the export tool's pages
            return "lastfm", (row for page in data for row in _lastfm_tracks(page.get("track")))
        if isinstance(first, list):
            return "lastfm", (row for page in data for row in _lastfm_tracks(page))
        if isinstance(first, dict) and ("artist" in first or "name" in first):
            return "lastfm", _lastfm_tracks(data)
    raise CantRead("This JSON isn't an export of Koito, Last.fm or ListenBrainz that Siansa Beats knows")


COLUMNS = {"artist": ("artist", "artist_name", "artistname"), "title": ("track", "title", "name", "track_name", "song"),
           "album": ("album", "album_name", "release_name"), "at": ("uts", "date", "utc_time", "timestamp", "time", "listened_at")}


def _csv_rows(text):
    """An export as a table: with a first line naming the columns, or the four of the oldest export tool (artist,
    album, title, date)."""
    first = text.split("\n", 1)[0]
    delimiter = max(",;\t", key=first.count)
    lines = csv.reader(text.splitlines(), delimiter=delimiter)
    head = next(lines, None)
    if head is None:
        raise CantRead("The file is empty")
    names = [re.sub(r"[^a-z_]", "", h.strip().lower().replace(" ", "_")) for h in head]
    where = {field: next((names.index(n) for n in options if n in names), None) for field, options in COLUMNS.items()}
    if where["artist"] is None or where["title"] is None or where["at"] is None:
        if len(head) >= 4 and _when(head[3]) is not None:  # no first line: artist, album, title, date
            where, lines = {"artist": 0, "album": 1, "title": 2, "at": 3}, _chain([head], lines)
        else:
            raise CantRead("This table has no artist, track and date columns: is it an export of Last.fm?")

    def rows():
        for line in lines:
            if len(line) <= max(v for v in where.values() if v is not None):
                continue
            yield {"at": _when(line[where["at"]]), "artist": line[where["artist"]].strip(),
                   "title": line[where["title"]].strip(),
                   "album": line[where["album"]].strip() if where.get("album") is not None else ""}
    return "lastfm", rows()


def _chain(first, rest):
    yield from first
    yield from rest


def read_export(path):
    """``(format, rows)`` of the export file at ``path``: ``format`` is "koito", "lastfm" or "listenbrainz", ``rows``
    gives ``{"at", "artist", "title", "album", "duration", "client"}`` (a listen without a date, artist or title is
    left out by :meth:`Listens.add`). :class:`CantRead` when it's none of them."""
    with open(path, "rb") as f:
        start = f.read(64).lstrip(b"\xef\xbb\xbf \t\r\n")
    if start[:2] == b"PK":
        raise CantRead("That's a zip: unpack it and choose the file inside")
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        if start[:1] in (b"{", b"["):
            try:
                return _json_rows(json.load(f))
            except ValueError:
                f.seek(0)
                try:  # ListenBrainz's own export: a listen a line
                    return "listenbrainz", _listenbrainz([json.loads(line) for line in f if line.strip()])
                except ValueError:
                    raise CantRead("The file starts like JSON but isn't") from None
        return _csv_rows(f.read())


# ---- Last.fm ----

class LastFmError(Exception):
    """Last.fm said no, or couldn't be reached: ``code`` is its error number (None when it didn't answer)."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class LastFm:
    """Last.fm's scrobbling API with the listener's own API account (key and shared secret), as the Siansa app's."""

    URL = "https://ws.audioscrobbler.com/2.0/"
    MOST = 50  # scrobbles in one request
    OLDEST = 14 * 86400  # Last.fm turns away a listen older than two weeks
    LATER = (8, 11, 16, 29)  # its errors that mean "try again later"

    def __init__(self, opener=None):
        self.open = opener or urllib.request.urlopen

    def call(self, params, secret):
        """One signed request; the answer as JSON. Never logs the parameters (a password or a session is in them)."""
        signature = hashlib.md5(("".join(k + str(params[k]) for k in sorted(params)) + secret).encode()).hexdigest()
        body = urllib.parse.urlencode({**params, "api_sig": signature, "format": "json"}).encode()
        request = urllib.request.Request(self.URL, data=body, headers={"User-Agent": "SiansaBeats"})
        try:
            with self.open(request, timeout=20) as response:
                raw = response.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LastFmError(f"Last.fm couldn't be reached: {getattr(e, 'reason', e)}") from None
        try:
            answer = json.loads(raw)
        except ValueError:
            raise LastFmError("Last.fm's answer isn't JSON") from None
        if isinstance(answer, dict) and answer.get("error"):
            raise LastFmError(f"Last.fm: {answer.get('message') or answer['error']}", int(answer["error"]))
        return answer

    def session(self, api_key, secret, name, password):
        """Signs in once and gives the session key to keep; the password isn't kept."""
        answer = self.call({"method": "auth.getMobileSession", "username": name, "password": password,
                            "api_key": api_key}, secret)
        found = (answer.get("session") or {}).get("key")
        if not found:
            raise LastFmError("Last.fm sent no session")
        return found

    def scrobble(self, keys, rows):
        """Sends up to :attr:`MOST` listens (``{"at", "artist", "title", "album", "duration"}``)."""
        params = {"method": "track.scrobble", "api_key": keys["api_key"], "sk": keys["session"]}
        for i, r in enumerate(rows[:self.MOST]):
            params[f"artist[{i}]"], params[f"track[{i}]"], params[f"timestamp[{i}]"] = r["artist"], r["title"], str(r["at"])
            if r.get("album"):
                params[f"album[{i}]"] = r["album"]
            if r.get("album_artist"):
                params[f"albumArtist[{i}]"] = r["album_artist"]
            if r.get("duration"):
                params[f"duration[{i}]"] = str(r["duration"])
        return self.call(params, keys["secret"])

    def love(self, keys, artist, title, loved=True):
        """Loves a song on Last.fm (or takes the love back)."""
        return self.call({"method": "track.love" if loved else "track.unlove", "api_key": keys["api_key"],
                          "sk": keys["session"], "artist": artist, "track": title}, keys["secret"])

    def now_playing(self, keys, row):
        params = {"method": "track.updateNowPlaying", "api_key": keys["api_key"], "sk": keys["session"],
                  "artist": row["artist"], "track": row["title"]}
        if row.get("album"):
            params["album"] = row["album"]
        if row.get("album_artist"):
            params["albumArtist"] = row["album_artist"]
        if row.get("duration"):
            params["duration"] = str(row["duration"])
        return self.call(params, keys["secret"])


# ---- in memory ----

AT, ID, ARTIST, TITLE, ALBUM, DURATION, SONG, AKEY, TKEY, CREDITS = range(10)  # what a listen is in a Book


class Library:
    """What Listening needs of the songs here, read once per library read: each song's length and its artists as its
    server lists them, and the artists of a credit line ("A feat. B") for a listen that names no song here."""

    def __init__(self, store, version):
        self.version, self.durations, self.artists, self.by_line = version, {}, {}, {}
        for r in store._rows("SELECT id, duration, artist, artists FROM songs"):
            if r["duration"]:
                self.durations[r["id"]] = r["duration"]
            if r["artists"]:
                try:
                    names = tuple(str(n) for n in json.loads(r["artists"]) if n)
                except ValueError:
                    continue
                if names:
                    self.artists[r["id"]] = names
                    if len(names) > 1 and r["artist"]:
                        self.by_line.setdefault(key(r["artist"]), names)

    def names(self, song_id, akey):
        """The artists of a listen of ``song_id`` (or, without one, of the credit line compared as ``akey``): None
        when nothing here says."""
        return (self.artists.get(song_id) if song_id else None) or self.by_line.get(akey)


class Book:
    """One listener's listens in memory, oldest first, as they were at one moment: never changed, a newer one takes
    its place (0.47: the page's numbers read 69,000 rows from the database, several times over, for every period
    opened). A listen counts for each of its artists (``CREDITS``: ``((as compared, name), …)``, the first one the
    song's own), not for the line they're written in."""

    def __init__(self, rows, top, seen, library):
        self.rows, self.ats, self.top, self.seen, self.library = rows, [r[AT] for r in rows], top, seen, library
        self._lengths = self._artists = None

    def between(self, start, end):
        return self.rows[bisect.bisect_left(self.ats, start):bisect.bisect_left(self.ats, end)]

    def lengths(self):
        """``{(artist line, title) as compared: the longest length a listen of it came with}``."""
        if self._lengths is None:
            found = {}
            for r in self.rows:
                if r[DURATION] and r[DURATION] > found.get((r[AKEY], r[TKEY]), 0):
                    found[(r[AKEY], r[TKEY])] = r[DURATION]
            self._lengths = found
        return self._lengths

    def artists(self):
        """``{artist as compared: [first listen's second, listens, name, whether a song here says the name]}``, all
        time."""
        if self._artists is None:
            found = {}
            for r in self.rows:
                for akey, name in r[CREDITS]:
                    one = found.get(akey)
                    if one is None:
                        found[akey] = [r[AT], 1, name, bool(r[SONG])]
                    else:
                        one[1] += 1
                        if r[SONG] or not one[3]:  # as the library writes the name, over a file's or an old tag's
                            one[2], one[3] = name, bool(r[SONG])
            self._artists = found
        return self._artists

    def length(self, r):
        """A listen's length: its own, else its song's from another listen or from the library, else None."""
        return r[DURATION] or self.lengths().get((r[AKEY], r[TKEY])) or self.library.durations.get(r[SONG])


# ---- the history ----

class Listens:
    def __init__(self, store, vault=None, lastfm=None, now=time.time):
        self.store, self.vault, self.lastfm, self.now = store, vault, lastfm or LastFm(), now
        with store._write():
            store.db.executescript(SCHEMA)
            if "album_artist" not in {r[1] for r in store.db.execute("PRAGMA table_info(listens)")}:
                store.db.execute("ALTER TABLE listens ADD COLUMN album_artist TEXT")
        self.changes = 0  # counts every change, so kept numbers know when they're old
        self.playing = {}  # listener -> {"artist", "title", "album", "at"}: what the app says is playing
        self.importing = {"running": False}
        self.relay_state = {}  # listener -> {"error", "at"}: the last trouble sending on to Last.fm
        self._kept, self._lock = {}, threading.Lock()
        self._working = set()  # the summaries being worked out again in the background
        self._relay_lock = threading.Lock()
        self._names = (None, [])  # (the change they were read at, the listeners with a listen kept)
        self._books, self._forgot = {}, 0  # listener -> Book; counts the times everything in memory was dropped
        self._library_kept = None
        self._clock = {}  # time zone -> {quarter of an hour since 1970: (year, month, day, hour, weekday, day number)}
        self._keys_kept = {}  # a name -> as compared
        self._marked = 0  # counts the changes to what's sent on to Last.fm
        self._people = self._sent = None
        self._join_names()

    # ---- who ----

    def _listeners(self):
        if self._names[0] != self.changes:
            self._names = (self.changes, [r["user"] for r in self.store._rows(
                "SELECT user FROM listens GROUP BY user ORDER BY COUNT(*) DESC")])
        return self._names[1]

    def who(self, user):
        """The listener ``user`` means: a name is the same whatever its capitals ("Max" typed on the TV is the
        phone's "max", as it is for the music server), so one person's listens stay together and go on to their
        Last.fm (issue 1178 of the app). The one who sends on to Last.fm first, then the one with the most listens."""
        user = str(user or "").strip()
        known = list(self._relays()) + self._listeners()
        if not user or user in known:
            return user
        folded = user.casefold()
        return next((name for name in known if name.casefold() == folded), user)

    def _join_names(self):
        """Listens kept under one name in different capitals, from before :meth:`who`, become one listener's. Left
        alone when two of the names each send on to their own Last.fm."""
        relays, groups = self._relays(), {}
        for name in list(relays) + self._listeners():
            if name not in groups.setdefault(name.casefold(), []):
                groups[name.casefold()].append(name)
        for names in groups.values():
            if len(names) < 2 or sum(1 for n in names if n in relays) > 1:
                continue
            for other in names[1:]:  # the first: the one who sends on, or else the one with the most listens
                self.rename(other, names[0])

    # ---- in memory ----

    def library(self):
        kept = self._library_kept
        if kept is None or kept.version != self.store.library_changes:
            if kept is not None:
                self.changes += 1  # a library was read: numbers kept from before are old (a song's artists may be new)
            kept = self._library_kept = Library(self.store, self.store.library_changes)
        return kept

    def _key(self, name):
        got = self._keys_kept.get(name)
        if got is None:
            if len(self._keys_kept) > 200000:
                self._keys_kept.clear()
            got = self._keys_kept[name] = key(name) or name.casefold()
        return got

    def _row(self, r, library):
        names = library.names(r["song_id"], r["akey"]) or (r["artist"],)
        credits = tuple({self._key(n): n for n in names}.items())
        return (r["at"], r["id"], r["artist"], r["title"], r["album"], r["duration"], r["song_id"], r["akey"], r["tkey"],
                credits)

    def book(self, user):
        """``user``'s listens in memory, as they are now: read whole once, then only what came since."""
        library = self.library()
        with self._lock:
            book, forgot = self._books.get(user), self._forgot
        seen = self.changes
        if book is not None and book.library is library and book.seen == seen:
            return book
        columns = "SELECT at, id, artist, title, album, duration, song_id, akey, tkey FROM listens "
        if book is None or book.library is not library:
            rows = [self._row(r, library) for r in self.store._rows(columns + "WHERE user=? ORDER BY at, id", (user,))]
        else:
            new = [self._row(r, library) for r in self.store._rows(columns + "WHERE id>? AND user=? ORDER BY at, id",
                                                                   (book.top, user))]
            if not new:
                book.seen = seen
                return book
            rows = book.rows + new
            if book.ats and new[0][AT] < book.ats[-1]:  # a listen from before the last one (kept by the app while offline)
                rows.sort(key=lambda r: (r[AT], r[ID]))
        book = Book(rows, max((r[ID] for r in rows), default=0), seen, library)
        with self._lock:
            if forgot == self._forgot:  # nothing was removed or renamed meanwhile
                if len(self._books) > 8:
                    self._books.clear()
                self._books[user] = book
        return book

    def _local(self, tz_name):
        """``at -> (year, month, day, hour, weekday, day number)`` on the clock of ``tz_name``, worked out once per
        quarter of an hour (a zone's clock is a whole number of them from UTC)."""
        tz = zone(tz_name)
        if len(self._clock) > 6:
            self._clock.clear()
        cache = self._clock.setdefault(str(tz_name or ""), {})
        if len(cache) > 400000:
            cache.clear()

        def local(at):
            got = cache.get(at // 900)
            if got is None:
                d = datetime.datetime.fromtimestamp(at, tz)
                got = cache[at // 900] = (d.year, d.month, d.day, d.hour, d.weekday(), d.toordinal())
            return got
        return local

    def warm(self, user, tz_name=None):
        """Reads ``user``'s listens into memory and works out all time's numbers, in the background (at the start:
        the first opening of Listening doesn't wait for them)."""
        def work():
            try:
                self.summary(user, None, None, tz_name)
            except Exception:  # nothing here may take the service down
                _log.exception("Getting Listening ready went wrong")
        threading.Thread(target=work, name="listens-warm", daemon=True).start()

    def first_artist(self, artist, song_id=None):
        """The artist Last.fm is told: the song's first one, not the line that credits a guest too ("A feat. B")."""
        names = self.library().names(song_id, key(artist))
        return names[0] if names else artist

    # ---- keeping ----

    def add(self, user, rows, source="siansa", server=None):
        """Keeps ``rows`` (``{"at", "artist", "title", "album", "duration", "id" (a server's id for the song),
        "client"}``) as ``user``'s listens: ``{"kept", "known", "skipped"}``; ``known``: already here, ``skipped``:
        without a date, artist or title."""
        user = self.who(user)
        rows = list(rows)
        latest, year = self.now() + 86400, datetime.datetime(FIRST_YEAR, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
        by_id = self.store.resolve([str(r["id"]) for r in rows if r.get("id")], server) if source == "siansa" else {}
        songs = None
        relay = 0 if source == "siansa" and self.relays(user) else None
        values, skipped = [], 0
        for r in rows:
            at, artist, title = r.get("at"), str(r.get("artist") or "").strip(), str(r.get("title") or "").strip()
            if not isinstance(at, (int, float)) or not year <= at <= latest or not artist or not title:
                skipped += 1
                continue
            akey, tkey = key(artist) or artist.casefold(), key(title) or title.casefold()
            song_id = by_id.get(str(r.get("id"))) if r.get("id") else None
            if song_id is None:
                if songs is None:
                    songs = self._songs()
                song_id = songs.get((akey, tkey))
            try:
                duration = int(float(r.get("duration") or 0)) or None
            except (TypeError, ValueError):
                duration = None
            values.append((user, int(at), artist, title, str(r.get("album") or "").strip() or None, duration, song_id,
                           source, str(r.get("client") or "")[:80] or None, akey, tkey, relay,
                           str(r.get("album_artist") or "").strip() or None))
        before = self.count(user)
        with self.store._write():
            self.store.db.executemany(
                "INSERT OR IGNORE INTO listens (user, at, artist, title, album, duration, song_id, source, client, "
                "akey, tkey, relayed, album_artist) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
        kept = self.count(user) - before
        if kept:
            self.changes += 1
            if kept > A_FEW_LISTENS:  # a history brought in: the old numbers would be far off
                self._forget_kept()
        return {"kept": kept, "known": len(values) - kept, "skipped": skipped}

    def _songs(self):
        """``{(artist, title) as compared: song id}`` of the songs here, to link a listen that came without an id."""
        return {(key(r["artist"]), key(r["title"])): r["id"]
                for r in self.store._rows("SELECT id, artist, title FROM songs WHERE title IS NOT NULL")}

    def count(self, user=None):
        if user is None:
            return self.store._rows("SELECT COUNT(*) AS n FROM listens")[0]["n"]
        return self.store._rows("SELECT COUNT(*) AS n FROM listens WHERE user=?", (user,))[0]["n"]

    def users(self):
        """The listeners, most listens first: ``[{"user", "listens", "first", "last", "sources", "lastfm"}]``."""
        stamp = (self.changes, self._forgot)
        kept = self._people
        if kept is None or kept[0] != stamp:  # kept until a listen comes: two counts of every listen, at each opening
            rows = self.store._rows("SELECT user, COUNT(*) AS listens, MIN(at) AS first, MAX(at) AS last FROM listens "
                                    "GROUP BY user ORDER BY listens DESC")
            sources = {}
            for r in self.store._rows("SELECT user, source, COUNT(*) AS n FROM listens GROUP BY user, source"):
                sources.setdefault(r["user"], {})[r["source"] or "siansa"] = r["n"]
            kept = self._people = (stamp, rows, sources)
        rows, sources = kept[1], kept[2]
        relays = self._relays()
        # Also who's playing now or sends on to Last.fm without a listen kept yet: the app's listener shows at once.
        names = [r["user"] for r in rows]
        names += [u for u in list(self.playing) + list(relays) if u not in names]
        by = {r["user"]: dict(r) for r in rows}
        return [{"user": u, "listens": 0, "first": None, "last": None, **by.get(u, {}), "sources": sources.get(u, {}),
                 "lastfm": self.lastfm_status(u)} for u in names]

    def set_playing(self, user, row, song_id=None):
        """What the app says is playing for ``user`` now (shown on the page, and said to Last.fm); ``song_id``: the
        song here, for its cover."""
        user = self.who(user)
        artist, title = str(row.get("artist") or "").strip(), str(row.get("title") or "").strip()
        if not artist or not title:
            return False
        try:
            duration = int(float(row.get("duration") or 0)) or None
        except (TypeError, ValueError):
            duration = None
        playing = {"artist": artist, "title": title, "album": str(row.get("album") or "").strip() or None,
                   "album_artist": str(row.get("album_artist") or "").strip() or None,
                   "duration": duration, "at": int(self.now()), "song": song_id}
        self.playing[user] = playing
        keys = self._keys(user)
        if keys:
            said = dict(playing, artist=self.first_artist(artist, song_id))
            threading.Thread(target=self._say_playing, args=(user, keys, said), name="lastfm-now", daemon=True).start()
        return True

    def _say_playing(self, user, keys, playing):
        try:
            self.lastfm.now_playing(keys, playing)
            if (self.relay_state.get(user) or {}).get("playing"):
                self.relay_state.pop(user, None)
        except LastFmError as e:
            # Said on the page's Last.fm line too, not only in the detailed log (the owner, 11 Nov).
            self.relay_state[user] = {"error": f"Last.fm wasn't told what's playing: {e}", "at": self.now(), "playing": True}
            _log.warning("Last.fm wasn't told what %s is playing: %s", user or "the listener", e)

    def all_playing(self):
        """``[{"user", "artist", "title", …}]``: what's playing now for each listener."""
        return [dict(self.now_playing(u), user=u) for u in list(self.playing) if self.now_playing(u)]

    def rename(self, old, new):
        """Makes ``old``'s listens ``new``'s (a history brought in without a name, then the app's listens under the
        music server's user name: the owner, 11 Nov). A listen both have is kept once; sending on to Last.fm moves
        too unless ``new`` has its own. How many listens moved."""
        old, new = str(old or "").strip(), str(new or "").strip()
        if old == new:
            return 0
        with self.store._write():
            moved = self.store.db.execute("UPDATE OR IGNORE listens SET user=? WHERE user=?", (new, old)).rowcount
            self.store.db.execute("DELETE FROM listens WHERE user=?", (old,))  # the ones new had already
        relays = dict(self._relays())
        if old in relays:
            mine = relays.pop(old)
            relays.setdefault(new, mine)
            self.store.set_setting("lastfm_relay", relays)
        since = (relays.get(new) or {}).get("since")
        if since:  # the app's listens since sending on was connected (under the other name) go on now
            with self.store._write():
                self.store.db.execute("UPDATE listens SET relayed=0 WHERE user=? AND source='siansa' AND relayed IS NULL "
                                      "AND at>=?", (new, since))
            self._marked += 1
        self.changes += 1
        self._forget_kept()
        self.store.event(f"The listens of {old or 'no name'} are {new or 'no name'}'s now ({moved} moved)")
        return moved

    def now_playing(self, user):
        """What's playing for ``user``, while it can still be: said within the song's length (10 minutes without)."""
        user = self.who(user)
        playing = self.playing.get(user)
        if playing and self.now() - playing["at"] <= (playing.get("duration") or 600) + 30:
            return playing
        return None

    # ---- files ----

    def start_import(self, path, user, name=None, done=None):
        """Brings the export at ``path`` in as ``user``'s, in a thread (a long history takes a while); ``done`` is
        called after it, whatever came of it. False when one runs already."""
        with self._lock:
            if self.importing.get("running"):
                return False
            self.importing = {"running": True, "file": name, "user": user, "started": self.now(), "read": 0}
        threading.Thread(target=self._import, args=(path, user, name, done), name="listens-import", daemon=True).start()
        return True

    def _import(self, path, user, name, done):
        state = {"running": False, "file": name, "user": user, "finished": None}
        try:
            state.update(self.import_file(path, user))
            self.store.event(f"{state['kept']} listens of {SOURCES.get(state['format'], state['format'])} were brought in"
                             + (f" for {user}" if user else "") + (f" ({state['known']} were here already)" if state["known"] else ""))
        except CantRead as e:
            state["error"] = str(e)
        except Exception as e:  # nothing here may take the service down
            state["error"] = f"{type(e).__name__}: {e}"
            _log.exception("Bringing in %s failed", name)
        state["finished"] = self.now()
        self.importing = state
        if done:
            done()

    def import_file(self, path, user):
        """One export, in this thread: ``{"format", "kept", "known", "skipped", "first", "last"}``."""
        kind, rows = read_export(path)
        sums, first, last, chunk = {"kept": 0, "known": 0, "skipped": 0}, None, None, []

        def keep():
            for k, v in self.add(user, chunk, source=kind).items():
                sums[k] += v
            self.importing = dict(self.importing, read=sums["kept"] + sums["known"] + sums["skipped"])
            chunk.clear()

        for row in rows:
            if isinstance(row.get("at"), int):
                first, last = min(first or row["at"], row["at"]), max(last or row["at"], row["at"])
            chunk.append(row)
            if len(chunk) >= 5000:
                keep()
        keep()
        if not sums["kept"] and not sums["known"]:
            raise CantRead("No listens were found in the file")
        _log.info("Brought in an export of %s for %s: %d listens kept, %d here already, %d without a date, artist or "
                  "title", kind, user or "the listener", sums["kept"], sums["known"], sums["skipped"])
        return {"format": kind, **sums, "first": first, "last": last}

    def remove(self, user, source=None):
        """Removes ``user``'s listens (those from ``source`` only, when given). How many went."""
        with self.store._write():
            if source:
                gone = self.store.db.execute("DELETE FROM listens WHERE user=? AND source=?", (user, source)).rowcount
            else:
                gone = self.store.db.execute("DELETE FROM listens WHERE user=?", (user,)).rowcount
        if gone:
            self.changes += 1
            self._forget_kept()
        return gone

    # ---- the numbers ----

    def window(self, year=None, month=None, tz=None):
        """``(from, to, label)``: the seconds a year or one of its months covers on the clock of ``tz``; all time
        without a year."""
        if not year:
            return 0, 2 ** 62, "All time"
        start = datetime.datetime(year, month or 1, 1, tzinfo=tz)
        end = datetime.datetime(year + (1 if not month or month == 12 else 0), 1 if not month or month == 12 else month + 1,
                                1, tzinfo=tz)
        return int(start.timestamp()), int(end.timestamp()), f"{MONTHS[month - 1]} {year}" if month else str(year)

    def top(self, user, kind="songs", start=0, end=2 ** 62, limit=50, server=None):
        """The most listened ``kind`` ("songs", "artists" or "albums") of ``user`` from ``start`` to ``end``, most
        first: ``[{"artist", "title"|"album", "listens", "id" (``server``'s for the song, when it has it)}]``. A
        listen counts for each artist on its song; an album is its first artist's."""
        user = self.who(user)
        rows = self._top(self.book(user).between(start, end), kind, max(1, min(1000, int(limit))))
        if kind == "songs":
            ids = self.store.item_ids([r["song"] for r in rows if r["song"]], server) if server else {}
            rows = [dict(r, id=ids.get(r["song"]) if server else r["song"]) for r in rows]
        return rows

    @staticmethod
    def _top(rows, kind, limit):
        found = {}  # what it's counted by -> [listens, last listen's second, the row shown]
        if kind == "artists":
            for r in rows:
                for place, (akey, name) in enumerate(r[CREDITS]):
                    one = found.get(akey)
                    if one is None:
                        one = found[akey] = [0, 0, {"artist": name, "song": None, "here": False}]
                    one[0], one[1] = one[0] + 1, r[AT]
                    if r[SONG] or not one[2]["here"]:  # as the library writes the name, over a file's or an old tag's
                        one[2]["artist"], one[2]["here"] = name, bool(r[SONG])
                    if place == 0 and r[SONG]:  # a song of their own: a guest's listen would show the host's picture
                        one[2]["song"] = r[SONG]
        elif kind == "albums":
            for r in rows:
                if r[ALBUM] is None:
                    continue
                akey, name = r[CREDITS][0]
                one = found.get((akey, r[ALBUM].casefold()))
                if one is None:
                    one = found[(akey, r[ALBUM].casefold())] = [0, 0, {"album": r[ALBUM], "artist": name, "song": None}]
                one[0], one[1] = one[0] + 1, r[AT]
                if r[SONG]:
                    one[2]["song"] = r[SONG]
        else:
            for r in rows:
                one = found.get((r[AKEY], r[TKEY]))
                if one is None:
                    one = found[(r[AKEY], r[TKEY])] = [0, 0, {"artist": r[ARTIST], "title": r[TITLE], "album": r[ALBUM],
                                                              "song": None}]
                one[0], one[1] = one[0] + 1, r[AT]
                if r[SONG]:
                    one[2]["song"] = r[SONG]
        most = sorted(found.values(), key=lambda one: (-one[0], -one[1]))[:limit]
        if kind == "artists":
            return [{"artist": one[2]["artist"], "listens": one[0], "song": one[2]["song"]} for one in most]
        if kind == "albums":
            return [{"album": one[2]["album"], "artist": one[2]["artist"], "listens": one[0], "song": one[2]["song"]}
                    for one in most]
        return [{"artist": one[2]["artist"], "title": one[2]["title"], "album": one[2]["album"], "listens": one[0],
                 "song": one[2]["song"]} for one in most]

    def totals(self, user, start=0, end=2 ** 62, tz_name=None):
        """What ``user`` listened to from ``start`` to ``end`` in numbers, for the app's reports: ``{"listens",
        "seconds", "guessed" (listens whose length is a typical one's), "artists", "songs", "albums", "new_artists"
        (heard for the first time then), "hours"}`` (listens per hour of the day in ``tz_name``)."""
        user = self.who(user)
        book, local = self.book(user), self._local(tz_name)
        rows = book.between(start, end)
        seconds = guessed = 0
        hours, artists, songs, albums = [0] * 24, set(), set(), set()
        for r in rows:
            length = book.length(r)
            if not length:
                length, guessed = TYPICAL_SECONDS, guessed + 1
            seconds += length
            hours[local(r[AT])[3]] += 1
            for akey, _ in r[CREDITS]:
                artists.add(akey)
            songs.add((r[AKEY], r[TKEY]))
            if r[ALBUM]:
                albums.add((r[CREDITS][0][0], r[ALBUM].casefold()))
        new = sum(1 for one in book.artists().values() if start <= one[0] < end)
        return {"listens": len(rows), "seconds": seconds, "guessed": guessed, "artists": len(artists), "songs": len(songs),
                "albums": len(albums), "new_artists": new, "hours": hours}

    def recent(self, user, limit=30):
        user = self.who(user)
        return [dict(r) for r in self.store._rows(
            "SELECT at, artist, title, album, source, song_id AS song FROM listens WHERE user=? ORDER BY at DESC LIMIT ?",
            (user, limit))]

    def summary(self, user, year=None, month=None, tz_name=None, most=25):
        """Everything the page shows of ``user``'s listening in a month, a year or all time; kept until a listen is
        added. Numbers that take long to work out (a long history: :data:`SLOW_SUMMARY`) are given at once even when
        a new listen has made them old (0.42.3, the owner, 13 Nov: the page took seconds to open with 69,000 listens
        while songs were analysed), and worked out again in the background for the next time; quick ones are worked
        out again there and then. What's playing and the latest listens are always the present ones. After a change
        that isn't a listen or two (a history brought in, listens removed or renamed) nothing old is given."""
        user = self.who(user)
        self.library()
        kept_as = (user, year, month, tz_name, most)
        with self._lock:
            kept = self._kept.get(kept_as)
            fresh = kept and kept[0] == self.changes
            old_but_slow = kept and not fresh and kept[2] >= SLOW_SUMMARY
            again = old_but_slow and kept_as not in self._working
            if again:
                self._working.add(kept_as)
        if fresh or old_but_slow:
            if again:
                threading.Thread(target=self._work_out, args=(kept_as,), name="listens-summary", daemon=True).start()
            return dict(kept[1], now=self.now_playing(user), recent=self.recent(user, 12))
        answer = self._work_out(kept_as)
        return dict(answer, now=self.now_playing(user), recent=self.recent(user, 12))

    def _work_out(self, kept_as):
        """Works a summary out and keeps it, with the changes it has seen and how long it took."""
        try:
            seen, started = self.changes, time.monotonic()
            answer = self._summary(*kept_as)
            with self._lock:
                if len(self._kept) > 60:
                    self._kept.clear()
                self._kept[kept_as] = (seen, answer, time.monotonic() - started)
            return answer
        finally:
            with self._lock:
                self._working.discard(kept_as)

    def _forget_kept(self):
        """After a change bigger than a listen or two: no kept summary is given again."""
        with self._lock:
            self._kept.clear()
            self._books.clear()
            self._forgot += 1

    def _summary(self, user, year, month, tz_name, most):
        start, end, label = self.window(year, month, zone(tz_name))
        book, local = self.book(user), self._local(tz_name)

        # The years and months there's something in.
        years, months = Counter(), Counter()
        for at in book.ats:
            d = local(at)
            years[d[0]] += 1
            if year and d[0] == year:
                months[d[1]] += 1

        rows = book.between(start, end)
        seconds = guessed = 0
        hours, weekdays, days = [0] * 24, [0] * 7, Counter()
        artists, songs, albums = set(), set(), set()
        for r in rows:
            length = book.length(r)
            if not length:
                length, guessed = TYPICAL_SECONDS, guessed + 1
            seconds += length
            d = local(r[AT])
            hours[d[3]] += 1
            weekdays[d[4]] += 1
            days[d[5]] += 1
            for akey, _ in r[CREDITS]:
                artists.add(akey)
            songs.add((r[AKEY], r[TKEY]))
            if r[ALBUM]:
                albums.add((r[CREDITS][0][0], r[ALBUM].casefold()))

        # Artists heard for the first time in this period, with their listens of all time.
        new_artists = sorted((one for one in book.artists().values() if start <= one[0] < end), key=lambda one: -one[1])

        if not year:
            unit, points = "year", [{"label": str(y), "listens": years[y], "year": y}
                                    for y in range(min(years), max(years) + 1)] if years else []
        elif not month:
            unit, points = "month", [{"label": MONTHS[m - 1][:3], "listens": months[m], "month": m} for m in range(1, 13)]
        else:
            last = (datetime.date(year + (month == 12), month % 12 + 1, 1) - datetime.timedelta(days=1)).day
            unit, points = "day", [{"label": str(d), "listens": days[datetime.date(year, month, d).toordinal()]}
                                   for d in range(1, last + 1)]

        streak = best = 0
        previous = None
        for day in sorted(days):
            streak = streak + 1 if previous is not None and day - previous == 1 else 1
            best, previous = max(best, streak), day
        busiest = max(days.items(), key=lambda p: p[1]) if days else None
        return {
            "user": user, "period": {"label": label, "year": year, "month": month, "zone": str(tz_name or "UTC")},
            "years": [{"year": y, "listens": n} for y, n in sorted(years.items())],
            "months": [months[m] for m in range(1, 13)] if year else None,
            "totals": {"listens": len(rows), "seconds": seconds, "guessed": guessed, "artists": len(artists),
                       "songs": len(songs), "albums": len(albums), "days": len(days), "new_artists": len(new_artists)},
            "chart": {"unit": unit, "points": points},
            "top": {kind: self._top(rows, kind, most) for kind in ("songs", "artists", "albums")},
            "new_artists": [{"artist": one[2], "listens": one[1]} for one in new_artists[:12]],
            "hours": hours, "weekdays": [{"day": WEEKDAYS[i], "listens": n} for i, n in enumerate(weekdays)],
            "records": {"busiest_day": {"date": datetime.date.fromordinal(busiest[0]).isoformat(), "listens": busiest[1]}
                        if busiest else None,
                        "streak": best,
                        "first": {"at": rows[0][AT], "artist": rows[0][ARTIST], "title": rows[0][TITLE]} if rows else None,
                        "per_day": round(len(rows) / len(days), 1) if days else 0},
            "all": {"listens": len(book.ats), "first": book.ats[0] if book.ats else None,
                    "last": book.ats[-1] if book.ats else None},
        }

    def artist(self, user, name, tz_name=None, most=20):
        """Everything the page shows of one artist in ``user``'s listening, all time: ``None`` when they never
        listened to it. Names are compared as :func:`key` does ("AC/DC" is "ac dc"). Every listen the artist is on
        counts, a guest's too; a credit line of several ("A feat. B") is its first artist."""
        user = self.who(user)
        akey = key(name)
        if not akey:
            return None
        book = self.book(user)
        if akey not in book.artists():
            line = next((r for r in reversed(book.rows) if r[AKEY] == akey), None)
            if line is None:
                return None
            akey = line[CREDITS][0][0]
        rows = [r for r in book.rows if any(c[0] == akey for c in r[CREDITS])]
        local = self._local(tz_name)
        seconds = guessed = 0
        years, hours, days = Counter(), [0] * 24, set()
        songs, albums = {}, {}  # as compared -> [listens, last, title or album, album, a song here, (songs of it)]
        for r in rows:
            length = book.length(r)
            if not length:
                length, guessed = TYPICAL_SECONDS, guessed + 1
            seconds += length
            d = local(r[AT])
            years[d[0]] += 1
            hours[d[3]] += 1
            days.add(d[5])
            one = songs.setdefault(r[TKEY], [0, 0, r[TITLE], r[ALBUM], None, r[ARTIST]])
            one[0], one[1] = one[0] + 1, r[AT]
            one[4] = r[SONG] or one[4]
            if r[ALBUM]:
                one = albums.setdefault(r[ALBUM].casefold(), [0, 0, r[ALBUM], set(), None, r[ARTIST]])
                one[0], one[1] = one[0] + 1, r[AT]
                one[3].add(r[TKEY])
                one[4] = r[SONG] or one[4]
        mine = book.artists()[akey]
        ahead = sum(1 for one in book.artists().values() if one[1] > len(rows))
        busiest = max(years.items(), key=lambda p: p[1])
        first, last = rows[0], rows[-1]
        most_first = lambda found: sorted(found.values(), key=lambda one: (-one[0], -one[1]))[:most]  # noqa: E731
        return {
            "user": user, "artist": mine[2],
            # A song of their own for the picture: a song they're a guest on would show the host's.
            "song": next((r[SONG] for r in reversed(rows) if r[SONG] and r[CREDITS][0][0] == akey), None),
            "totals": {"listens": len(rows), "seconds": seconds, "guessed": guessed, "songs": len(songs),
                       "albums": len(albums), "days": len(days),
                       "share": round(len(rows) / len(book.rows) * 100, 1) if book.rows else 0, "rank": ahead + 1},
            "first": {"at": first[AT], "title": first[TITLE]}, "last": {"at": last[AT], "title": last[TITLE]},
            "busiest_year": {"year": busiest[0], "listens": busiest[1]},
            "years": [{"year": y, "listens": years[y]} for y in range(min(years), max(years) + 1)],
            "hours": hours,
            "songs": [{"title": one[2], "album": one[3], "artist": one[5], "listens": one[0], "song": one[4]}
                      for one in most_first(songs)],
            "albums": [{"album": one[2], "artist": one[5], "listens": one[0], "songs": len(one[3]), "song": one[4]}
                       for one in most_first(albums)],
            "recent": [{"at": r[AT], "title": r[TITLE], "album": r[ALBUM], "artist": r[ARTIST], "song": r[SONG]}
                       for r in rows[:-11:-1]],
        }

    # ---- on to Last.fm ----

    def _relays(self):
        saved = self.store.setting("lastfm_relay") or {}
        return saved if isinstance(saved, dict) else {}

    def relays(self, user):
        return user in self._relays()

    def _keys(self, user):
        saved = self._relays().get(user)
        if not saved or self.vault is None:
            return None
        return {k: self.vault.open(saved.get(k)) for k in ("api_key", "secret", "session")}

    def lastfm_status(self, user):
        """``{"connected", "name", "waiting", "sent", "error"}`` of ``user``'s sending on to Last.fm; never a key."""
        saved = self._relays().get(user)
        stamp = (self.changes, self._forgot, self._marked)
        kept = self._sent
        if kept is None or kept[0] != stamp:
            found = {}
            for r in self.store._rows("SELECT user, relayed, COUNT(*) AS n FROM listens WHERE relayed IS NOT NULL "
                                      "GROUP BY user, relayed"):
                found.setdefault(r["user"], {})[r["relayed"]] = r["n"]
            kept = self._sent = (stamp, found)
        counts = kept[1].get(user, {})
        return {"connected": bool(saved), "name": (saved or {}).get("name"), "since": (saved or {}).get("since"),
                "waiting": counts.get(0, 0), "sent": counts.get(1, 0), "turned_away": counts.get(2, 0) + counts.get(3, 0),
                "error": (self.relay_state.get(user) or {}).get("error")}

    def connect_lastfm(self, user, api_key, secret, name, password):
        """Signs ``user`` in to Last.fm with their own API account and keeps the session (encrypted; the password
        isn't kept). Listens from now on are sent on. :class:`LastFmError` says why not."""
        user = self.who(user)
        api_key, secret, name = str(api_key or "").strip(), str(secret or "").strip(), str(name or "").strip()
        if not (api_key and secret and name and password):
            raise ValueError("Last.fm's API key, shared secret, user name and password are all needed")
        if self.vault is None:
            raise ValueError("Secrets can't be kept here")
        session = self.lastfm.session(api_key, secret, name, str(password))
        saved = dict(self._relays())
        saved[user] = {"api_key": self.vault.seal(api_key), "secret": self.vault.seal(secret),
                       "session": self.vault.seal(session), "name": name, "since": int(self.now())}
        self.store.set_setting("lastfm_relay", saved)
        self.relay_state.pop(user, None)
        self.store.event(f"Listens{' of ' + user if user else ''} are sent on to Last.fm ({name}) from now on")
        return self.lastfm_status(user)

    def love(self, user, artist, title, loved=True, song_id=None):
        """Passes a heart from the app on to ``user``'s Last.fm, in the background; False when they don't send on."""
        user = self.who(user)
        keys = self._keys(user)
        artist, title = str(artist or "").strip(), str(title or "").strip()
        if not keys or not all(keys.values()) or not artist or not title:
            return False
        artist = self.first_artist(artist, song_id)

        def send():
            try:
                self.lastfm.love(keys, artist, title, loved)
                _log.info("%s %s – %s on Last.fm for %s", "Loved" if loved else "Unloved", artist, title, user or "the listener")
            except LastFmError as e:
                self.relay_state[user] = {"error": f"A heart wasn't passed on: {e}", "at": self.now()}
                _log.warning("Last.fm didn't take a heart for %s: %s", user or "the listener", e)

        threading.Thread(target=send, name="lastfm-love", daemon=True).start()
        return True

    def disconnect_lastfm(self, user):
        user = self.who(user)
        saved = dict(self._relays())
        if saved.pop(user, None) is None:
            return False
        self.store.set_setting("lastfm_relay", saved)
        with self.store._write():  # what was waiting isn't sent later to another account
            self.store.db.execute("UPDATE listens SET relayed=NULL WHERE user=? AND relayed=0", (user,))
        self._marked += 1
        self.relay_state.pop(user, None)
        self.store.event(f"Listens{' of ' + user if user else ''} are no longer sent on to Last.fm")
        return True

    def relay(self):
        """Sends the waiting listens on to Last.fm, oldest first: ``{listener: sent}``. What Last.fm can't take now
        stays waiting; a listen older than two weeks, or one it turns away, is marked and left."""
        sent = {}
        with self._relay_lock:
            for user in list(self._relays()):
                keys = self._keys(user)
                if not keys or not all(keys.values()):
                    continue
                sent[user] = self._relay_user(user, keys)
        return sent

    def _relay_user(self, user, keys):
        sent = 0
        oldest = self.now() - LastFm.OLDEST
        with self.store._write():
            self.store.db.execute("UPDATE listens SET relayed=3 WHERE user=? AND relayed=0 AND at<?", (user, oldest))
        self._marked += 1
        while True:
            rows = [dict(r) for r in self.store._rows(
                "SELECT id, at, artist, title, album, album_artist, duration, song_id FROM listens WHERE user=? AND relayed=0 "
                "ORDER BY at LIMIT ?",
                (user, LastFm.MOST))]
            if not rows:
                break
            for r in rows:  # Last.fm's artist is the song's first one, not a line with its guests ("A feat. B")
                r["artist"] = self.first_artist(r["artist"], r.pop("song_id"))
            try:
                self.lastfm.scrobble(keys, rows)
            except LastFmError as e:
                if e.code is None or e.code in LastFm.LATER:
                    self.relay_state[user] = {"error": f"{e} (tried again later)", "at": self.now()}
                elif e.code in (4, 9, 10, 14, 26):  # the session or the API account is no longer taken
                    self.relay_state[user] = {"error": f"{e}: connect Last.fm again", "at": self.now()}
                else:
                    self.relay_state[user] = {"error": str(e), "at": self.now()}
                    self._mark(rows, 2)
                _log.warning("Sending %d listens on to Last.fm for %s: %s", len(rows), user or "the listener", e)
                break
            self._mark(rows, 1)
            self.relay_state.pop(user, None)
            sent += len(rows)
        if sent:
            _log.info("Sent %d listens on to Last.fm for %s", sent, user or "the listener")
        return sent

    def _mark(self, rows, state):
        with self.store._write():
            self.store.db.executemany("UPDATE listens SET relayed=? WHERE id=?", [(state, r["id"]) for r in rows])
        self._marked += 1
