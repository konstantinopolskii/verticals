"""The fixed-shape FAIL block (`docs/E2E.md` §12) and the two primitives a scenario test uses
to report something other than a plain pass.

Two things every scenario test file imports from here:

  * `gate(reason)` — call when a precondition this scenario needs is absent (a fixture, an
    extension, a checkout). Never use `pytest.skip`: `docs/E2E.md` §12 rule 4 says the catalogue
    has no skippable scenarios, and AC-089 asserts `skip == 0` in every suite row. A gate is a
    distinct, permitted outcome; a skip is always a FAIL.
  * `fail(detail)` — call with a filled-in `FailDetail` to make a failure print the exact block
    `docs/E2E.md` §12 shows under "A failure prints a fixed-shape block before the verdict".
    A plain `assert` still works and still fails the test; `fail()` is for a scenario author who
    wants the rich shape (expected/actual/detail) rather than a bare traceback.

Both are read by exactly one place downstream: `tests/conftest.py`'s `pytest_runtest_makereport`
hook (for `Gated`) and `tests/harness/runner.py`'s result collector (for a `longrepr` that
already starts with `"FAIL "`). Neither of those places is this module's concern — this module
only defines the shapes and the formatter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NoReturn

import pytest

# The naming convention every scenario test function follows, already in use by WP-01's
# tests/core/test_migrations.py (`test_s01_...`, `test_s02_...`) and
# tests/pipeline/test_schema_parity.py (`test_s88_...`, `test_s111a_...`). A trailing lowercase
# letter distinguishes several test functions that all verify one multi-part catalogue scenario
# (S-111's three privilege shapes) without inventing three scenario ids that E2E.md never named.
_SCENARIO_RE = re.compile(r"^test_s(\d+)[a-z]?(?:_|$)", re.IGNORECASE)


def scenario_id_of(test_name: str) -> str | None:
    """`"test_s09_reparent_indirect_cycle_refused"` -> `"S-09"`. `"test_s111a_..."` -> `"S-111"`.
    `None` for anything that does not follow the convention — the caller decides whether an
    unmatched test name is a harness error (`tests/harness/runner.py` treats it as one)."""
    m = _SCENARIO_RE.match(test_name)
    return f"S-{m.group(1)}" if m else None


def suite_of(nodeid: str) -> str:
    """`"tests/core/test_tree.py::test_s08_..."` -> `"core"`. The suite is the directory
    directly under `tests/`, which already matches the Makefile's suite names one for one.
    Shared by `tests/conftest.py` (the `VERTICALS_FORCE_FAIL` FAIL block's `suite` field) and
    `tests/harness/runner.py` (the per-scenario stream line and `results.jsonl`'s `suite`
    field) so the two never quietly drift apart."""
    parts = nodeid.split("::", 1)[0].replace("\\", "/").split("/")
    return parts[1] if len(parts) > 1 else "unknown"


class Gated(Exception):
    """Raised by `gate()`. Caught by `tests/conftest.py`'s report hook and turned into the
    `gate` outcome — never a plain pass, never pytest's own `skipped`."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def gate(reason: str) -> NoReturn:
    """Report this scenario as GATE: `reason` names the missing precondition and is what the
    verdict line prints (`docs/E2E.md` §12: "a gate is permitted only ... when the verdict line
    names the missing fixture"). Example: `gate("F3 absent")`."""
    raise Gated(reason)


def backlog(scenario_id: str, ruling: str, *, dated: str) -> NoReturn:
    """Report this scenario as GATE because **the owner deferred the work**, not because a
    precondition is missing. Same machinery as `gate()` — there is no fourth outcome and adding
    one would mean a fourth column in every suite row — but a distinct, greppable prefix, because
    the two states are not the same claim and a reader must not be able to confuse them:

        gate      = "this box cannot answer the question" (nothing is owed)
        backlog   = "the question is real and unanswered, and the owner said later" (work is owed)

    Deliberately **not** a pass. Under `TIER=full` `runner.py` turns any gate into a FAIL, which
    is the behaviour we want: the strictest tier should still say the work is outstanding. Under
    the default `ci` tier it reports PASS with the ruling printed in the verdict line, so a
    backlogged item cannot rot silently — every single run reprints it.

    `dated` is required and is the date of the ruling, so a deferral that has been sitting for
    months is visible as such in the verdict line rather than looking like a fresh decision."""
    raise Gated(f"BACKLOG {scenario_id} (owner ruling {dated}): {ruling}")


@dataclass(frozen=True)
class FailDetail:
    """Structured input to `format_fail_block`. `expected`/`actual` carry their own
    parenthetical ("9f2c1a...  (49 rows)") because that annotation is scenario-specific, not
    something the harness can compute generically."""

    scenario_id: str
    suite: str
    name: str
    file: str  # "tests/core/test_tree.py:118"
    assert_expr: str
    expected: str
    actual: str
    detail: str
    artifact: str | None = None


_FIELD_WIDTH = 8  # len("expected") == len("artifact"), the two longest field names below


def format_fail_block(d: FailDetail) -> str:
    """Byte-for-byte the shape `docs/E2E.md` §12 shows:

        FAIL S-09  core  reparent_indirect_cycle_refused
          file      tests/core/test_tree.py:118
          assert    table_digest_after == table_digest_before
          expected  9f2c1a...  (49 rows)
          actual    77be40...  (49 rows, 3 paths rewritten)
          detail    the prefix UPDATE ran before the cycle guard; ...
          artifact  artifacts/core/S-09/rows_after.csv

    Field names are left-justified to 8 characters, then two literal spaces, then the value.
    `artifact` is the one optional row — omitted when the scenario declared none.
    """
    lines = [f"FAIL {d.scenario_id}  {d.suite}  {d.name}"]
    rows: list[tuple[str, str]] = [
        ("file", d.file),
        ("assert", d.assert_expr),
        ("expected", d.expected),
        ("actual", d.actual),
        ("detail", d.detail),
    ]
    if d.artifact:
        rows.append(("artifact", d.artifact))
    for name, value in rows:
        lines.append(f"  {name.ljust(_FIELD_WIDTH)}  {value}")
    return "\n".join(lines)


def fail(detail: FailDetail) -> NoReturn:
    """Fail the current test with the exact block `format_fail_block` renders. `pytrace=False`
    is load-bearing: without it pytest appends its own traceback below the block, and the block
    stops being what `runner.py` finds verbatim at the start of `report.longrepr`."""
    pytest.fail(format_fail_block(detail), pytrace=False)


# --- artifacts -------------------------------------------------------------------------------
#
# A scenario declares an artifact file so two things become true: `results.jsonl`'s "artifacts"
# list names it, and the post-run leak audit (S-124) can assert the file actually exists. This
# uses pytest's own `Stash` (no new mechanism, no global) so the value lives exactly as long as
# the test item does.

_ARTIFACTS_KEY = pytest.StashKey[list]()


def artifact(request: pytest.FixtureRequest, path: str) -> str:
    """Register `path` (repo-root-relative, e.g. `"artifacts/core/S-09/rows_after.csv"`) as an
    artifact this scenario produced. Returns `path` unchanged so a call can wrap a write:

        p = artifact(request, f"artifacts/core/{scenario_id}/rows_after.csv")
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(rows_csv)
    """
    request.node.stash.setdefault(_ARTIFACTS_KEY, []).append(path)
    return path


def artifacts_for(item: pytest.Item) -> list[str]:
    """Read back whatever `artifact()` registered against this item. Empty list if none."""
    return list(item.stash.get(_ARTIFACTS_KEY, []))
