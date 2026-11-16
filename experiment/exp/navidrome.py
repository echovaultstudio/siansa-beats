"""Navidrome (the Subsonic API), as little of it as the trial needs: sign in, the playlists, a playlist's songs, a
song's file, and making one playlist. The password is kept in memory only, and is never sent as it is: each request
carries a hash of it with a fresh salt, as the Subsonic API asks."""
import hashlib
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request

CLIENT = "siansa-beats-experiment"


class NavidromeError(Exception):
    pass


class Navidrome:
    def __init__(self, url, user, password, timeout=30):
        url = str(url or "").strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        self.url, self.user, self._password, self.timeout = url, str(user or "").strip(), str(password or ""), timeout

    def _address(self, method, params=()):
        salt = secrets.token_hex(8)
        token = hashlib.md5((self._password + salt).encode()).hexdigest()  # noqa: S324 - the Subsonic API's own scheme
        query = [("u", self.user), ("t", token), ("s", salt), ("v", "1.16.1"), ("c", CLIENT), ("f", "json"), *params]
        return f"{self.url}/rest/{method}?{urllib.parse.urlencode(query)}"

    def _call(self, method, params=()):
        try:
            with urllib.request.urlopen(self._address(method, params), timeout=self.timeout) as r:  # noqa: S310
                answer = json.loads(r.read()).get("subsonic-response") or {}
        except urllib.error.HTTPError as e:
            raise NavidromeError(f"Navidrome answered HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise NavidromeError(f"Navidrome can't be reached at {self.url}: {getattr(e, 'reason', e)}") from None
        if answer.get("status") != "ok":
            said = (answer.get("error") or {}).get("message") or "no answer"
            raise NavidromeError("Wrong user name or password" if "password" in said.lower() else f"Navidrome says: {said}")
        return answer

    def ping(self):
        answer = self._call("ping")
        return f"{answer.get('type', 'server')} {answer.get('serverVersion') or answer.get('version', '')}".strip()

    def playlists(self):
        found = (self._call("getPlaylists").get("playlists") or {}).get("playlist") or []
        return [{"id": p["id"], "name": p.get("name") or "", "songs": p.get("songCount") or 0} for p in found]

    def playlist(self, playlist_id):
        found = self._call("getPlaylist", [("id", playlist_id)]).get("playlist") or {}
        return {"id": found.get("id"), "name": found.get("name") or "", "songs": [
            {"id": s["id"], "title": s.get("title") or "", "artist": s.get("artist") or "",
             "duration": s.get("duration") or 0, "suffix": s.get("suffix") or ""} for s in found.get("entry") or []]}

    def make_playlist(self, name, song_ids):
        """A new playlist ``name`` with ``song_ids`` (those the server doesn't have are left out by it): its id."""
        answer = self._call("createPlaylist", [("name", name), *[("songId", i) for i in song_ids]])
        return (answer.get("playlist") or {}).get("id")

    def download(self, song_id, path):
        """The song's own file, saved to ``path``: its size in bytes."""
        try:
            with urllib.request.urlopen(self._address("download", [("id", song_id)]), timeout=self.timeout * 4) as r:  # noqa: S310
                if "json" in (r.headers.get("Content-Type") or ""):
                    said = ((json.loads(r.read()).get("subsonic-response") or {}).get("error") or {}).get("message")
                    raise NavidromeError(f"Navidrome says: {said or 'no file'}")
                size = 0
                with open(path, "wb") as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
                        size += len(chunk)
                return size
        except urllib.error.HTTPError as e:
            raise NavidromeError(f"Navidrome answered HTTP {e.code} for the file") from None
        except (urllib.error.URLError, OSError) as e:
            raise NavidromeError(f"The file didn't come: {getattr(e, 'reason', e)}") from None
