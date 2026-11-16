"""The trial's service: one page, a few calls, one worker.

    GET  /                      the page
    GET  /api/health            always open, for Docker
    GET  /api/state             signed in or not, the playlists, the run, the songs' results (no levels), the log's end
    POST /api/signin            {"url", "user", "password"}: Navidrome; kept in memory only, gone at a restart
    POST /api/signout
    POST /api/playlist/make     a playlist "Beats experiment" on Navidrome from the songs of the answer key
    POST /api/analyse           {"playlist"}: that playlist's songs, one after another
    POST /api/stop              after the song being analysed
    GET  /api/results.json      everything, with each song's levels: the file to send
    GET  /api/log.txt           the log

The page has no password of its own: for a home network, for the time of the trial.
"""
import json
import logging
import os
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, sections, stems
from .navidrome import Navidrome, NavidromeError

HERE = os.path.dirname(__file__)
PLAYLIST_NAME = "Beats experiment"
LOG_KEPT = 2000


class App:
    def __init__(self, data_dir, separator, marks_path=None):
        self.data_dir, self.separator = data_dir, separator
        os.makedirs(data_dir, exist_ok=True)
        with open(marks_path or os.path.join(HERE, "..", "marks.json"), encoding="utf-8") as f:
            self.marks = json.load(f)["songs"]
        self.lock = threading.Lock()
        self.navidrome, self.server_says = None, None
        self.log_lines = []
        self.run = {"state": "idle", "playlist": None, "done": 0, "of": 0, "current": None, "started": None, "seconds": None}
        self.results = {}
        self._stop = threading.Event()
        self._thread = None
        self.results_path = os.path.join(data_dir, "results.json")
        if os.path.exists(self.results_path):
            try:
                with open(self.results_path, encoding="utf-8") as f:
                    self.results = {s["id"]: s for s in json.load(f).get("songs", [])}
                self.log(f"Kept from before: {len(self.results)} songs' results")
            except (OSError, ValueError) as e:
                self.log(f"The results kept from before couldn't be read: {e}", "warn")

    # ---- the log ----

    def log(self, message, level="info"):
        line = {"at": time.time(), "level": level, "message": message}
        with self.lock:
            self.log_lines.append(line)
            del self.log_lines[:-LOG_KEPT]
        logging.getLogger("experiment").log({"warn": logging.WARNING, "error": logging.ERROR}.get(level, logging.INFO), message)

    def log_text(self):
        with self.lock:
            lines = list(self.log_lines)
        return "".join(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(x['at']))} {x['level'].upper():5} {x['message']}\n" for x in lines)

    # ---- Navidrome ----

    def sign_in(self, url, user, password):
        client = Navidrome(url, user, password)
        says = client.ping()  # raises with why when it doesn't take the sign-in
        with self.lock:
            self.navidrome, self.server_says = client, says
        self.log(f"Signed in to Navidrome at {client.url} as {client.user} ({says})")

    def sign_out(self):
        with self.lock:
            self.navidrome, self.server_says = None, None
        self.log("Signed out")

    def _client(self):
        with self.lock:
            client = self.navidrome
        if client is None:
            raise NavidromeError("Sign in to Navidrome first")
        return client

    def make_playlist(self):
        client = self._client()
        ids = list(self.marks)
        made = client.make_playlist(PLAYLIST_NAME, ids)
        have = len(client.playlist(made)["songs"]) if made else 0
        self.log(f"Made the playlist \"{PLAYLIST_NAME}\" on Navidrome: {have} of the {len(ids)} tapped songs are on this server")
        return {"id": made, "name": PLAYLIST_NAME, "songs": have, "tapped": len(ids)}

    # ---- the run ----

    def analyse(self, playlist_id):
        client = self._client()
        with self.lock:
            if self.run["state"] == "running":
                raise ValueError("Already analysing")
        playlist = client.playlist(playlist_id)
        if not playlist["songs"]:
            raise ValueError("That playlist has no songs")
        self._stop.clear()
        with self.lock:
            self.run = {"state": "running", "playlist": playlist["name"], "done": 0, "of": len(playlist["songs"]),
                        "current": None, "started": time.time(), "seconds": None}
        self._thread = threading.Thread(target=self._work, args=(client, playlist), name="experiment-worker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.log("Stopping after this song")

    def _work(self, client, playlist):
        songs = playlist["songs"]
        tapped = sum(1 for s in songs if s["id"] in self.marks)
        self.log(f"Analysing the playlist \"{playlist['name']}\": {len(songs)} songs, {tapped} of them tapped")
        started = time.monotonic()
        for song in songs:
            if self._stop.is_set():
                break
            with self.lock:
                self.run["current"] = f"{song['artist']} – {song['title']}"
            try:
                self.results[song["id"]] = self.one(client, song)
            except Exception as e:  # noqa: BLE001 - one song's trouble is logged; the rest go on
                self.log(f"{song['artist']} – {song['title']}: failed: {e}", "error")
                self.results[song["id"]] = {"id": song["id"], "artist": song["artist"], "title": song["title"], "error": str(e)}
            with self.lock:
                self.run["done"] += 1
            self.save()
        took = round(time.monotonic() - started, 1)
        with self.lock:
            stopped = self._stop.is_set()
            self.run.update(state="stopped" if stopped else "done", current=None, seconds=took)
        t = self.summary()["total"]
        self.log(f"{'Stopped' if stopped else 'Done'} in {took}s · {self.separator.describe()} · "
                 f"{t['hits']} of {t['scored']} taps found, {t['extra']} of {t['between']} finds between taps not at a tap")

    def one(self, client, song):
        """One song: its file, its parts, their levels, where the kick goes and comes, and the taps beside it."""
        times = {}
        with tempfile.TemporaryDirectory(dir=self.data_dir) as folder:
            path = os.path.join(folder, "song." + (song.get("suffix") or "bin"))
            t = time.monotonic()
            size = client.download(song["id"], path)
            times["download"] = round(time.monotonic() - t, 2)
            t = time.monotonic()
            audio = stems.decode(path)
            times["decode"] = round(time.monotonic() - t, 2)
        t = time.monotonic()
        parts = self.separator(audio)
        times["split"] = round(time.monotonic() - t, 2)
        t = time.monotonic()
        levels = stems.levels(parts)
        times["levels"] = round(time.monotonic() - t, 2)
        del parts
        found = sections.find(levels["kick"], levels["hop"])
        mine = self.marks.get(song["id"])
        scored = sections.score(found, mine["marks"], mine["bpm"]) if mine else None
        duration = round(audio.shape[1] / stems.RATE, 1)
        said = f"{scored['hits']} of {scored['scored']} taps found" if scored else "not tapped"
        self.log(f"{song['artist']} – {song['title']}: {len(found)} found, {said} · {size / 1e6:.1f} MB in {times['download']}s, "
                 f"decoded in {times['decode']}s, split in {times['split']}s ({duration / max(times['split'], 0.01):.0f}× as fast as it plays), "
                 f"levels in {times['levels']}s")
        return {"id": song["id"], "artist": song["artist"], "title": song["title"], "duration": duration, "seconds": times,
                "bpm": mine["bpm"] if mine else None, "found": found, "score": scored, "levels": levels}

    def save(self):
        body = {"version": __version__, "separator": self.separator.describe(),
                "rule": {"gap_db": sections.GAP_DB, "hold_seconds": sections.HOLD_SECONDS, "kick_hz": stems.KICK_HZ},
                "songs": list(self.results.values())}
        temporary = self.results_path + ".part"
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(body, f)
        os.replace(temporary, self.results_path)

    def summary(self):
        songs = [{k: v for k, v in s.items() if k != "levels"} for s in self.results.values()]
        return {"songs": songs, "total": sections.total([s["score"] for s in songs if s.get("score")])}

    def state(self):
        with self.lock:
            client, says, run = self.navidrome, self.server_says, dict(self.run)
            log = self.log_lines[-200:]
        out = {"version": __version__, "separator": self.separator.describe(), "tapped": len(self.marks),
               "signed_in": client is not None, "server": {"url": client.url, "user": client.user, "says": says} if client else None,
               "run": run, "log": log, **self.summary(), "playlists": None, "playlist_problem": None}
        if client is not None and run["state"] != "running":
            try:
                out["playlists"] = client.playlists()
            except NavidromeError as e:
                out["playlist_problem"] = str(e)
        return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    app = None

    def log_message(self, fmt, *args):  # requests aren't logged: the log is the trial's own
        pass

    def _send(self, status, body, kind="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            value = json.loads(self.rfile.read(length))
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        app = self.app
        if path == "/api/health":
            return self._send(HTTPStatus.OK, {"status": "ok", "version": __version__})
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "page.html"), "rb") as f:
                return self._send(HTTPStatus.OK, f.read(), "text/html; charset=utf-8")
        if path == "/api/state":
            return self._send(HTTPStatus.OK, app.state())
        if path == "/api/log.txt":
            return self._send(HTTPStatus.OK, app.log_text(), "text/plain; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="beats-experiment-log.txt"'})
        if path == "/api/results.json":
            if not os.path.exists(app.results_path):
                return self._send(HTTPStatus.NOT_FOUND, {"error": "Nothing analysed yet"})
            # Straight from the file, a piece at a time: it starts at once however big it is.
            size = os.path.getsize(app.results_path)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Disposition", 'attachment; filename="beats-experiment-results.json"')
            self.end_headers()
            if self.command != "HEAD":
                with open(app.results_path, "rb") as f:
                    while chunk := f.read(1 << 18):
                        self.wfile.write(chunk)
            return None
        return self._send(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        app, body = self.app, self._body()
        try:
            if path == "/api/signin":
                app.sign_in(body.get("url"), body.get("user"), body.get("password"))
                return self._send(HTTPStatus.OK, {"signed_in": True})
            if path == "/api/signout":
                app.sign_out()
                return self._send(HTTPStatus.OK, {"signed_in": False})
            if path == "/api/playlist/make":
                return self._send(HTTPStatus.OK, app.make_playlist())
            if path == "/api/analyse":
                app.analyse(str(body.get("playlist") or ""))
                return self._send(HTTPStatus.OK, {"started": True})
            if path == "/api/stop":
                app.stop()
                return self._send(HTTPStatus.OK, {"stopping": True})
        except (NavidromeError, ValueError) as e:
            if path == "/api/signin":
                app.log(f"Sign-in to Navidrome didn't work: {e}", "warn")
            return self._send(HTTPStatus.BAD_REQUEST, {"error": str(e)})
        return self._send(HTTPStatus.NOT_FOUND, {"error": "Not found"})


def serve(app, port):
    handler = type("ExperimentHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)  # noqa: S104 - a service in a container
    server.daemon_threads = True
    return server


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    separator = stems.FakeSeparator() if os.environ.get("EXPERIMENT_SEPARATOR") == "fake" else stems.DemucsSeparator(os.environ.get("EXPERIMENT_DEVICE", "auto"))
    app = App(os.environ.get("DATA_DIR", "/data"), separator)
    port = int(os.environ.get("PORT", "8095"))
    app.log(f"Siansa Beats experiment {__version__} on port {port}: {len(app.marks)} tapped songs in the answer key")
    serve(app, port).serve_forever()


if __name__ == "__main__":
    main()
