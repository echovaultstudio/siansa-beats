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
        self.assertEqual([b for _, b in menu], ["overview", "libraries", "songs", "listening", "loudness", "keys", "genres",
                                                "similar", "activity", "setup", "log", "blends", "report"])
        for gone in ("audiomuse", "plugin"):
            self.assertNotIn(gone, page.lower(), gone)
        signin = open(os.path.join(os.path.dirname(PAGE), "signin.html"), encoding="utf-8").read()
        self.assertIn("beats.reset", signin)  # the way back in is said where it's needed
        self.assertNotIn("audiomuse", signin.lower())


if __name__ == "__main__":
    unittest.main()


class PageDownloadsTest(unittest.TestCase):
    def test_every_download_link_is_fetched_by_the_page(self):
        """0.50.1 (the owner, 16 Nov: Download data failed on a phone, as a small "export.html"): the page fetches every
        download link of its own, with its sign-in, and saves what came back, instead of the browser's download manager
        asking again on its own. Each such link is an api/ address, which the page's one handler takes."""
        page = open(PAGE, encoding="utf-8").read()
        links = re.findall(r'<a [^>]*href="([^"]+)"[^>]*\bdownload\b', page)
        self.assertGreaterEqual(len(links), 5)
        for href in links:
            self.assertTrue(href.startswith("api/"), href)
        self.assertIn('e.target.closest("a[download]")', page)
        self.assertIn("e.preventDefault();", page)
        self.assertIn("URL.createObjectURL(blob)", page)
