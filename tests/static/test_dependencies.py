"""S-110 — the dependency allowlist. `docs/E2E.md` §7b; AC-086, AC-183, and AC-191's dependency
half (the socket-audit half is `S-112`, WP-21's, not this suite's — `static` opens no network).

`docs/DEPENDENCIES.md` now exists (WP-31, wave 6 — `docs/IMPLEMENTATION.md` §9.1, "supplies the
file AC-086 and AC-183 audit against"). `test_s110a` below does real set equality, both
directions, against two HTML-comment-delimited blocks in that document
(`s110a-python-runtime`, `s110a-js-runtime`) — not the whole-word substring check an earlier
revision of this suite used while the file did not exist yet. `gate()` stays as the defensive
branch for a checkout where `docs/DEPENDENCIES.md` is missing or mid-edit: a missing file must
still report itself as "not built yet," not crash `static` with a stack trace or silently pass an
empty set against an empty set. Everything that does not depend on that file's existence — zero
ORM, zero migration autogenerator, zero analytics/telemetry/updater, zero foreign absolute URL in
the built bundle — runs unconditionally, as it always did.

`docs/E2E.md` also refers to `uv.lock` throughout as though it is the Python lockfile; this
project has no `uv.lock` (or any `requirements*.txt`) anywhere — direct dependencies are pinned
by exact `==` versions straight in `pyproject.toml`, installed with plain `pip` into `.venv`. Both
are recorded in `docs/PENDING_DOC_FIXES.md`. `conftest.venv_dist_info_names()` is the degrading
proxy for "what actually landed, transitively" that a `uv.lock` scan would otherwise give; the
direct-dependency half of every check here reads `pyproject.toml` itself and needs no proxy.
"""

from __future__ import annotations

import re
import tomllib

from tests.harness.report import gate
from tests.static.conftest import REPO_ROOT, WEB_DIR, npm_package_names, venv_dist_info_names

DEPENDENCIES_MD = REPO_ROOT / "docs" / "DEPENDENCIES.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
PACKAGE_JSON = WEB_DIR / "package.json"
PACKAGE_LOCK = WEB_DIR / "package-lock.json"

ORM_AND_MIGRATION_TOOLS = {"sqlalchemy", "tortoise", "peewee", "prisma", "drizzle", "alembic", "atlas"}
ANALYTICS_AND_UPDATERS = {"sentry", "posthog", "segment", "mixpanel", "analytics", "electron-updater"}

# S-110's own allowance: "the two documentation links the README also carries." There is no
# README.md yet (WP-07/WP-32 territory) to read that pair from, so this is a narrow, principled
# stand-in rather than a guess at its contents — real DOM API namespace constants (never network
# hosts) plus the one vendor link this build's own `dist/` was empirically found to carry.
ALLOWED_URL_PREFIXES = (
    "http://www.w3.org/",
    "https://vuejs.org/error-reference/",
)


def _dep_name(spec: str) -> str:
    """`"psycopg[binary,pool]==3.3.4"` -> `"psycopg"`. Strips the extras bracket and every
    version/marker separator PEP 508 allows to start one."""
    return re.split(r"[\[=<>!~; ]", spec, maxsplit=1)[0].strip().lower()


def python_direct_dependencies() -> tuple[set[str], set[str]]:
    """(runtime names, dev names) declared in `pyproject.toml`, normalized like `_dep_name`."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data.get("project", {})
    runtime = {_dep_name(d) for d in project.get("dependencies", [])}
    dev = {_dep_name(d) for d in project.get("optional-dependencies", {}).get("dev", [])}
    return runtime, dev


def js_direct_dependencies() -> set[str]:
    import json

    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    return set(data.get("dependencies", {}))


def _marker_block_package_names(text: str, marker: str) -> set[str]:
    """Every backtick-quoted first-column entry inside the start/end HTML-comment marker pair
    named `marker` in `DEPENDENCIES.md` — the exact region `test_s110a` treats as
    machine-checked. A row is recognised only when its first table cell is entirely one
    backtick-quoted name, package name alone in the cell, nothing else; the header row
    (literal text, no backticks) and the `|---|---|` separator row have no leading backtick and
    are silently skipped, and a package name mentioned in a later column (e.g. "extra of
    `psycopg`") is never in the first cell so it is never picked up as a row of its own.
    Everything outside the marker pair — dev-dependency tables, `tools/uiref`'s table, prose —
    is documentation for a human and is not read here."""
    pattern = rf"<!-- {re.escape(marker)}:start -->(.*?)<!-- {re.escape(marker)}:end -->"
    match = re.search(pattern, text, re.DOTALL)
    assert match, f"DEPENDENCIES.md is missing the {marker} marker block test_s110a reads"
    names: set[str] = set()
    for line in match.group(1).splitlines():
        cell = re.match(r"\s*\|\s*`([^`]+)`", line)
        if cell:
            names.add(cell.group(1))
    return names


def test_s110a_declared_dependencies_match_DEPENDENCIES_md():
    """AC-086, AC-183: set equality, both directions, against `DEPENDENCIES.md` — Python
    `[project.dependencies]` against the document's `s110a-python-runtime` marker block,
    `package.json` `dependencies` against `s110a-js-runtime`. Hardened from the original
    whole-word substring check (which a single paragraph naming every package, in any order,
    with no per-package accounting, would have passed): `docs/ACCEPTANCE.md` §7 records exactly
    that failure mode happening for real — an allowlist row once named `vue-router` while the
    shipped `package.json` actually carried `@konstantinopolskii/design-system` instead, "the
    count stayed right while the membership was wrong, and nothing caught it." Set equality in
    both directions is what catches it: a row for an undeclared package fails this test exactly
    as loudly as a declared package missing its row. Python names are matched as
    `python_direct_dependencies()` normalizes them (lowercase, extras bracket stripped); JS names
    are matched verbatim, case-sensitive, as `package.json` itself spells them."""
    if not DEPENDENCIES_MD.is_file():
        gate("docs/DEPENDENCIES.md does not exist yet (WP-31, wave 6)")
    text = DEPENDENCIES_MD.read_text(encoding="utf-8")
    runtime, _dev = python_direct_dependencies()
    js = js_direct_dependencies()
    documented_py = _marker_block_package_names(text, "s110a-python-runtime")
    documented_js = _marker_block_package_names(text, "s110a-js-runtime")
    missing = sorted((runtime - documented_py) | (js - documented_js))
    extra = sorted((documented_py - runtime) | (documented_js - js))
    assert not missing and not extra, (
        f"DEPENDENCIES.md disagrees with the declared dependency sets — "
        f"missing rows: {missing}; rows naming an undeclared package: {extra}"
    )


def test_s110b_zero_orm_or_migration_autogenerator():
    runtime, dev = python_direct_dependencies()
    js = js_direct_dependencies()
    hits = (runtime | dev | js | npm_package_names(PACKAGE_LOCK) | venv_dist_info_names()) & ORM_AND_MIGRATION_TOOLS
    assert not hits, f"raw SQL and numbered .sql files are the ruling; found: {sorted(hits)}"


def test_s110c_zero_analytics_telemetry_or_updater():
    runtime, dev = python_direct_dependencies()
    js = js_direct_dependencies()
    hits = (runtime | dev | js | npm_package_names(PACKAGE_LOCK) | venv_dist_info_names()) & ANALYTICS_AND_UPDATERS
    assert not hits, f"cut the wire (AC-191); found: {sorted(hits)}"


def test_s110d_built_bundle_has_no_foreign_absolute_url():
    dist = WEB_DIR / "dist"
    if not dist.is_dir():
        gate("web/dist/ does not exist yet (run `make build-web` first)")
    urls: list[str] = []
    for path in list(dist.rglob("*.js")) + list(dist.rglob("*.css")):
        urls += re.findall(r"https?://[^\s\"'`)]+", path.read_text(encoding="utf-8", errors="ignore"))
    foreign = sorted({u for u in urls if not u.startswith(ALLOWED_URL_PREFIXES)})
    assert not foreign, f"dist/ must carry no absolute URL off the app's own origin: {foreign}"


def test_dependencies_rule_catches_a_planted_orm():
    runtime = {"psycopg", "fastapi", "sqlalchemy"}
    hits = runtime & ORM_AND_MIGRATION_TOOLS
    assert hits == {"sqlalchemy"}, f"expected the planted sqlalchemy entry alone, got {hits}"


def test_dependencies_rule_catches_a_planted_foreign_url(scratch_dir):
    victim = scratch_dir / "bundle.js"
    victim.write_text('const t = "https://evil-telemetry.example.com/collect";')
    urls = re.findall(r"https?://[^\s\"'`)]+", victim.read_text(encoding="utf-8"))
    foreign = [u for u in urls if not u.startswith(ALLOWED_URL_PREFIXES)]
    assert foreign == ["https://evil-telemetry.example.com/collect"], foreign


def test_dependencies_rule_allows_the_declared_vue_error_reference_link(scratch_dir):
    victim = scratch_dir / "bundle.js"
    victim.write_text('t=`https://vuejs.org/error-reference/#runtime-${r}`')
    urls = re.findall(r"https?://[^\s\"'`)]+", victim.read_text(encoding="utf-8"))
    foreign = [u for u in urls if not u.startswith(ALLOWED_URL_PREFIXES)]
    assert foreign == [], f"the declared vuejs.org allowance must not be flagged, got {foreign}"


# --- the pins are only as good as the environment that honours them -------------------------
#
# No scenario id: S-110's steps are the allowlist audit (membership), and these two check
# something else — that the pinned *versions* are the ones actually installed, and that the
# library API a pin exists to protect still exists. `docs/E2E.md` names neither, so per the
# naming law they stay `test_dependencies_*` and claim nothing.


def _pinned_versions() -> dict[str, str]:
    """`{name: version}` for every `[project.dependencies]` entry pinned with a bare `==`."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for spec in data.get("project", {}).get("dependencies", []):
        if (m := re.fullmatch(r"([^\[=<>!~; ]+)(?:\[[^\]]*\])?==([^,;\s]+)", spec.strip())):
            out[m.group(1).strip().lower().replace("_", "-")] = m.group(2)
    return out


def test_dependencies_every_pin_matches_the_installed_version():
    """A pin nobody honours is decoration. This is the check that makes `==` mean something
    inside a venv that has been hand-`pip install`ed, upgraded by a stray `--upgrade`, or built
    from a `pyproject.toml` edited after the install.

    It is also what makes the `psycopg-pool==3.3.1` line load-bearing rather than cosmetic.
    That line exists because `psycopg` declares its own `pool` extra as bare
    `psycopg-pool; extra == "pool"` — **no version constraint of any kind** — so with no Python
    lockfile in this project, a fresh install takes whatever is newest that day. The pool's
    *behaviour* is asserted (S-46, AC-079) against a shrink policy that is an implementation
    detail of that package, not a documented API. A pin and this test fail at different moments
    and that is the point: the pin refuses the upgrade at install time, this test names what
    drifted at run time, on a machine where the install already went wrong.

    Deliberately general — every `==` in `[project.dependencies]`, not a hardcoded psycopg-pool
    check. The next unpinned transitive gets the same guard for free.
    """
    from importlib.metadata import PackageNotFoundError, version

    drifted: list[str] = []
    for name, pinned in sorted(_pinned_versions().items()):
        try:
            installed = version(name)
        except PackageNotFoundError:
            drifted.append(f"{name}: pinned =={pinned}, not installed at all")
            continue
        if installed != pinned:
            drifted.append(f"{name}: pinned =={pinned}, installed {installed}")
    assert not drifted, "the venv does not match pyproject.toml: " + "; ".join(drifted)


def test_dependencies_the_pool_api_the_pin_protects_still_exists():
    """`verticals/db/pool.py` passes `max_idle` explicitly and `open_pool` guards it. If a
    psycopg-pool upgrade ever renames or drops that keyword, `open_pool` raises `TypeError` at
    the first boot after the upgrade — a runtime failure on a self-hoster's box, discovered by
    them. This turns that into a failing test on ours.

    Asserted against the signature rather than by constructing a pool: this suite opens no
    network (its own module docstring), and the live half — that `open_pool(dsn).max_idle` is
    really 300.0, and that `max_idle=0` is refused — is `tests/http/test_pool.py`'s, where a
    database exists.
    """
    import inspect

    from psycopg_pool import ConnectionPool

    params = inspect.signature(ConnectionPool.__init__).parameters
    assert "max_idle" in params, (
        f"psycopg_pool.ConnectionPool no longer accepts `max_idle`; verticals/db/pool.py passes it "
        f"explicitly and would raise TypeError at boot. Parameters: {sorted(params)}"
    )


def test_dependencies_pin_rule_catches_a_planted_version_drift():
    """Both directions, on the comparison itself — the real one above passes only while the venv
    is clean, so on its own it is a check that has never been observed failing."""
    pinned = {"psycopg-pool": "3.3.1", "fastapi": "0.141.1"}
    installed = {"psycopg-pool": "3.4.0", "fastapi": "0.141.1"}
    drifted = [f"{n}: pinned =={v}, installed {installed[n]}" for n, v in pinned.items() if installed[n] != v]
    assert drifted == ["psycopg-pool: pinned ==3.3.1, installed 3.4.0"], drifted

    assert [f"{n}" for n, v in pinned.items() if pinned[n] != v] == [], "a clean venv must flag nothing"


def test_dependencies_pin_rule_reads_the_extras_bracket_off_the_parent():
    """The parser must see `psycopg[binary,pool]==3.3.4` as `psycopg` at `3.3.4` — not as a name
    containing a bracket, which would report a spurious "not installed" for every extra'd pin."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    specs = data["project"]["dependencies"]
    assert any(s.startswith("psycopg[") for s in specs), "fixture drift: no extra'd spec to parse"
    pins = _pinned_versions()
    assert pins["psycopg"] == "3.3.4", pins
    assert pins["psycopg-pool"] == "3.3.1", pins
    assert not any("[" in name for name in pins), f"a bracket survived name normalization: {sorted(pins)}"
