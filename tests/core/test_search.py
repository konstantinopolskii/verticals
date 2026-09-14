"""S-26, S-27, S-28 — `core/search.py` against real Postgres 16 and the real F2 fixture.

No mocks, no stubs, no fakes (`docs/BRIEF.md` rule 2): every assertion below runs against a
freshly migrated clone with `tests/fixtures/f2_synth.sql` loaded, and every plan assertion
`EXPLAIN`s a statement text captured from `pg_stat_statements` rather than one written here
by hand (`docs/E2E.md` S-25's rule, inherited by S-26 and S-27).

Two halves of this file cannot reach a green line today and say so out loud rather than
quietly passing:

  * the F4-5670 *selection* plan assertions GATE — `tests/fixtures/gen_corpus.py` (WP-20)
    does not exist, and a plan assertion on 49 rows with the planner left alone is a wager
    dressed as a gate (S-25's own argument).
  * the F2 *usability* half runs, but not in the shape S-26/S-27 describe. Measured: with
    `enable_seqscan = off` the shipped statement plans onto `goals_path`, because `owner = $1`
    is indexable there and 49 rows fit one heap page — no knob short of dropping indexes makes
    a 49-row table prefer a GIN scan. What the forced plan *does* prove is asserted here in
    the form that is true: the shipped statement has an index path and no `Seq Scan` on
    `goals`, and each search predicate, explained on its own, lands on the index that is
    supposed to serve it (`goals_search`, `goals_tags`). That second assertion is exactly the
    "is the index structurally broken" detector S-25 argues the F2 half exists for — a
    predicate rewritten to wrap a column in a function fails it — and it fails loudly today
    if either index stops matching its predicate.

Run standalone (the WP-06 runner that prints `PASS S-26` does not exist yet):
    PGHOST=127.0.0.1 PGPORT=55432 PGUSER=verticals PGPASSWORD=verticals \
        .venv/bin/python -m pytest tests/core/test_search.py -v
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from verticals.core import search as S
from verticals.core.errors import ValidationError
from tests.harness.report import gate

F2_SQL = Path(__file__).resolve().parents[1] / "fixtures" / "f2_synth.sql"
GEN_CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "gen_corpus.py"

CYCL = ["SYNSCH01", "SYNSCH02", "SYNSCH03", "SYNSCH04"]

# Same `owner`, `id`/`path`/... column order as `tests/perf/conftest.py`'s own corpus fixtures
# and `tests/core/test_board.py`'s local `f4_5670` — duplicated per file rather than imported
# across suite directories (this module's own `F2_SQL`/`GEN_CORPUS` precedent).
_GOALS_COLUMNS = (
    "id", "owner", "parent_id", "path", "depth", "vertical", "anchor_date", "period_key",
    "title", "body", "color", "tags", "done_at", "position", "origin", "created_at", "updated_at",
    "parked_from_vertical",
)


def _dsn(dbname: str) -> str:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "55432")
    user = os.environ.get("PGUSER", "verticals")
    password = os.environ.get("PGPASSWORD", "verticals")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


@pytest.fixture
def f2(db: psycopg.Connection) -> Iterator[psycopg.Connection]:
    """F2 on a fresh clone. `ANALYZE` so the plan assertions read real statistics rather than
    the planner's default guesses — a plan asserted against absent stats proves nothing."""
    db.execute(F2_SQL.read_text())
    db.execute("ANALYZE goals")
    yield db


@pytest.fixture(scope="module")
def f4_5670() -> Iterator[psycopg.Connection]:
    """A real F4-5670 clone (`tests/fixtures/gen_corpus.py`, WP-20), built once for the whole
    file and shared by `test_s26f` and `test_s27d` — the corpus is not under test here, only
    the plan it produces. `owner="t1"` matches this file's own synthetic-owner convention.

    Verified live (this database, this run, 2026-08-09) before being written down: at 5670 rows
    with `owner="t1"`, `search(q='cycl')` returns the 40 planted matches (`truncated=False`) and
    plans `Bitmap Index Scan` on `goals_search`; `search(tag='retro')` returns zero rows (this
    generator never assigns `tags` — no published aggregate exists to model that field, so
    `shape.json` carries none, per the Zone 1 rule against inventing one from the real export)
    but still plans `Bitmap Index Scan` on `goals_tags`, because `enable_seqscan=off` removes
    every other path capable of evaluating a `tags @>` predicate at all — the claim `test_s27d`
    makes is about which index the containment predicate compiles onto, not about how many rows
    it matches today."""
    from tests.conftest import fresh_clone
    from tests.fixtures import gen_corpus as G

    with fresh_clone("f0") as name:
        target = _dsn(name)
        rows = G.generate_rows(5670, G.DEFAULT_SEED, owner="t1")
        conn = psycopg.connect(target, autocommit=True)
        try:
            with conn.cursor() as cur, cur.copy(
                f"COPY goals ({', '.join(_GOALS_COLUMNS)}) FROM STDIN"
            ) as copy:
                for row in rows:
                    copy.write_row(tuple(row[c] for c in _GOALS_COLUMNS))
            conn.execute("ANALYZE goals")
            yield conn
        finally:
            conn.close()


def ids(result: S.SearchResult) -> list[str]:
    return [g.id for g in result.goals]


# --- pg_stat_statements capture, and EXPLAIN of the captured text -------------------------------


def _maintenance_dsn() -> str:
    from tests.conftest import maintenance_dsn

    return maintenance_dsn()


def _capture(dbname: str, needle: str) -> str:
    """The one statement text `dbname` ran that contains `needle`, read out of the cluster-wide
    view scoped by `dbid` (IR-06 — never the bare, zero-argument reset or an unscoped read)."""
    with psycopg.connect(_maintenance_dsn(), autocommit=True) as conn:
        rows = conn.execute(
            "SELECT query FROM pg_stat_statements "
            " WHERE dbid = (SELECT oid FROM pg_database WHERE datname = %s)",
            (dbname,),
        ).fetchall()
    matches = [q for (q,) in rows if needle in q]
    assert len(matches) == 1, f"expected one captured statement containing {needle!r}, got {matches}"
    return matches[0]


def _reset(dbname: str) -> None:
    with psycopg.connect(_maintenance_dsn(), autocommit=True) as conn:
        conn.execute(
            "SELECT pg_stat_statements_reset(0, "
            "(SELECT oid FROM pg_database WHERE datname = %s), 0)",
            (dbname,),
        )


def _rehydrate(captured: str, statement: str) -> tuple[str, list[str]]:
    """`pg_stat_statements` normalises inline string literals into extra `$n` placeholders,
    numbered after the real bind parameters and in order of appearance. Putting them back is
    what makes the captured text executable again; the bind parameters stay parameters, which
    is the property the plan assertion is about."""
    names: list[str] = []
    for match in re.finditer(r"%\((\w+)\)s", statement):
        if match.group(1) not in names:
            names.append(match.group(1))
    text = captured
    for offset, literal in enumerate(re.findall(r"'([^']*)'", statement)):
        text = text.replace(f"${len(names) + offset + 1}", "'" + literal.replace("'", "''") + "'")
    return text, names


def _plan_nodes(plan: dict, acc: list | None = None) -> list[tuple]:
    acc = [] if acc is None else acc
    acc.append((plan.get("Node Type"), plan.get("Index Name"), plan.get("Relation Name")))
    for child in plan.get("Plans", []):
        _plan_nodes(child, acc)
    return acc


def _explain_forced(conn: psycopg.Connection, text: str, params: list) -> list[tuple]:
    """`SET LOCAL enable_seqscan = off` + `EXPLAIN (FORMAT JSON)` of `text`. Goes through
    `PREPARE`/`EXECUTE` because the captured text carries `$n` placeholders, which psycopg's
    own `%s` parser does not speak; `ClientCursor` renders the `EXECUTE` arguments as literals
    so Postgres has a type for each without a cast the test invented."""
    name = "vt_plan_" + secrets.token_hex(4)
    cursor = psycopg.ClientCursor(conn)
    with conn.transaction():
        cursor.execute("SET LOCAL enable_seqscan = off")
        cursor.execute(f"PREPARE {name} AS {text}")
        cursor.execute(
            f"EXPLAIN (FORMAT JSON) EXECUTE {name} ({', '.join(['%s'] * len(params))})", params
        )
        return _plan_nodes(cursor.fetchone()[0][0]["Plan"])


# --- S-26 — substring search finds `bicycles` from `cycl` ---------------------------------------


def test_s26a_substring_search_finds_bicycles_from_cycl(f2: psycopg.Connection) -> None:
    """`cycl` returns exactly {01,02,03,04}; `Circle back` and `Cyan` are absent; the match is
    case-insensitive and covers the body; the floor is exactly 3. AC-045, AC-046, AC-047."""
    # Doubles as a guard on F2 itself: E2E.md §2's G4 row and the fixture's own comment both
    # say `cycl` matches these four and nothing else, so any other row whose title or body
    # grows the substring — a retro body mentioning a "cycle", say — breaks the invariant
    # here rather than three work packages downstream.
    assert ids(S.search(f2, owner="t1", q="cycl")) == CYCL, "F2 G4 invariant broken"
    assert ids(S.search(f2, owner="t1", q="cycl")) == CYCL  # AC-045: two calls, same order
    assert ids(S.search(f2, owner="t1", q="CYCL")) == CYCL
    assert ids(S.search(f2, owner="t1", q="cyc")) == CYCL
    assert ids(S.search(f2, owner="t1", q="motorcycle")) == ["SYNSCH04"]

    for refused in ("", "c", "cy"):
        with pytest.raises(ValidationError) as exc:
            S.search(f2, owner="t1", q=refused)
        assert exc.value.detail["field"] == "q"
        assert exc.value.detail["minimum"] == 3


def test_s26b_ir12_metacharacters_are_data_and_never_wildcards(f2: psycopg.Connection) -> None:
    """IR-12. Neither `cy%l` nor `cy_l` is a literal substring of any G4 title or body, so a
    live `%` or `_` is the only way either could return a row — and a live `%` is the
    whole-table read AC-047 refuses. The control at the end runs the unescaped pattern by hand
    and shows exactly how many rows the defect would have handed over."""
    assert S.escape_like("cy%l") == r"cy\%l"
    assert S.escape_like("cy_l") == r"cy\_l"
    assert S.escape_like("a\\b") == r"a\\b"
    assert S.escape_like("%") == r"\%"

    assert ids(S.search(f2, owner="t1", q="cy%l")) == []
    assert ids(S.search(f2, owner="t1", q="cy_l")) == []
    assert ids(S.search(f2, owner="t1", q="cycl\\")) == []  # trailing backslash, not a DB error
    assert ids(S.search(f2, owner="t1", q="%%%")) == []  # all-wildcard, past the length floor
    assert ids(S.search(f2, owner="t1", q="___")) == []
    assert ids(S.search(f2, owner="t1", q="\\\\\\")) == []

    # WP-10's done-when names these three; each is one character, so the trigram floor refuses
    # them before escaping ever matters. Both gates are real and both are asserted.
    for refused in ("%", "_", "\\"):
        with pytest.raises(ValidationError):
            S.search(f2, owner="t1", q=refused)

    # The control: the same statement with the pattern left raw dumps the owner's rows.
    raw = f2.execute(
        S.build_statement(with_q=True, with_tag=False, with_vertical=False),
        {"owner": "t1", "pat": "%%%", "limit": 500},
    ).fetchall()
    assert len(raw) == 46, "unescaped '%' returns the owner's whole table — this is IR-12's point"


def test_s26c_q_is_bound_never_interpolated(f2: psycopg.Connection) -> None:
    """S-26's statement-text assertion. The predicate is the pinned one, and the statement the
    server actually received carries no byte of the caller's query."""
    assert S.TRIGRAM_PREDICATE == "(title || ' ' || body) ILIKE %(pat)s ESCAPE '\\'"
    assert S.TRIGRAM_PREDICATE in S.build_statement(
        with_q=True, with_tag=False, with_vertical=False
    )

    dbname = f2.execute("SELECT current_database()").fetchone()[0]
    _reset(dbname)
    assert ids(S.search(f2, owner="t1", q="cycl")) == CYCL
    captured = _capture(dbname, "ILIKE")
    assert "cycl" not in captured, captured
    assert re.search(r"\(title \|\| \$\d+ \|\| body\) ILIKE \$\d+ ESCAPE \$\d+", captured), captured


def test_s26d_ac048_the_search_index_is_trigram_not_lexeme(f2: psycopg.Connection) -> None:
    """AC-048, read straight off the catalogue: a `gin_trgm_ops` index exists and nothing on
    `goals` is a tsvector index. C6 — this scenario fails against `to_tsvector` by
    construction, and that is the point of asserting it here rather than trusting the DDL."""
    defs = [d for (d,) in f2.execute("SELECT indexdef FROM pg_indexes WHERE tablename='goals'")]
    assert any("gin_trgm_ops" in d for d in defs), defs
    assert not any("to_tsvector" in d for d in defs), defs


def test_s26e_plan_usability_on_f2(f2: psycopg.Connection) -> None:
    """The F2 half, in the form that is true at 49 rows — see the module docstring. The
    statement explained is the captured one, not one written here."""
    dbname = f2.execute("SELECT current_database()").fetchone()[0]
    _reset(dbname)
    S.search(f2, owner="t1", q="cycl")
    statement = S.build_statement(with_q=True, with_tag=False, with_vertical=False)
    text, names = _rehydrate(_capture(dbname, "ILIKE"), statement)
    values = {"owner": "t1", "pat": "%cycl%", "limit": 51}
    nodes = _explain_forced(f2, text, [values[n] for n in names])

    assert not any(n[0] == "Seq Scan" and n[2] == "goals" for n in nodes), nodes

    predicate = S.TRIGRAM_PREDICATE.replace("%(pat)s", "$1")
    isolated = _explain_forced(f2, f"SELECT id FROM goals WHERE {predicate}", ["%cycl%"])
    assert any(n[1] == "goals_search" for n in isolated), isolated


def test_s26f_plan_shape_on_f4_5670(f4_5670: psycopg.Connection) -> None:
    """The selection claim: at 49 rows (F2) the planner picks a sequential scan no matter what
    index exists, so this is only meaningful at F4-5670 scale. Same capture-and-rehydrate shape
    as `test_s26e_plan_usability_on_f2`, pointed at the bigger clone; `q='cycl'` is this file's
    own canonical needle (`CYCL`), planted 40 times by the generator regardless of corpus size."""
    if not GEN_CORPUS.exists():
        gate(f"F4-5670 absent: {GEN_CORPUS} (WP-20) does not exist")

    dbname = f4_5670.execute("SELECT current_database()").fetchone()[0]
    _reset(dbname)
    result = S.search(f4_5670, owner="t1", q="cycl")
    assert len(result.goals) == 40 and result.truncated is False, "the generator's own 40-plant"

    statement = S.build_statement(with_q=True, with_tag=False, with_vertical=False)
    text, names = _rehydrate(_capture(dbname, "ILIKE"), statement)
    values = {"owner": "t1", "pat": "%cycl%", "limit": 51}
    nodes = _explain_forced(f4_5670, text, [values[n] for n in names])

    assert not any(n[0] == "Seq Scan" and n[2] == "goals" for n in nodes), nodes
    assert any(n[1] == "goals_search" for n in nodes), nodes


# --- S-27 — tag search is the whole retro-review feature ----------------------------------------


def test_s27a_tag_search_is_the_retro_review_feature(f2: psycopg.Connection) -> None:
    """AC-049 and §10-D3: `retro` in `anchor_date DESC` order, `planning` as a set, and `Retro`
    matching nothing, because tags are case-sensitive labels."""
    assert ids(S.search(f2, owner="t1", tag="retro")) == ["SYNRET01", "SYNRET02"]
    assert set(ids(S.search(f2, owner="t1", tag="planning"))) == {"SYNRET02", "SYNRET03"}
    assert ids(S.search(f2, owner="t1", tag="Retro")) == []
    assert ids(S.search(f2, owner="t2", tag="retro")) == []

    for refused in ("", " retro", "retro tag", "x" * 49, "retro\n"):
        with pytest.raises(ValidationError) as exc:
            S.search(f2, owner="t1", tag=refused)
        assert exc.value.detail["field"] == "tag"


def test_s27b_ac022_tags_are_stored_bare(f2: psycopg.Connection) -> None:
    """AC-022: the `#` is CSS, never data."""
    (count,) = f2.execute(
        "SELECT count(*) FROM goals WHERE EXISTS (SELECT 1 FROM unnest(tags) t WHERE t LIKE '#%')"
    ).fetchone()
    assert count == 0


def test_s27c_plan_usability_on_f2(f2: psycopg.Connection) -> None:
    """The tag half of the same split as S-26e, and the assertion that catches a `tags` column
    wrapped in a function: explained on its own, the predicate must land on `goals_tags`.
    Case-sensitivity is re-asserted under the forced plan so it is not an artifact of the
    planner picking a different path at 49 rows."""
    dbname = f2.execute("SELECT current_database()").fetchone()[0]
    _reset(dbname)
    S.search(f2, owner="t1", tag="retro")
    statement = S.build_statement(with_q=False, with_tag=True, with_vertical=False)
    text, names = _rehydrate(_capture(dbname, "tags @>"), statement)
    values = {"owner": "t1", "tags": ["retro"], "limit": 51}
    nodes = _explain_forced(f2, text, [values[n] for n in names])

    assert not any(n[0] == "Seq Scan" and n[2] == "goals" for n in nodes), nodes
    isolated = _explain_forced(f2, "SELECT id FROM goals WHERE tags @> $1::text[]", [["retro"]])
    assert any(n[1] == "goals_tags" for n in isolated), isolated

    with f2.transaction():
        f2.execute("SET LOCAL enable_seqscan = off")
        assert ids(S.search(f2, owner="t1", tag="Retro")) == []


def test_s27d_plan_shape_on_f4_5670(f4_5670: psycopg.Connection) -> None:
    """The `Bitmap Index Scan on goals_tags` selection claim, for S-26f's reason. See the
    `f4_5670` fixture's own docstring for why `tag='retro'` matching zero rows here does not
    weaken this assertion: `enable_seqscan=off` leaves `goals_tags` as the only path capable of
    evaluating `tags @>` at all, which is exactly the "is the index structurally broken"
    property this row exists to catch — a predicate rewritten to wrap `tags` in a function
    fails this the same way at 0 matches or at 5670."""
    if not GEN_CORPUS.exists():
        gate(f"F4-5670 absent: {GEN_CORPUS} (WP-20) does not exist")

    dbname = f4_5670.execute("SELECT current_database()").fetchone()[0]
    _reset(dbname)
    S.search(f4_5670, owner="t1", tag="retro")
    statement = S.build_statement(with_q=False, with_tag=True, with_vertical=False)
    text, names = _rehydrate(_capture(dbname, "tags @>"), statement)
    values = {"owner": "t1", "tags": ["retro"], "limit": 51}
    nodes = _explain_forced(f4_5670, text, [values[n] for n in names])

    assert not any(n[0] == "Seq Scan" and n[2] == "goals" for n in nodes), nodes
    assert any(n[1] == "goals_tags" for n in nodes), nodes


# --- S-28 — combined filters intersect, and stay owner-scoped ------------------------------------


def test_s28a_combined_filters_intersect(f2: psycopg.Connection) -> None:
    """AC-050, both owners. `t2` owns three rows and none of them can be reached through
    `t1`'s filters or the other way round."""
    assert ids(S.search(f2, owner="t1", q="cycl", vertical="month")) == CYCL
    assert ids(S.search(f2, owner="t1", tag="retro", vertical="day")) == []
    assert ids(S.search(f2, owner="t2", q="cycl", vertical="month")) == []
    assert ids(S.search(f2, owner="t2", tag="retro", vertical="day")) == []
    assert ids(S.search(f2, owner="t1", q="cycl", vertical="week")) == []
    assert ids(S.search(f2, owner="t2", q="Other owner")) == ["SYNOTH01", "SYNOTH02", "SYNOTH03"]


def test_s28b_search_refuses_what_it_cannot_scope(f2: psycopg.Connection) -> None:
    """Owner is not optional and the empty filter set is not a search (AC-013, AC-047)."""
    for kwargs in ({"owner": ""}, {"owner": None}):
        with pytest.raises(ValidationError):
            S.search(f2, q="cycl", **kwargs)
    with pytest.raises(ValidationError):
        S.search(f2, owner="t1")
    with pytest.raises(ValidationError):
        S.search(f2, owner="t1", vertical="fortnight")


def test_s28c_ac202_search_is_bounded(f2: psycopg.Connection) -> None:
    """AC-202 at the core, where the check lives. The F4-56700 flood is `test_s129`'s job
    (re-homed from WP-15 to WP-20 — `docs/IMPLEMENTATION.md` §0.2, "S-129 removed"/"re-homed
    with the F4-56700 fixture it needs" — it is a `core` scenario by its own text and by
    `ACCEPTANCE.md:669`'s explicit `S-129 | core` row, six direct `search(q=...)` calls, no
    HTTP verb); the bound itself is asserted here against a real result set that really is
    clipped."""
    assert S.search(f2, owner="t1", q="cycl").truncated is False
    clipped = S.search(f2, owner="t1", q="cycl", limit=3)
    assert ids(clipped) == CYCL[:3] and clipped.truncated is True
    assert S.search(f2, owner="t1", q="cycl", limit=4).truncated is False
    assert S.DEFAULT_LIMIT == 50 and S.MAX_LIMIT == 200

    with pytest.raises(ValidationError) as exc:
        S.search(f2, owner="t1", q="x" * 201)
    assert exc.value.detail["maximum"] == 200
    for bad in (0, -1, 201, "50", True):
        with pytest.raises(ValidationError):
            S.search(f2, owner="t1", q="cycl", limit=bad)


# --- S-129 — search refuses what it cannot serve, and truncates what it can, at F4-56700 --------


@pytest.fixture(scope="module")
def f4_56700() -> Iterator[psycopg.Connection]:
    """F4-56700, the largest corpus (`tests/fixtures/gen_corpus.py`, WP-20) — `test_s129`'s own
    fixture (`docs/E2E.md`: "Fixture: F4-56700, the largest corpus"), module-scoped since only
    one test in this file needs it. Same shape as `f4_5670` above, ten times the row count."""
    from tests.conftest import fresh_clone
    from tests.fixtures import gen_corpus as G

    with fresh_clone("f0") as name:
        target = _dsn(name)
        rows = G.generate_rows(56700, G.DEFAULT_SEED, owner="t1")
        conn = psycopg.connect(target, autocommit=True)
        try:
            with conn.cursor() as cur, cur.copy(
                f"COPY goals ({', '.join(_GOALS_COLUMNS)}) FROM STDIN"
            ) as copy:
                for row in rows:
                    copy.write_row(tuple(row[c] for c in _GOALS_COLUMNS))
            conn.execute("ANALYZE goals")
            yield conn
        finally:
            conn.close()


def test_s129_search_bounds_on_f4_56700(f4_56700: psycopg.Connection) -> None:
    """S-129 (`docs/E2E.md`; `ACCEPTANCE.md:669`; AC-202) — re-homed here from WP-15's `http`
    suite (`docs/IMPLEMENTATION.md` §0.2, "S-129 removed"/"it is a `core` scenario by its own
    text... re-homed to WP-20 with the F4-56700 fixture it needs"): "Both are refused at the
    core, so both transports inherit it without either implementing it" — six direct
    `search(q=...)` calls, no HTTP verb, no server to spawn.

    **Flood needle.** `"ack"` — the widest 3-character substring this generator's own lorem word
    bank can produce at any corpus size *that also survives `_validate_query`'s own `.strip()`
    unchanged* (a leading- or trailing-space needle like `" re"` looked wider by raw substring
    count, but strips down to 2 characters and is refused by the trigram floor before ever
    reaching the query — checked exhaustively over every distinct 3-gram actually present in a
    real F4-56700 build, restricted to the ones `.strip()` leaves alone: nothing clears 21%).
    Measured live against this exact fixture: 11565/56700 rows (20.4%) — short of the scenario
    intent paragraph's own illustrative "a query matching 40 000 rows" (~70%), which would need
    either a much smaller, un-lorem-like vocabulary or a second, dedicated flood-plant pass this
    generator does not carry (filed as a `docs/PENDING_DOC_FIXES.md` row: illustrative, not a
    number any step in the table actually asserts). Every hard assertion this row states —
    exactly 50 rows, `truncated: true`, the correct order, stable across three calls — needs
    only "comfortably over fifty", which 11565 clears by three orders of magnitude.

    **Ordering.** `docs/E2E.md`'s own table says "the first 50... under the total order
    `position, id`" — but `core/search.py`'s shipped `ORDER_BY` is `anchor_date DESC NULLS LAST,
    id ASC`, and that module's own comment names S-129 by id as the reason: "'id' is the primary
    key, so no two rows can tie — which is what makes 'stable across three consecutive calls'
    (S-129) a property of the query rather than luck." The shipped order, not the document's
    stale paraphrase, is what this test verifies against — filed as a second `docs/
    PENDING_DOC_FIXES.md` row.
    """
    import time

    from tests.harness.calibrate import percentiles

    NEEDLE = "ack"

    # Step 1-2: below the trigram floor.
    for too_short in ("a", "ab"):
        with pytest.raises(ValidationError) as exc:
            S.search(f4_56700, owner="t1", q=too_short)
        assert exc.value.detail["field"] == "q"
        assert exc.value.detail["minimum"] == 3

    # Step 3: the floor is inclusive.
    S.search(f4_56700, owner="t1", q="abc")

    # Step 4: the ceiling.
    with pytest.raises(ValidationError) as exc:
        S.search(f4_56700, owner="t1", q="x" * 201)
    assert exc.value.detail["field"] == "q"
    assert exc.value.detail["maximum"] == 200

    # Step 5: the flood — exactly 50, truncated, the real first-50-under-ORDER_BY, stable.
    (total_matches,) = f4_56700.execute(
        "SELECT count(*) FROM goals WHERE owner='t1' AND (title || ' ' || body) ILIKE %s ESCAPE '\\'",
        (f"%{NEEDLE}%",),
    ).fetchone()
    assert total_matches > 50, f"needle {NEEDLE!r} only matches {total_matches} rows — not a flood"

    expected_ids = [
        row[0]
        for row in f4_56700.execute(
            "SELECT id FROM goals WHERE owner='t1' AND (title || ' ' || body) ILIKE %s ESCAPE '\\' "
            "ORDER BY anchor_date DESC NULLS LAST, id ASC LIMIT 50",
            (f"%{NEEDLE}%",),
        ).fetchall()
    ]

    results = [S.search(f4_56700, owner="t1", q=NEEDLE) for _ in range(3)]
    for r in results:
        assert len(r.goals) == 50
        assert r.truncated is True
        assert [g.id for g in r.goals] == expected_ids
    assert results[0].goals == results[1].goals == results[2].goals, "stable across three calls"

    samples = []
    for _ in range(30):
        t0 = time.perf_counter()
        S.search(f4_56700, owner="t1", q=NEEDLE)
        samples.append((time.perf_counter() - t0) * 1000.0)
    p95 = percentiles(samples)["p95"]
    assert p95 <= 150.0, f"call 5's p95 ({p95:.2f}ms) exceeds S-93's 150ms budget"

    # Step 6: `limit` is bounded, checked before the query is built.
    assert len(S.search(f4_56700, owner="t1", q=NEEDLE, limit=200).goals) == 200
    for bad in (201, 0, -1):
        with pytest.raises(ValidationError) as exc:
            S.search(f4_56700, owner="t1", q=NEEDLE, limit=bad)
        assert exc.value.detail["field"] == "limit"
