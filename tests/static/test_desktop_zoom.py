"""Desktop zoom through real native menu commands and a real WebKit page.

Run with `python3 -m unittest tests.static.test_desktop_zoom -v` on macOS.
The app's entry point is omitted only in the temporary test compilation; its delegate,
menus, WebView and developer-panel bridge are the production implementations.
No database, agent, user preferences or board contents are used.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform == "darwin", "AppKit and WebKit require macOS")
class DesktopZoomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix="verticals-zoom-test-")
        cls.addClassCleanup(cls.work.cleanup)
        work = Path(cls.work.name)
        source = (ROOT / "desktop/macos/Verticals.swift").read_text()
        delegate, marker, _ = source.rpartition("\n@main enum Main")
        assert marker, "The desktop entry point was not found"
        test_source = work / "Verticals.swift"
        test_source.write_text(delegate)
        program = work / ("verticals-zoom-check-" + uuid.uuid4().hex)
        sources = [test_source, *(ROOT / "desktop/macos" / name for name in
                                  ("AppLinks.swift", "Updater.swift", "UpdateIndicator.swift")),
                   ROOT / "tests/static/desktop_zoom_check.swift"]
        build = subprocess.run([shutil.which("swiftc") or "swiftc", "-parse-as-library", "-target",
                                "arm64-apple-macos13.0", "-module-cache-path", str(work / "modules"),
                                "-o", str(program), *(str(p) for p in sources)],
                               capture_output=True, text=True, timeout=180)
        assert build.returncode == 0, build.stderr[-5000:]
        run = subprocess.run([str(program)], capture_output=True, text=True, timeout=45)
        assert run.returncode == 0, run.stderr[-3000:]
        cls.observed = json.loads(run.stdout)

    def test_view_menu_exposes_standard_zoom_commands(self):
        commands = self.observed["commands"]
        for title in ("Zoom In", "Zoom Out", "Actual Size"):
            self.assertIn(title, commands)
        self.assertIn("Reduce Motion", commands)
        self.assertIn("Reload", commands)

    def test_plus_and_equals_enlarge_and_minus_reverses_the_last_step(self):
        self.assertTrue(self.observed["equalsHandled"])
        self.assertTrue(self.observed["plusHandled"])
        self.assertTrue(self.observed["minusHandled"])
        self.assertEqual(self.observed["steps"], [1.1, 1.25, 1.1])
        self.assertEqual(self.observed["savedAfterStep"], 1.1)

    def test_command_zero_resets_and_saves_actual_size(self):
        self.assertTrue(self.observed["resetHandled"])
        self.assertEqual(self.observed["reset"], 1)
        self.assertEqual(self.observed["savedAfterReset"], 1)

    def test_zoom_stops_at_the_existing_50_and_200_percent_limits(self):
        self.assertEqual(self.observed["maximum"], 2)
        self.assertEqual(self.observed["minimum"], 0.5)
        self.assertFalse(self.observed["plainEqualsHandled"])
        self.assertEqual(self.observed["afterPlainEquals"], 0.5)

    def test_zoom_works_while_editing_and_keeps_the_draft_and_focus(self):
        self.assertEqual(self.observed["bridge"], 1.25)
        self.assertEqual(self.observed["whileEditing"], 1.5)
        self.assertEqual(self.observed["focusedBefore"], "draft")
        self.assertEqual(self.observed["focusedAfter"], "draft")
        self.assertEqual(self.observed["draft"], "Keep my draft")
        self.assertEqual(self.observed["pageKnowsZoom"], 1.5)

    def test_appearance_choice_reaches_the_page_and_is_kept(self):
        self.assertEqual(self.observed["appearances"], ["System", "Light", "Dark"])
        self.assertEqual(self.observed["dark"], {"dark": True, "saved": "NSAppearanceNameDarkAqua",
                                                 "checked": ["Dark"], "draft": "Keep my draft"})
        self.assertEqual(self.observed["light"], {"dark": False, "saved": "NSAppearanceNameAqua",
                                                  "checked": ["Light"], "draft": "Keep my draft"})
        self.assertEqual(self.observed["system"]["saved"], "")
        self.assertEqual(self.observed["system"]["checked"], ["System"])
        self.assertTrue(self.observed["systemFollowsMacOS"])


if __name__ == "__main__":
    unittest.main()
