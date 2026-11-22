"""The page's script must parse: one mistake there (a name declared twice) leaves the whole page empty."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser

PAGE = os.path.join(os.path.dirname(__file__), "..", "beats", "page.html")


def _scripts(page):
    """What's inside each script tag, read as a browser reads the page."""
    found = []

    class Reader(HTMLParser):
        inside = False

        def handle_starttag(self, tag, attrs):
            if tag == "script":
                self.inside = True
                found.append("")

        def handle_endtag(self, tag):
            if tag == "script":
                self.inside = False

        def handle_data(self, data):
            if self.inside:
                found[-1] += data

    Reader().feed(page)
    return found


class PageScriptTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_page_script_parses(self):
        script = "\n".join(_scripts(open(PAGE, encoding="utf-8").read()))
        self.assertTrue(script.strip())
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(script)
        try:
            check = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        finally:
            os.unlink(f.name)
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_the_menu_and_the_pages_match_and_nothing_old_is_said(self):
        """0.43 (the owner, 13 Nov: pages still spoke of things since removed): every menu entry has its page and the
        script knows it; and the page says nothing of AudioMuse-AI or a plugin, which Siansa Beats no longer has."""
        page = open(PAGE, encoding="utf-8").read()
        menu = re.findall(r'<a href="#(\w+)" data-view="(\w+)"', page)
        self.assertEqual([a for a, _ in menu], [b for _, b in menu])
        sections = set(re.findall(r'<section data-view="(\w+)"', page))
        views = set(re.search(r'const VIEWS = \[(.*?)\];', page).group(1).replace('"', "").replace(" ", "").split(","))
        self.assertEqual({b for _, b in menu} - sections, set())
        self.assertEqual(sections, views)
        self.assertEqual([b for _, b in menu], ["overview", "libraries", "songs", "listening", "mixes", "loudness", "keys", "genres",
                                                "voice", "similar", "activity", "setup", "log", "blends", "report"])
        # 0.52: Voice and mood has its own page, and each of its lines one for its songs.
        self.assertIn("trait", sections)
        # 0.53: Mixes, and one mix's songs.
        self.assertIn("mix", sections)
        for gone in ("audiomuse", "plugin"):
            self.assertNotIn(gone, page.lower(), gone)
        signin = open(os.path.join(os.path.dirname(PAGE), "signin.html"), encoding="utf-8").read()
        self.assertIn("beats.reset", signin)  # the way back in is said where it's needed
        self.assertNotIn("audiomuse", signin.lower())


if __name__ == "__main__":
    unittest.main()


class PageDownloadsTest(unittest.TestCase):
    def test_mix_settings_have_a_page_of_their_own_with_a_place_for_every_setting(self):
        """0.63 (the owner, 22 Nov: "mix settings shouldn't be hidden at the bottom of the page"; "their own page and be
        100% organised"): the settings are a page, opened from the top of Mixes, and every setting Siansa Beats has is
        placed in one of its lines, so none is left under More."""
        from beats import mix_settings
        page = open(PAGE, encoding="utf-8").read()
        self.assertIn('<section data-view="mixsettings">', page)
        mixes = page[page.index('<section data-view="mixes">'):page.index('<section data-view="mixsettings">')]
        self.assertIn('href="#mixsettings"', mixes)
        self.assertNotIn('id="mx-set-groups"', mixes)
        parts = page[page.index("var MX_PARTS = ["):page.index("var MX_WORDS")]
        placed = set(re.findall(r'on: "(\w+)"', parts))
        for names in re.findall(r"more: \[(.*?)\]", parts):
            placed |= set(re.findall(r'"(\w+)"', names))
        self.assertEqual(set(mix_settings.SETTINGS) - placed, set())
        self.assertEqual(placed - set(mix_settings.SETTINGS), set())
        self.assertEqual(re.findall(r'^  \["([^"]+)"', parts, re.M), ["Mixes", "Your sound", "For all mixes"])

    def test_downloads_are_plain_links(self):
        """0.50.2 (the owner, 16 Nov: "it should just stream the download until completion"): every Download button is
        a plain link the browser downloads as it comes, as Beats streams it; the page doesn't fetch it whole first."""
        page = open(PAGE, encoding="utf-8").read()
        links = re.findall(r'<a [^>]*href="([^"]+)"[^>]*\bdownload\b', page)
        self.assertGreaterEqual(len(links), 5)
        self.assertNotIn('closest("a[download]")', page)
        self.assertNotIn("createObjectURL", page)
