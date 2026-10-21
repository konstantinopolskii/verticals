"""Run the production window configuration in AppKit; WebKit must inherit OS appearance."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform == "darwin", "AppKit and WebKit require macOS")
class DesktopAppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "desktop/macos/Verticals.swift").read_text()
        start = source.index("        window = NSWindow(contentRect:")
        end = source.index("        window.contentView = content", start)
        configuration = source[start:end]
        harness = (ROOT / "tests/static/desktop_appearance_check.swift").read_text()
        with tempfile.TemporaryDirectory(prefix="vertical-appearance-") as directory:
            work = Path(directory)
            program = work / "appearance"
            swift = work / "check.swift"
            swift.write_text(harness.replace("// WINDOW_CONFIGURATION", configuration))
            build = subprocess.run(["swiftc", "-parse-as-library", "-target", "arm64-apple-macos13.0",
                                    "-module-cache-path", str(work / "modules"), "-o", str(program), str(swift)],
                                   capture_output=True, text=True, timeout=180)
            assert build.returncode == 0, build.stderr
            run = subprocess.run([str(program)], check=True, capture_output=True, text=True, timeout=30)
        cls.result = json.loads(run.stdout.strip().splitlines()[-1])

    def test_window_and_webkit_follow_appearance_without_reload(self):
        self.assertEqual([s["nativeDark"] for s in self.result], [False, True, False])
        self.assertEqual([s["webDark"] for s in self.result], [False, True, False])
        self.assertTrue(all(s["draft"] == "Keep my draft" for s in self.result))

    def test_starting_window_background_follows_appearance(self):
        self.assertGreater(self.result[0]["background"], .9)
        self.assertLess(self.result[1]["background"], .2)
        self.assertGreater(self.result[2]["background"], .9)
