"""The demo of the page (demo/): it still fits the page it's made from. The demo itself is built by the Checks
workflow (demo/build.py), which is the check that it works."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "demo"))
sys.path.insert(0, HERE)

import build  # noqa: E402
import library  # noqa: E402


class TheDemo(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "..", "beats", "page.html"), encoding="utf-8") as f:
            self.page = f.read()

    def test_every_address_the_page_names_is_one_the_demo_knows(self):
        known = set().union(*build.ADDRESSES.values())
        new = sorted(build.named(self.page) - known)
        self.assertEqual(new, [], "The page asks for something the demo can't answer: teach demo/shim.js, then name it in "
                                  "ADDRESSES (demo/build.py)")
        gone = sorted(known - build.named(self.page))
        self.assertEqual(gone, [], "ADDRESSES (demo/build.py) names what the page no longer asks for")

    def test_the_places_the_demo_takes_over_are_there_once(self):
        # Pictures and the player are the page's own lines, swapped for the demo's when it's built.
        self.assertEqual(self.page.count(build.ART), 1)
        self.assertEqual(self.page.count(build.AUDIO), 1)
        self.assertEqual((self.page.count("<script>"), self.page.count("</script>")), (1, 1))

    def test_the_made_up_library_is_the_same_each_time_and_no_song_twice(self):
        songs = library.catalog()
        self.assertEqual(songs, library.catalog())
        self.assertEqual(len({s["id"] for s in songs}), len(songs))
        self.assertEqual(len({s["title"] for s in songs}), len(songs))
        self.assertEqual({s["kind"] for s in songs}, set(library.KINDS))

    def test_an_answers_key_leaves_out_what_the_page_adds_of_its_own(self):
        self.assertEqual(build.key_of("/api/listens?tz=Europe%2FLondon&year=2026&user=demo&month=3&server=main"),
                         "api/listens?month=3&year=2026")
        self.assertEqual(build.key_of("/api/status"), "api/status")


if __name__ == "__main__":
    unittest.main()
