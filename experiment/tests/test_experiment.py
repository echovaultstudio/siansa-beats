"""The trial without a model: the rule on made-up kicks, the score against taps, and the whole service against a fake
Navidrome with a stand-in for Demucs (everything under 200 Hz is "drums")."""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from exp import sections, stems  # noqa: E402
from exp.navidrome import Navidrome, NavidromeError  # noqa: E402
from exp.server import App, serve  # noqa: E402

RATE = stems.RATE
PASSWORD = "open sesame"


def song(parts, bpm=120.0):
    """Stereo float32 of ``parts``: ``[(seconds, kick?)]``, a hi-hat throughout and a 60 Hz kick on each beat where asked."""
    out = []
    beat = 60.0 / bpm
    rng = np.random.default_rng(1)
    for seconds, kick in parts:
        n = int(seconds * RATE)
        t = np.arange(n) / RATE
        hat = 0.02 * rng.standard_normal(n) * (np.mod(t, beat / 2) < 0.03)
        part = hat
        if kick:
            inside = np.mod(t, beat)
            part = part + 0.6 * np.sin(2 * np.pi * 60 * inside) * np.exp(-inside * 18)
        out.append(part)
    mono = np.concatenate(out).astype(np.float32)
    return np.stack([mono, mono])


def write_wav(path, audio):
    with wave.open(path, "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((audio.T.clip(-1, 1) * 32767).astype("<i2").tobytes())


class RuleTest(unittest.TestCase):
    def levels(self, parts):
        return stems.levels(stems.FakeSeparator()(song(parts)))

    def test_the_kick_going_out_and_coming_back(self):
        got = self.levels([(16, True), (12, False), (20, True)])
        found = sections.find(got["kick"], got["hop"])
        self.assertEqual([f["kind"] for f in found], ["breakdown", "drop"])
        self.assertAlmostEqual(found[0]["seconds"], 16, delta=1.0)
        self.assertAlmostEqual(found[1]["seconds"], 28, delta=1.0)

    def test_an_intro_without_the_kick_ends_in_a_drop_and_a_short_pause_is_none(self):
        got = self.levels([(10, False), (20, True), (1.5, False), (20, True)])
        found = sections.find(got["kick"], got["hop"])
        self.assertEqual([f["kind"] for f in found], ["drop"])
        self.assertAlmostEqual(found[0]["seconds"], 10, delta=1.0)

    def test_a_song_with_the_kick_all_through_has_none(self):
        got = self.levels([(40, True)])
        self.assertEqual(sections.find(got["kick"], got["hop"]), [])
        self.assertEqual(sections.find([], 0.046), [])

    def test_levels_of_every_part(self):
        got = self.levels([(6, True)])
        self.assertEqual(set(got), {"hop", "kick", "drums", "bass", "other", "vocals"})
        self.assertEqual(len(got["kick"]), len(got["other"]))
        self.assertGreater(max(got["kick"]), -40)
        self.assertEqual(max(got["bass"]), stems.FLOOR_DB)


class ScoreTest(unittest.TestCase):
    def test_a_tap_is_found_within_a_bar_of_the_same_kind(self):
        found = [{"seconds": 30.0, "kind": "breakdown"}, {"seconds": 60.5, "kind": "drop"}, {"seconds": 90.0, "kind": "drop"}]
        marks = [[29.2, "breakdown"], [44.0, "buildup"], [62.0, "drop"], [120.0, "drop"]]
        got = sections.score(found, marks, bpm=120.0)  # a bar is 2 s
        self.assertEqual([t["found"] for t in got["taps"]], [30.0, None, 60.5, False])
        self.assertEqual((got["scored"], got["hits"]), (3, 2))
        # Between the first and last tap: three found, the one at 90 s with no tap near.
        self.assertEqual((got["between"], got["extra"]), (3, 1))

    def test_a_song_tapped_once_or_twice_has_no_extras_counted(self):
        got = sections.score([{"seconds": 10.0, "kind": "drop"}, {"seconds": 50.0, "kind": "drop"}], [[10.0, "drop"]], bpm=174.0)
        self.assertEqual((got["hits"], got["between"], got["extra"]), (1, None, None))
        # The wrong kind at the right place is not a hit.
        self.assertEqual(sections.score([{"seconds": 10.0, "kind": "breakdown"}], [[10.0, "drop"]], 174.0)["hits"], 0)
        self.assertEqual(sections.total([got, got]), {"songs": 2, "scored": 2, "hits": 2, "between": 0, "extra": 0})


class FakeNavidrome(BaseHTTPRequestHandler):
    songs, playlists, made = {}, {}, []

    def log_message(self, *args):
        pass

    def do_GET(self):
        path, _, query = self.path.partition("?")
        q = urllib.parse.parse_qs(query)
        ok = q.get("u") == ["max"] and hashlib.md5((PASSWORD + q["s"][0]).encode()).hexdigest() == q["t"][0]  # noqa: S324
        if not ok:
            return self.answer({"status": "failed", "error": {"code": 40, "message": "Wrong username or password"}})
        method = path.rsplit("/", 1)[-1]
        if method == "ping":
            return self.answer({"status": "ok", "type": "navidrome", "serverVersion": "0.64.2"})
        if method == "getPlaylists":
            return self.answer({"status": "ok", "playlists": {"playlist": [{"id": i, "name": p["name"], "songCount": len(p["ids"])} for i, p in self.playlists.items()]}})
        if method == "getPlaylist":
            p = self.playlists[q["id"][0]]
            return self.answer({"status": "ok", "playlist": {"id": q["id"][0], "name": p["name"], "entry": [
                {"id": i, "title": f"Song {i}", "artist": "Tester", "duration": 40, "suffix": "wav"} for i in p["ids"] if i in self.songs or i == "gone"]}})
        if method == "createPlaylist":
            new = f"p{len(self.playlists) + 1}"
            self.playlists[new] = {"name": q["name"][0], "ids": [i for i in q.get("songId", []) if i in self.songs]}
            self.made.append(q.get("songId", []))
            return self.answer({"status": "ok", "playlist": {"id": new}})
        if method == "download":
            if q["id"][0] not in self.songs:
                return self.answer({"status": "failed", "error": {"code": 70, "message": "Song not found"}})
            with open(self.songs[q["id"][0]], "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        return self.answer({"status": "failed", "error": {"message": "unknown"}})

    def answer(self, value):
        body = json.dumps({"subsonic-response": value}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        tapped, plain = os.path.join(self.folder, "tapped.wav"), os.path.join(self.folder, "plain.wav")
        write_wav(tapped, song([(16, True), (12, False), (12, True)]))
        write_wav(plain, song([(14, True)]))
        FakeNavidrome.songs = {"tapped": tapped, "plain": plain}
        FakeNavidrome.playlists = {"p1": {"name": "Trial", "ids": ["tapped", "plain", "gone"]}}
        FakeNavidrome.made = []
        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeNavidrome)
        threading.Thread(target=self.fake.serve_forever, daemon=True).start()
        self.addCleanup(self.fake.shutdown)
        self.navidrome = f"http://127.0.0.1:{self.fake.server_address[1]}"
        marks = os.path.join(self.folder, "marks.json")
        with open(marks, "w") as f:
            json.dump({"songs": {"tapped": {"bpm": 120.0, "marks": [[16.3, "breakdown"], [21.0, "buildup"], [28.2, "drop"]]},
                                 "elsewhere": {"bpm": 174.0, "marks": [[10.0, "drop"]]}}}, f)
        self.app = App(os.path.join(self.folder, "data"), stems.FakeSeparator(), marks)
        self.server = serve(self.app, 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def call(self, path, body=None, raw=False):
        request = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                         method="GET" if body is None else "POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as r:
            data = r.read()
            return (r, data) if raw else json.loads(data)

    def refused(self, path, body):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.call(path, body)
        return json.loads(caught.exception.read())["error"]

    def wait(self):
        end = time.time() + 30
        while time.time() < end:
            state = self.call("/api/state")
            if state["run"]["state"] != "running":
                return state
            time.sleep(0.1)
        self.fail("still running")

    def test_sign_in_a_playlist_and_the_taps_beside_what_was_found(self):
        self.assertEqual(self.call("/api/health")["status"], "ok")
        self.assertIn(b"Siansa Beats experiment", self.call("/", raw=True)[1])
        state = self.call("/api/state")
        self.assertFalse(state["signed_in"])
        self.assertEqual(state["tapped"], 2)
        # Nothing works before signing in; a wrong password is said as that, and never written down.
        self.assertEqual(self.refused("/api/analyse", {"playlist": "p1"}), "Sign in to Navidrome first")
        self.assertEqual(self.refused("/api/signin", {"url": self.navidrome, "user": "max", "password": "wrong"}), "Wrong user name or password")
        self.assertIn("can't be reached", self.refused("/api/signin", {"url": "http://127.0.0.1:1", "user": "max", "password": PASSWORD}))
        self.call("/api/signin", {"url": self.navidrome, "user": "max", "password": PASSWORD})
        state = self.call("/api/state")
        self.assertEqual(state["server"]["says"], "navidrome 0.64.2")
        self.assertEqual(state["playlists"], [{"id": "p1", "name": "Trial", "songs": 3}])
        self.assertEqual(self.refused("/api/results.json", None) if False else self.call("/api/state")["songs"], [])

        self.call("/api/analyse", {"playlist": "p1"})
        state = self.wait()
        self.assertEqual((state["run"]["state"], state["run"]["done"], state["run"]["of"]), ("done", 3, 3))
        songs = {s["id"]: s for s in state["songs"]}
        self.assertEqual([f["kind"] for f in songs["tapped"]["found"]], ["breakdown", "drop"])
        self.assertEqual([t["found"] is not False for t in songs["tapped"]["score"]["taps"]], [True, True, True])
        self.assertIsNone(songs["tapped"]["score"]["taps"][1]["found"])  # the build-up: shown, not scored
        self.assertEqual(songs["plain"]["found"], [])
        self.assertIsNone(songs["plain"]["score"])
        self.assertIn("Song not found", songs["gone"]["error"])  # one song's trouble doesn't stop the rest
        self.assertEqual(state["total"], {"songs": 1, "scored": 2, "hits": 2, "between": 2, "extra": 0})
        self.assertNotIn("levels", songs["tapped"])

        r, body = self.call("/api/results.json", raw=True)
        self.assertIn("beats-experiment-results.json", r.headers["Content-Disposition"])
        saved = {s["id"]: s for s in json.loads(body)["songs"]}
        self.assertEqual(len(saved["tapped"]["levels"]["kick"]), len(saved["tapped"]["levels"]["drums"]))
        self.assertGreater(saved["tapped"]["seconds"]["split"], 0)
        log = self.call("/api/log.txt", raw=True)[1].decode()
        self.assertIn("2 of 2 taps found", log)
        self.assertIn("Signed in to Navidrome", log)
        self.assertNotIn(PASSWORD, log + body.decode() + json.dumps(state))
        # Kept over a restart; the sign-in isn't.
        again = App(os.path.join(self.folder, "data"), stems.FakeSeparator(), os.path.join(self.folder, "marks.json"))
        self.assertEqual(set(again.results), {"tapped", "plain", "gone"})
        self.assertIsNone(again.navidrome)

    def test_the_playlist_made_from_the_tapped_songs(self):
        self.assertEqual(self.refused("/api/playlist/make", {}), "Sign in to Navidrome first")
        self.call("/api/signin", {"url": self.navidrome, "user": "max", "password": PASSWORD})
        made = self.call("/api/playlist/make", {})
        self.assertEqual(made, {"id": "p2", "name": "Beats experiment", "songs": 1, "tapped": 2})
        self.assertEqual(FakeNavidrome.made, [["tapped", "elsewhere"]])
        self.call("/api/signout", {})
        self.assertFalse(self.call("/api/state")["signed_in"])


class NavidromeTest(unittest.TestCase):
    def test_an_address_without_http_and_no_password_in_it(self):
        client = Navidrome("192.168.1.2:4533/", " max ", "secret")
        self.assertEqual((client.url, client.user), ("http://192.168.1.2:4533", "max"))
        self.assertNotIn("secret", client._address("ping"))
        with self.assertRaises(NavidromeError):
            Navidrome("http://127.0.0.1:1", "max", "x", timeout=2).ping()


if __name__ == "__main__":
    unittest.main()
