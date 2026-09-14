"""Parity suite plumbing: reuse the UI suite's fixtures with normal motion by default.

`tests/parity/` runs Playwright against the same built app + test Postgres as `tests/ui/`,
so its fixture stack IS `tests/ui/conftest.py`'s — re-exported here because pytest only
auto-applies conftests on the collection path, and `pytest_plugins` is not allowed outside
the rootdir conftest. A star-import is the whole mechanism: fixture functions become names
in this module and pytest discovers them here. The local `ui_reduced_motion` fixture is defined
after that import, so parity collection resolves the UI-session dependency to `no-preference`
without changing `tests/ui/`'s load-bearing `reduce` default.

A parity test that genuinely measures reduced motion can request it explicitly with indirect
parametrization: `@pytest.mark.parametrize("ui_reduced_motion", ["reduce"], indirect=True)`.
"""

import pytest

from tests.ui.conftest import *  # noqa: F401,F403


@pytest.fixture
def ui_reduced_motion(request: pytest.FixtureRequest) -> str:
    """Normal motion for parity; indirect parametrization may explicitly request `reduce`."""
    preference = getattr(request, "param", "no-preference")
    if preference not in {"no-preference", "reduce"}:
        raise ValueError(f"unsupported reduced-motion preference: {preference!r}")
    return preference
