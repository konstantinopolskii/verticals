"""The web app the browser suites build and serve: `web/`, or the package `VERTICALS_WEB_DIR` names
(relative to the repository). The package builds into its own `dist/` with `npm run build` and serves it
with `npm run preview`, both run from the repository root (`npm --prefix`, so the package may import from
its siblings), proxying `/api` and `/healthz` to `VITE_API_PROXY_TARGET`."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / os.environ.get("VERTICALS_WEB_DIR", "web")
WEB_PREFIX = WEB_DIR.relative_to(REPO_ROOT).as_posix()
