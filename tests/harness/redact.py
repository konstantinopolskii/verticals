"""The redaction pass every F3 scenario runs over its own artifacts before the run ends
(`docs/E2E.md` suite-E teardown rule: "F3 scenarios additionally run the redactor over their
artifacts before the run ends, and the redactor's own output is asserted to contain zero strings
from the export's `name` or `description` fields").

Built directly against `SECURITY_FINDINGS.md` F-001's lesson: "check the bytes you actually
write, not a convenient projection of them" — a prior leak check read *rendered* text and missed
a real name sitting in an HTML attribute. `verify_clean` below re-reads the target file fresh off
disk and scans that; it is never handed the in-memory string `redact_file` already believes it
cleaned. The two are separate calls on purpose — a caller cannot accidentally verify the string
it just built instead of the bytes actually on disk.

The denylist itself is built at call time from the gitignored export and is never written to disk
on its own — the one artifact that must not exist is a second copy of the sensitive material
under a different name.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

# Below this length a "leaked string" check produces mostly false positives (a two-character
# title matches inside unrelated words constantly) with no safety benefit — the artifacts this
# module guards are pure count/id tables (`tools/import_planner.py`'s reconciliation table
# never prints a title or a body to begin with), so there is nothing to lose by ignoring short
# strings and something to gain in signal quality.
_MIN_LENGTH = 4


def build_denylist(export_path: Path) -> frozenset[str]:
    """Every non-trivial `name`/`description` string in the export, deduplicated. Rebuilt fresh
    from the file on every call — nothing here is cached to disk or to a module-level global.
    Returns an empty set rather than raising when `export_path` is absent, so a caller does not
    need its own F3-presence guard duplicated in front of every call site (the scenario itself
    already gates on F3 absence via `tests/harness/report.gate`, before it would ever reach a
    redaction call)."""
    if not export_path.exists():
        return frozenset()
    rows = json.loads(export_path.read_text())
    denylist: set[str] = set()
    for row in rows:
        for field in ("name", "description"):
            value = row.get(field)
            if isinstance(value, str) and len(value.strip()) >= _MIN_LENGTH:
                denylist.add(value)
    return frozenset(denylist)


def scan(text: str, denylist: frozenset[str]) -> list[str]:
    """Every denylist string present verbatim in `text`, as a substring — F-001's own failure
    mode was a name sitting *inside* an HTML attribute, not standing alone as the whole field."""
    return [s for s in denylist if s in text]


def _redact_text(text: str, denylist: frozenset[str]) -> str:
    for s in denylist:
        if s in text:
            text = text.replace(s, "[REDACTED]")
    return text


def redact_file(path: Path, denylist: frozenset[str]) -> list[str]:
    """Read `path`, replace every denylist hit with `[REDACTED]`, write it back only if anything
    changed. Returns the strings that were found (before redaction) — empty if the file was
    already clean. Missing `path` is a no-op, not an error: a scenario that failed before writing
    its artifact has nothing here to clean.

    This function's own belief that the result is clean is exactly the "convenient projection"
    F-001 warns about — it never asserts anything itself. `verify_clean` is the real check,
    called separately against the same path, against bytes re-read from disk.
    """
    if not path.exists():
        return []
    original = path.read_text()
    hits = scan(original, denylist)
    if hits:
        path.write_text(_redact_text(original, denylist))
    return hits


def verify_clean(path: Path, denylist: frozenset[str]) -> list[str]:
    """Re-reads `path` fresh off disk and scans *that* — the actual bytes a reviewer or a
    shipped artifact would see, not the string `redact_file` last held in memory. Returns the
    denylist strings still present; empty means clean."""
    if not path.exists():
        return []
    return scan(path.read_text(), denylist)


def redact_and_verify(paths: Iterable[Path], denylist: frozenset[str]) -> None:
    """The one call an F3 scenario's teardown needs: redact every path, then verify each is
    clean by re-reading it off disk. Raises `AssertionError` naming the path and the count of
    strings still present if verification ever finds one — this is the check the suite-E
    teardown rule requires to actually run, not merely to exist."""
    for path in paths:
        redact_file(path, denylist)
        leaked = verify_clean(path, denylist)
        if leaked:
            raise AssertionError(
                f"{path}: redaction left {len(leaked)} leaked string(s) on disk after rewrite"
            )
