"""Mixes made from a listener's own listening (beats/mixes.py): the parts of the day, the sun, groups of songs that
sound alike, and the mixes for a slot of the week, with what they fall back on when little is known."""

import datetime
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from beats import mixes as M  # noqa: E402
from beats.drive import Arousal  # noqa: E402
from beats.listens import Listens  # noqa: E402
from beats.sound import Sound  # noqa: E402
from beats.store import Store  # noqa: E402

TZ = "Europe/Helsinki"


def at(text):
    """Seconds since 1970 of ``text`` on Helsinki's clock."""
    return int(datetime.datetime.fromisoformat(text).replace(tzinfo=M.zone(TZ)).timestamp())


NOW = at("2026-11-17 06:40")  # a Tuesday, early morning, dark


class TheClockAndTheSun(unittest.TestCase):
    def test_the_parts_of_the_day(self):
        self.assertEqual([M.part_of(h) for h in (4, 5, 8, 9, 11, 12, 16, 17, 21, 22, 0)],
                         ["night", "early", "early", "morning", "morning", "afternoon", "afternoon", "evening", "evening", "night", "night"])
        self.assertEqual((M.days_of(0), M.days_of(4), M.days_of(5), M.days_of(6)), ("weekdays", "weekdays", "weekend", "weekend"))
        self.assertEqual((M.said("early"), M.hours("early"), M.hours("night")), ("early morning", "05:00–09:00", "22:00–05:00"))

    def test_a_time_zones_city(self):
        lat, lon = M.place(TZ)
        self.assertAlmostEqual(lat, 60.17, delta=0.1)
        self.assertAlmostEqual(lon, 24.97, delta=0.1)
        self.assertIsNone(M.place("Nowhere/At_All"))
        self.assertIsNone(M.place(None))
        self.assertEqual(M._coordinates("-3327-07040"), (-33.45, -70.67))

    def test_helsinki_in_november_is_dark_at_twenty_to_seven(self):
        """The owner's morning (17 Nov): "sunshine mixes at 6:40 am, it's winter and dark outside"."""
        sun = M.daylight(60.17, 24.97, NOW, TZ)
        self.assertEqual(sun["light"], "dark")
        self.assertTrue("08:10" <= sun["sunrise"] <= "08:30", sun)  # the almanac: 08:20
        self.assertTrue("15:35" <= sun["sunset"] <= "15:55", sun)  # 15:45
        self.assertEqual(sun["said"], f"Dark outside: the sun rises at {sun['sunrise']}")
        noon = M.daylight(60.17, 24.97, at("2026-11-17 12:00"), TZ)
        self.assertEqual((noon["light"], noon["said"]), ("light", f"Light outside until {noon['sunset']}"))
        evening = M.daylight(60.17, 24.97, at("2026-11-17 18:00"), TZ)
        self.assertEqual((evening["light"], evening["said"]), ("dark", f"Dark outside: the sun set at {evening['sunset']}"))

    def test_days_without_a_sunrise_or_a_sunset(self):
        polar = M.daylight(69.65, 18.96, int(datetime.datetime(2026, 12, 21, 11, tzinfo=datetime.timezone.utc).timestamp()), "Europe/Oslo")
        self.assertEqual((polar["sunrise"], polar["sunset"], polar["said"]), (None, None, "The sun doesn't rise today"))
        self.assertNotEqual(polar["light"], "light")
        midnight_sun = M.daylight(69.65, 18.96, int(datetime.datetime(2026, 6, 21, 23, tzinfo=datetime.timezone.utc).timestamp()), "Europe/Oslo")
        self.assertEqual((midnight_sun["light"], midnight_sun["said"]), ("light", "Light outside all day"))


class Groups(unittest.TestCase):
    def test_songs_that_sound_alike_are_one_group_the_heaviest_first(self):
        rng = np.random.default_rng(1)
        a, b = np.zeros(200, np.float32), np.zeros(200, np.float32)
        a[0], b[1] = 1, 1
        vectors = M.unit(np.vstack([a + rng.normal(0, 0.05, 200) for _ in range(10)] + [b + rng.normal(0, 0.05, 200) for _ in range(6)]))
        weights = np.array([1.0] * 10 + [5.0] * 6, np.float32)
        found = M.groups(vectors, weights, 2)
        self.assertEqual([sorted(map(int, g)) for g in found], [list(range(10, 16)), list(range(10))])
        # A group of one is no mix: its song joins the others.
        self.assertEqual(len(M.groups(vectors[:11], weights[:11], 2)), 1)
        self.assertEqual([sorted(map(int, g)) for g in M.groups(vectors, weights, 2)], [sorted(map(int, g)) for g in found])


class Library(unittest.TestCase):
    """Three kinds of music, 60 songs each: calm piano (low energy, dark), rock (middle), techno (high, bright)."""

    KINDS = (("piano", 0, 2.5, 3.0), ("rock", 1, 5.0, 5.0), ("techno", 2, 7.5, 7.0))

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Store(os.path.join(self.folder.name, "beats.db"))
        self.sound = Sound(self.store)
        Arousal(self.folder.name, self.store)  # its table: each song's energy and valence
        self.clock = [NOW]
        self.listens = Listens(self.store, now=lambda: self.clock[0])
        self.mixes = M.Mixes(self.store, self.sound, self.listens, now=lambda: self.clock[0])
        rng = np.random.default_rng(7)
        for kind, axis, energy, valence in self.KINDS:
            for n in range(60):
                song = f"{kind}{n}"
                self.store.add_song({"id": song, "title": f"{kind.title()} {n}", "artist": f"{kind.title()} Artist {n % 30}",
                                     "album": "", "duration": 200, "suffix": "mp3", "tag_bpm": None, "genres": [kind.title()]})
                vector = rng.normal(0, 0.04, 200).astype(np.float32)
                vector[axis] += 1
                self.store.save_sound([{"song_id": song, "musicnn": vector.tobytes()}])
                self.store.db.execute("INSERT OR REPLACE INTO arousal (song_id, value, valence) VALUES (?, ?, ?)",
                                      (song, energy + (n % 5) * 0.1, valence + (n % 5) * 0.1))
        self.store.db.commit()
        self.store.writes += 1

    def play(self, kind, when, songs=range(30), times=1):
        rows = [{"id": f"{kind}{n}", "at": at(when) + n * 240 + t * 86400 * 7, "artist": f"{kind.title()} Artist {n % 30}",
                 "title": f"{kind.title()} {n}", "duration": 200} for n in songs for t in range(times)]
        return self.listens.add("max", rows)

    def make(self, **more):
        return self.mixes.make("max", TZ, **more)

    def kinds(self, mix):
        return {s["id"].rstrip("0123456789") for s in mix["songs"]}


class TheMixes(Library):
    def test_with_no_listening_they_come_from_the_library_the_calm_ones_first_in_the_dark(self):
        got = self.make()
        self.assertEqual((got["part"], got["days"], got["basis"], got["listens"], got["songs"]), ("early", "weekdays", "library", 0, 180))
        self.assertEqual(got["daylight"]["light"], "dark")
        self.assertEqual([s["key"] for s in got["shelves"]], ["now"])
        now = got["shelves"][0]
        self.assertEqual(now["title"], "Your early morning")
        self.assertIn("Weekdays, 05:00–09:00 · Dark outside: the sun rises at", now["note"])
        self.assertEqual(len(now["mixes"]), 3)
        self.assertEqual(self.kinds(now["mixes"][0]), {"piano"})  # calm and dark at 6:40 in November…
        self.assertEqual(self.kinds(now["mixes"][-1]), {"techno"})  # …and nothing bright and busy first
        self.assertEqual(now["mixes"][0]["name"], "Hushed Piano")
        self.assertTrue(all("sun" not in m["name"].lower() for m in now["mixes"]))
        self.assertIn("From your library", got["based"])
        # In the afternoon light the busier ones lead.
        day = self.make(at=at("2026-11-17 13:00"))
        self.assertEqual((day["part"], day["daylight"]["light"]), ("afternoon", "light"))
        self.assertNotEqual(self.kinds(day["shelves"][0]["mixes"][0]), {"piano"})

    def test_a_slots_own_listening_makes_its_mixes(self):
        """Rock on weekday early mornings, techno on weekend evenings: each slot gets what's played in it."""
        self.play("rock", "2026-11-10 06:30")
        self.play("techno", "2026-11-14 19:00")
        got = self.make()
        self.assertEqual((got["basis"], got["listens"]), ("slot", 60))
        self.assertEqual(got["based"], "From what you play in the early morning on weekdays.")
        now = got["shelves"][0]["mixes"]
        self.assertEqual(self.kinds(now[0]), {"rock"})
        self.assertEqual(now[0]["name"], "Easy Rock")
        self.assertTrue(now[0]["why"].startswith("Like Rock Artist "))
        self.assertEqual(len(now[0]["songs"]), M.SIZE)
        self.assertEqual(now[0]["own"], sum(1 for s in now[0]["songs"] if s["own"]))
        self.assertTrue(0 < now[0]["own"] <= round(M.SIZE * M.FAMILIAR))
        # No artist more than twice, no song twice.
        artists = [s["artist"] for s in now[0]["songs"]]
        self.assertLessEqual(max(artists.count(a) for a in artists), M.PER_ARTIST)
        self.assertEqual(len({s["id"] for s in now[0]["songs"]}), len(now[0]["songs"]))
        # The songs around the listener's own weren't played lately.
        self.assertTrue(all(int(s["id"][4:]) >= 30 for s in now[0]["songs"] if not s["own"]))
        weekend = self.make(at=at("2026-11-15 19:30"))  # the Sunday after
        self.assertEqual((weekend["part"], weekend["days"], weekend["basis"]), ("evening", "weekend", "slot"))
        self.assertEqual(self.kinds(weekend["shelves"][0]["mixes"][0]), {"techno"})

    def test_too_little_in_a_slot_borrows_from_the_part_of_the_day_then_from_everything(self):
        self.play("rock", "2026-11-14 06:30")  # a Saturday
        got = self.make()
        self.assertEqual(got["basis"], "part")
        self.assertEqual(got["based"], "From what you play in the early morning on any day: not enough on weekdays alone yet.")
        self.assertEqual(self.kinds(got["shelves"][0]["mixes"][0]), {"rock"})
        evening = self.make(at=at("2026-11-17 19:00"))
        self.assertEqual((evening["basis"], evening["based"]), ("all", "From all your listening: not enough in the evening yet."))

    def test_the_same_all_day_and_new_the_next(self):
        self.play("rock", "2026-11-10 06:30")
        first = self.make()
        again = self.make(at=NOW + 3600)
        ids = lambda got: [s["id"] for s in got["shelves"][0]["mixes"][0]["songs"]]  # noqa: E731
        self.assertEqual(ids(first), ids(again))
        self.clock[0] = NOW + 86400
        self.assertNotEqual(ids(first), ids(self.make()))

    def test_another_slot_can_be_looked_at(self):
        self.play("techno", "2026-11-14 19:00")
        got = self.make(part="evening", days="weekend")
        self.assertEqual((got["part"], got["days"], got["basis"], got["said"], got["hours"]), ("evening", "weekend", "slot", "evening", "17:00–22:00"))
        self.assertEqual(got["daylight"]["light"], "dark")  # this evening's sun, not this morning's
        self.assertIn("the sun set at", got["daylight"]["said"])
        self.assertEqual(got["shelves"][0]["note"].split(" · ")[0], "The weekend, 17:00–22:00")

    def test_made_for_you_on_repeat_rediscover_and_new(self):
        self.play("rock", "2026-11-10 06:30", times=1)
        self.play("rock", "2026-11-03 06:30", songs=range(12))  # twice in thirty days: on repeat
        self.play("piano", "2026-02-02 21:00", songs=range(20), times=3)  # played a lot, long ago
        got = self.make()
        shelves = {s["key"]: s for s in got["shelves"]}
        self.assertEqual(list(shelves), ["now", "daily", "more"])
        self.assertEqual(shelves["daily"]["title"], "Made for you")
        self.assertEqual({frozenset(self.kinds(m)) for m in shelves["daily"]["mixes"]}, {frozenset({"rock"}), frozenset({"piano"})})
        more = {m["id"]: m for m in shelves["more"]["mixes"]}
        self.assertEqual([m["name"] for m in shelves["more"]["mixes"]], ["On repeat", "Rediscover", "New for you"])
        self.assertEqual({s["id"] for s in more["repeat"]["songs"]}, {f"rock{n}" for n in range(12)})
        self.assertEqual(self.kinds(more["rediscover"]), {"piano"})
        self.assertTrue(all(s["own"] for s in more["rediscover"]["songs"]))
        played = {f"rock{n}" for n in range(30)} | {f"piano{n}" for n in range(20)}
        self.assertFalse({s["id"] for s in more["new"]["songs"]} & played)
        self.assertEqual(self.kinds(more["new"]), {"rock", "piano"})
        for shelf in got["shelves"]:  # no two of a shelf by the same name
            self.assertEqual(len(shelf["mixes"]), len({m["name"] for m in shelf["mixes"]}))

    def test_this_time_of_year_counts_from_earlier_years(self):
        """Piano every early morning last November, rock all spring: in November the piano is back on top."""
        self.play("piano", "2025-11-18 06:30", songs=range(26))
        self.play("rock", "2026-03-10 06:30", songs=range(26))
        self.assertEqual(self.kinds(self.make()["shelves"][0]["mixes"][0]), {"piano"})
        self.clock[0] = at("2026-07-14 06:40")
        self.assertEqual(self.kinds(self.make()["shelves"][0]["mixes"][0]), {"rock"})

    def test_nobody_and_an_empty_library(self):
        got = self.mixes.make("", TZ)
        self.assertEqual((got["user"], got["basis"]), ("", "library"))
        empty = M.Mixes(Store(os.path.join(self.folder.name, "empty.db")), None, None)
        empty.sound, empty.listens = Sound(empty.store), Listens(empty.store)
        got = empty.make("max", TZ, at=NOW)
        self.assertEqual((got["songs"], got["shelves"][0]["mixes"]), (0, []))
        self.assertEqual(self.mixes.listeners(), [])
        self.play("rock", "2026-11-10 06:30")
        self.assertEqual(self.mixes.listeners(), ["max"])

    def test_where_the_listener_is_can_be_said(self):
        """A latitude and longitude from the app: Cape Town's November morning is light."""
        got = self.mixes.make("max", TZ, lat=-33.92, lon=18.42)
        self.assertEqual(got["daylight"]["light"], "light")
        self.assertIsNone(self.mixes.make("max", "Nowhere/At_All")["daylight"])


if __name__ == "__main__":
    unittest.main()
