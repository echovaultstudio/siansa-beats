"""Mixes made from a listener's own listening (beats/mixes.py): the parts of the day, the sun, groups of songs that
sound alike, and the mixes for a slot of the week, with what they fall back on when little is known."""

import datetime
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from beats import mix_settings
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

    def test_asked_for_so_many_they_are_not_joined_to_fewer(self):
        # 0.60.6, the owner: "I said make 6 mixes but I still only see 4".
        rng = np.random.default_rng(2)
        a = np.zeros(200, np.float32)
        a[0] = 1
        vectors = M.unit(np.vstack([a + rng.normal(0, 0.05, 200) for _ in range(300)]))
        weights = np.ones(300, np.float32)
        self.assertLess(len(M.groups(vectors, weights, 6)), 6)  # one kind of music: joined to fewer
        self.assertEqual(len(M.groups(vectors, weights, 6, least=6)), 6)  # but six asked for: six


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
    def test_all_in_one_row_when_the_listener_wants_them_together(self):
        """0.62, the owner, 22 Nov: "allow choosing how many cards it sends to Siansa… I don't like the idea of always
        separating More of you and Made for you"."""
        shelves = [{"key": "now", "title": "Your evening", "note": "n", "mixes": [{"id": "now-1"}, {"id": "now-2"}]},
                   {"key": "daily", "title": "Made for you", "note": "", "mixes": [{"id": "daily-1"}, {"id": "daily-2"}]},
                   {"key": "more", "title": "More of you", "note": "", "mixes": [{"id": "repeat"}, {"id": "new"}]}]
        chosen = mix_settings.defaults()
        self.assertEqual(M.one_row(shelves, chosen), shelves)  # apart, as before, until chosen
        one = M.one_row(shelves, chosen | {"together": True, "together_count": 5})
        self.assertEqual([(s["key"], s["title"]) for s in one], [("now", "Your mixes")])
        self.assertEqual([m["id"] for m in one[0]["mixes"]], ["now-1", "now-2", "daily-1", "daily-2", "repeat"])
        # With For now switched off, the row is still in For now's place.
        self.assertEqual(M.one_row(shelves[1:], chosen | {"together": True})[0]["key"], "now")
        self.assertEqual(M.one_row([], chosen | {"together": True}), [])

    def test_a_mix_of_genres_isnt_named_for_one(self):
        """0.61.5, the owner, 22 Nov: "it's ok for songs not in the same genre to be in a mix. That's the point. But it
        shouldn't be named after the genre if it's a mix of songs" ("Clear-sky Drum n Bass" with hip hop and house)."""
        def hears(song, genre):
            self.store.db.execute("INSERT OR REPLACE INTO genres VALUES (?, 'sound', ?, 0.9)", (song, genre))
        self.make()  # reads the sound into memory
        rows = {i: n for n, i in enumerate(self.sound.ids)}
        mixed = [rows[f"piano{n}"] for n in range(10)]
        for n in range(10):  # four in ten drum and bass, the rest three other genres
            hears(f"piano{n}", "Electronic---Drum n Bass" if n < 4 else ("Hip Hop---Pop Rap", "Electronic---House", "Electronic---Dubstep")[n % 3])
        self.store.db.commit()
        like = self.mixes._like(mixed)
        self.assertEqual((like["genres"][0], like["sure"]), ("Drum n Bass", 0.4))
        name = M.Mixes._name(like, set(), set(), ["Clear-sky"], 0)
        self.assertEqual(name, "Clear-sky mix")
        self.assertNotIn("drum n bass", M._about(like))
        for n in range(4, 7):  # seven in ten: it's named for it
            hears(f"piano{n}", "Electronic---Drum n Bass")
        self.store.db.commit()
        self.assertEqual(M.Mixes._name(self.mixes._like(mixed), set(), set(), ["Clear-sky"], 0), "Clear-sky Drum n Bass")

    def test_asks_with_and_without_the_weather_get_the_same_mixes(self):
        """0.61.3, the owner: "Siansa Beats and the Siansa app not showing the same playlist" (the app said the weather,
        the page didn't, and each got its own set). The weather the app said last names the set whoever asks."""
        rainy = self.make(weather="rain")
        page = self.make()
        self.assertEqual([m["name"] for sh in page["shelves"] for m in sh["mixes"]],
                         [m["name"] for sh in rainy["shelves"] for m in sh["mixes"]])
        self.assertEqual([[x["id"] for x in m["songs"]] for m in page["shelves"][0]["mixes"]],
                         [[x["id"] for x in m["songs"]] for m in rainy["shelves"][0]["mixes"]])
        self.assertTrue(page["shelves"][0]["mixes"][0]["name"].startswith("Rainy"))

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
        # Named for the moment first (0.61): it's dark this early morning.
        self.assertEqual(now["mixes"][0]["name"], "Dark-morning Piano")
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
        self.assertEqual(now[0]["name"], "Dark-morning Rock")
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

    def test_made_again_by_hand_is_a_new_pick_and_a_new_day_starts_afresh(self):
        """0.60.4, the owner: a button to make the mixes again after changing how they're made."""
        self.play("rock", "2026-11-10 06:30")
        songs = lambda got: [[s["id"] for s in m["songs"]] for sh in got["shelves"] for m in sh["mixes"]]  # noqa: E731
        first = self.make()
        self.assertEqual(self.mixes.again("max", tz=TZ), 1)
        again = self.make()
        self.assertNotEqual(songs(first), songs(again))
        self.assertEqual(songs(again), songs(self.make()))  # kept until asked again
        self.assertEqual(self.mixes.again("max", tz=TZ), 2)
        self.assertNotEqual(songs(again), songs(self.make()))
        self.clock[0] = NOW + 86400  # the next day: picked as any day is, not as the day before's again
        next_day = self.make()
        self.assertEqual(self.mixes.again("max", tz=TZ), 1)
        self.assertNotEqual(songs(next_day), songs(self.make()))

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

    def test_no_two_mixes_shown_together_share_a_name(self):
        # 0.60.5, the owner: "the mixes are often named the same".
        class Namer:
            ready, asked = True, []

            def name_mixes(self, described, taken=()):
                self.asked.append(list(taken))
                return {d["id"]: {"name": "Velvet Undertow"} for d in described}

        self.play("rock", "2026-11-10 06:30")
        self.play("piano", "2026-02-02 21:00", songs=range(20), times=3)
        namer = Namer()
        self.mixes.ai, self.mixes.background = namer, False
        got = self.make()
        names = [m["name"].casefold() for s in got["shelves"] for m in s["mixes"]]
        self.assertEqual(len(names), len(set(names)), names)
        # One keeps the AI's name; the others their own.
        self.assertEqual(sum(m["named"] == "ai" for s in got["shelves"] for m in s["mixes"]), 1)
        # The AI was told the fixed names.
        self.assertIn("Rediscover", namer.asked[0])

    def test_the_ai_names_the_mixes_of_a_kind_and_they_are_kept_for_the_day(self):
        class Namer:
            ready, asked = True, []

            def name_mixes(self, described, taken=()):
                self.asked.append(described)
                return {d["id"]: {"name": f"Name {d['id']}", **({"about": "Wiry guitars, restless drums"} if d["id"] == "now-1" else {})}
                        for d in described if d["id"] != "daily-2"}

        self.play("rock", "2026-11-10 06:30")
        self.play("piano", "2026-02-02 21:00", songs=range(20), times=3)
        namer = Namer()
        self.mixes.ai, self.mixes.background = namer, False
        got = self.make()
        mixes = {m["id"]: m for s in got["shelves"] for m in s["mixes"]}
        self.assertEqual((mixes["now-1"]["name"], mixes["now-1"]["named"], mixes["now-1"]["about"]), ("Name now-1", "ai", "Wiry guitars, restless drums"))
        self.assertEqual(mixes["daily-1"]["about"], "Steady rock")  # named, but no line given: its sound's
        self.assertEqual((mixes["daily-2"]["named"], mixes["daily-2"]["name"]), ("sound", "Hushed Piano"))  # not named: its own
        self.assertEqual((mixes["rediscover"]["name"], mixes["rediscover"]["named"]), ("Rediscover", "sound"))
        self.assertNotIn("rediscover", [d["id"] for d in namer.asked[0]])
        self.assertTrue(all("signature" not in m for m in mixes.values()))
        described = {d["id"]: d for d in namer.asked[0]}["now-1"]
        self.assertEqual((described["genres"], described["energy"]), (["Rock"], "steady"))
        # Asked again the same day: the names are kept, and only the one without asked for again.
        self.make(at=NOW + 600)
        self.assertEqual([[d["id"] for d in a] for a in namer.asked[1:]], [["daily-2"]])

    def test_each_mix_has_a_line_on_whats_in_it_and_a_key_of_its_own(self):
        self.play("rock", "2026-11-10 06:30")
        self.play("piano", "2026-02-02 21:00", songs=range(20), times=3)
        got = self.make()
        mixes = {m["id"]: m for s in got["shelves"] for m in s["mixes"]}
        self.assertEqual(mixes["now-1"]["about"], "Steady rock")
        self.assertEqual(mixes["daily-2"]["about"], "Calm piano")
        self.assertEqual((mixes["rediscover"]["about"], mixes["new"]["about"]), ("Old favourites, back again", "Fresh finds near your taste"))
        self.assertTrue(mixes["now-1"]["why"].startswith("Like Rock Artist"))  # the artists stay, for the mix's own page
        self.assertEqual(mixes["now-1"]["key"], "2026-11-17-early-weekdays-now-1")
        self.assertEqual(mixes["daily-1"]["key"], "2026-11-17-daily-1")
        evening = {m["id"]: m for s in self.make(at=at("2026-11-17 19:00"))["shelves"] for m in s["mixes"]}
        self.assertEqual(evening["now-1"]["key"], "2026-11-17-evening-weekdays-now-1")  # another part of the day: another mix

    def test_mixes_given_out_are_kept_for_days(self):
        self.play("rock", "2026-11-10 06:30")
        got = self.make()
        self.assertEqual(got["keep_days"], 7)
        kept = self.mixes.kept("max")
        first = got["shelves"][0]["mixes"][0]
        self.assertIn(first["key"], [m["key"] for m in kept])
        one = self.mixes.kept("max", first["key"])[0]
        self.assertEqual((one["name"], one["about"], one["songs"]), (first["name"], first["about"], [s["id"] for s in first["songs"]]))
        writes = self.store.writes
        self.make(at=NOW + 60)
        self.assertEqual(self.store.writes, writes)  # the same mixes again: nothing written
        # Six days on it's still there; past seven it's gone.
        self.clock[0] = NOW + 6 * 86400
        self.assertTrue(self.mixes.kept("max", first["key"]))
        self.clock[0] = NOW + 8 * 86400
        self.assertEqual(self.mixes.kept("max", first["key"]), [])
        # Kept longer when the page says so.
        self.assertEqual(self.mixes.set_keep_days(30), 30)
        self.assertTrue(self.mixes.kept("max", first["key"]))
        self.assertEqual((self.mixes.set_keep_days(500), self.mixes.set_keep_days(0)), (90, 1))

    def test_the_listener_chooses_what_goes_in(self):
        self.play("rock", "2026-11-10 06:30")
        self.play("piano", "2026-02-02 21:00", songs=range(20), times=3)
        before = self.make()
        self.assertEqual(self.mixes.settings("max"), mix_settings.defaults())  # nothing chosen: as they came
        # Fewer shelves and mixes, shorter, one song an artist, no piano (New for you has some without it).
        self.mixes.set_settings("max", {"daily": False, "repeat": False, "rediscover": False, "now_count": 1,
                                        "size": 12, "per_artist": 1, "leave_genres": ["Piano"]})
        got = self.make()
        self.assertEqual([s["key"] for s in got["shelves"]], ["now", "more"])
        self.assertEqual([m["id"] for m in got["shelves"][1]["mixes"]], ["new"])
        now = got["shelves"][0]["mixes"]
        self.assertEqual(len(now), 1)
        for m in now + got["shelves"][1]["mixes"]:
            self.assertLessEqual(len(m["songs"]), 12)
            self.assertNotIn("piano", self.kinds(m))
            artists = [x["artist"] for x in m["songs"]]
            self.assertEqual(len(artists), len(set(artists)))
        self.assertNotEqual(before["shelves"], got["shelves"])
        # An artist left out, and only what's new to you.
        self.mixes.set_settings("max", {"leave_genres": [], "leave_artists": ["Piano Artist 1", "piano artist 2"], "familiar": 0, "now_count": 4})
        for shelf in self.make()["shelves"]:
            for m in shelf["mixes"]:
                self.assertFalse({"Piano Artist 1", "Piano Artist 2"} & {x["artist"] for x in m["songs"]})
                if m["id"].startswith("now-"):
                    self.assertEqual(m["own"], 0)
        # The time of day not to count: made from all the listening.
        self.mixes.set_settings("max", {"time_of_day": False})
        self.assertEqual(self.make()["basis"], "all")
        # Only what differs is kept; the defaults back with "As they come".
        self.assertEqual(self.store.setting("mix_settings:max")["time_of_day"], False)
        self.mixes.set_settings("max", mix_settings.defaults())
        self.assertEqual(self.store.setting("mix_settings:max"), {})

    def test_settings_are_checked(self):
        with self.assertRaises(ValueError):
            mix_settings.clean({"size": "lots"})
        with self.assertRaises(ValueError):
            mix_settings.clean({"daily": "yes"})
        got = mix_settings.clean({"size": 500, "per_artist": 0, "leave_genres": " Rock ,  rock, Jazz,,", "nonsense": 1})
        self.assertEqual((got["size"], got["per_artist"], got["leave_genres"]), (100, 1, ["Rock", "Jazz"]))
        self.assertNotIn("nonsense", got)

    def test_made_ahead_for_how_the_app_asked(self):
        """Ten minutes before nine the morning's mixes are made, so the app finds them ready."""
        self.play("rock", "2026-11-10 06:30")
        self.play("piano", "2026-11-10 09:30")
        self.mixes.remember("max", TZ)
        self.clock[0] = at("2026-11-17 08:52")
        self.assertEqual(self.mixes.ahead(), 2)  # now's (early morning) and nine's (morning)
        self.assertEqual(self.mixes.ahead(), 0)  # already made
        kept = len(self.mixes._kept)
        self.clock[0] = at("2026-11-17 09:01")
        got = self.make()
        self.assertEqual((got["part"], len(self.mixes._kept)), ("morning", kept))  # nothing made: it was ready
        # With nobody asked for, the listener with most listens.
        self.mixes.asked.clear()
        self.clock[0] = at("2026-11-17 12:00")
        self.assertEqual(self.mixes.ahead(default_tz=TZ), 1)  # now and ten minutes on are both the afternoon

    def test_where_the_listener_is_can_be_said(self):
        """A latitude and longitude from the app: Cape Town's November morning is light."""
        got = self.mixes.make("max", TZ, lat=-33.92, lon=18.42)
        self.assertEqual(got["daylight"]["light"], "light")
        self.assertIsNone(self.mixes.make("max", "Nowhere/At_All")["daylight"])


if __name__ == "__main__":
    unittest.main()


class TheNames(unittest.TestCase):
    """0.61, the owner: "the naming is way too generic, hushed appears many times"; a mix of everything "as long as
    it's suitable, taking weather, location, season etc into consideration"."""

    def like(self, energy=0.3, mood=0.2, genre="Alternative Rock", artists=("Loathe", "Spiritbox")):
        return {"energy": energy, "mood": mood, "genres": [genre], "tags": [], "artists": list(artists)}

    def test_a_page_says_each_first_word_once(self):
        taken, used = set(), set()
        names = [M.Mixes._name(self.like(genre=g), taken, used, turn=0) for g in ("Alternative Rock", "Metalcore", "Folk", "Piano")]
        self.assertEqual(names, ["Hushed Alternative Rock", "Shadowed Metalcore", "Smoky Folk", "Brooding Piano"])

    def test_a_row_takes_turns_moment_and_sound_never_artists(self):
        taken, used = set(), set()
        moment = M.moment_words("evening", 4, 12, "dark", "rain")
        self.assertEqual(moment[:3], ["Rainy", "After-dark", "Friday-night"])
        names = [M.Mixes._name(self.like(genre=g, artists=a), taken, used, moment, n)
                 for n, (g, a) in enumerate([("Folk", ("Vaya Con Dios",)), ("Metalcore", ("Loathe", "Spiritbox")), ("Drum n Bass", ("Pendulum", "Sub Focus"))])]
        # Never who's in it (0.61.2, the owner: "we have artist radios for that job").
        self.assertEqual(names, ["Rainy Folk", "Hushed Metalcore", "After-dark Drum n Bass"])
        self.assertFalse(any("Pendulum" in n or "Loathe" in n for n in names))

    def test_the_season_turns_round_in_the_south(self):
        self.assertEqual(M.moment_words("afternoon", 1, 1)[-1], "Winter")
        self.assertEqual(M.moment_words("afternoon", 1, 1, south=True)[-1], "Summer")
        self.assertEqual(M.moment_words("afternoon", 1, 7)[-1], "Summer")

    def test_no_weather_word_without_the_app_saying(self):
        self.assertNotIn("Rainy", M.moment_words("evening", 2, 11, "light", None))
        self.assertNotIn("Rainy", M.moment_words("evening", 2, 11, "light", "nonsense"))

