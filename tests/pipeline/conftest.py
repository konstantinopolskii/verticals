"""Regenerates `artifacts/census.json` exactly once per invocation, before any pipeline worker
starts — the same ordering fix `tests/conftest.py`'s own `pytest_configure` already uses for the
identical cross-worker race (there: building `verticals_tmpl_f0` once; here: writing one shared
file once). Under pytest-xdist, `config.workerinput` exists only inside a worker process — the
controller runs every discovered `pytest_configure`, including this one, to completion before
spawning any worker, so gating on its absence means "run this exactly once, before the race could
ever start" rather than "take a lock and hope". A plain, non-distributed `pytest` invocation has
no controller/worker split at all, so the same guard is trivially satisfied there too — the exact
reasoning `tests/conftest.py` already gives for `ensure_template`.

Without this, `tests/pipeline/test_import.py`'s own `census` fixture (`scope="module"`) would run
once per xdist WORKER PROCESS rather than once globally, and every one of those workers would call
`tests.fixtures.census.write_census` against the same fixed path — a non-atomic `Path.write_text`
— at effectively the same moment. First run of this suite, observed directly: one worker's
`write_text` truncated the file while another worker's `read_text`, mid-flight, saw zero bytes;
`json.loads('')` raised `JSONDecodeError: Expecting value: line 1 column 1`. Not a flake in the
importer or in `census.py` — a torn read on a file two processes were writing at once. Moving the
write here and leaving `test_import.py`'s fixture as a read-only load fixes it by construction:
N module instances across N workers all read a file none of them ever writes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.census import write_census

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXPORT_PATH = _REPO_ROOT / "seed" / "planner-export.json"
_CENSUS_PATH = _REPO_ROOT / "artifacts" / "census.json"


def pytest_configure(config: pytest.Config) -> None:
    if hasattr(config, "workerinput"):
        return
    if not _EXPORT_PATH.exists():
        return  # F3 absent — every scenario that needs it gates itself, per-test
    write_census(_EXPORT_PATH, _CENSUS_PATH)
