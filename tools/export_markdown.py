#!/usr/bin/env python3
"""Export one owner's whole goal tree to markdown — AC-143, AC-144, AC-145; `docs/E2E.md` S-87.

    python tools/export_markdown.py --owner t1 > a.md

One command, no ceremony (AC-143): no token, no login prompt, no network call other than the
one Postgres connection it needs to read `goals`. Reads `VERTICALS_DATABASE_URL` directly from
the environment rather than going through `verticals/config.py`'s `load()` — the same, deliberate
exception `verticals/db/runner.py` already is. That module's own docstring names itself as "the
one pre-existing exception" to "nothing else under verticals/ reads os.environ directly"; this
tool is a second, and for the same underlying reason: `load()` also requires `VERTICALS_TOKEN`, a
transport-auth concern this offline, single-shot, read-only CLI has no business demanding before
it will even run — AC-143's "no token prompt" would otherwise be unmeetable by construction.
(`config.py`'s docstring calling this "the one" exception is therefore one word stale as of this
file; not this file's docstring to fix, noted for whoever next edits `config.py`.)

Every actual decision — which roots, what order, what the rendered bytes look like — lives in
`verticals/core/markdown.py::export_owner`, called exactly once, below. This file is the
argv-to-stdout shell around that one call and nothing else (`ARCHITECTURE.md` §2's module
boundary): parse `--owner`, open one connection, write the result to stdout, pick an exit code.
AC-145 is what makes that safe to be this thin — the agent-facing `outline` MCP tool (WP-19) and
this file's output are guaranteed the same format because both call the same renderer, not
because two renderers happen to agree today.
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg

from verticals.core.errors import VerticalError
from verticals.core.markdown import export_owner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python tools/export_markdown.py",
        description="Dump one owner's whole goal tree to markdown on stdout.",
    )
    parser.add_argument("--owner", required=True, help="owner to export, e.g. t1")
    args = parser.parse_args(argv)

    dsn = os.environ.get("VERTICALS_DATABASE_URL")
    if not dsn:
        print("export_markdown: VERTICALS_DATABASE_URL is not set", file=sys.stderr)
        return 2

    try:
        # autocommit=True: matching verticals/db/runner.py's own _connect (its comment there
        # argues the case once already), a bare read starts and ends in the same statement — no
        # transaction anything downstream needs held open around it.
        with psycopg.connect(dsn, autocommit=True) as conn:
            text = export_owner(conn, owner=args.owner)
    except VerticalError as exc:
        print(f"export_markdown: {exc.message}", file=sys.stderr)
        return 2
    except psycopg.Error as exc:
        print(f"export_markdown: database error: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
