#!/usr/bin/env python3
"""Check that a release's lite zip completes the previous release, the way the app does it.

    python3 desktop/macos/lite_check.py OLD.app desktop/dist/Verticals-lite.zip

With the same Resources/RUNTIME in both, the lite app plus OLD's runtime dirs must verify as the
signed release does; otherwise every update from OLD would fall back to the whole download. With a
different RUNTIME there is nothing to check: updates from OLD download the whole app.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

RUNTIME_DIRS = ["pg", "python", "site"]  # bundle.py's


def runtime(resources: Path) -> str | None:
    marker = resources / "RUNTIME"
    return marker.read_text().strip() if marker.exists() else None


def main():
    old, lite = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["ditto", "-x", "-k", lite, tmp], check=True)
        new = Path(tmp) / "Verticals.app"
        before, after = runtime(old / "Contents/Resources"), runtime(new / "Contents/Resources")
        if before is None or before != after:
            print(f"[lite] runtime {before} -> {after}: updates from the previous release download the whole app")
            return
        for top in RUNTIME_DIRS:
            subprocess.run(["ditto", old / "Contents/Resources" / top, new / "Contents/Resources" / top], check=True)
        if subprocess.run(["codesign", "--verify", "--deep", "--strict", new]).returncode != 0:
            sys.exit(f"[lite] runtime {after} unchanged, yet the completed lite app does not verify")
        print(f"[lite] runtime {after} unchanged: the lite zip completes the previous release")


if __name__ == "__main__":
    main()
