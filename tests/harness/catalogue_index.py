"""WP-02 catalogue reconciliation, made runnable.

docs/E2E.md is the scenario catalogue of record. docs/ACCEPTANCE.md is the criteria of
record. docs/IMPLEMENTATION.md section 9.1 owns every scenario and every criterion to a
work package. The three documents are edited independently and nothing forces them to
agree with each other -- this module is that force, expressed as six checks instead of
three paragraphs of prose that nobody re-reads after the merge.

Each check_N function below is one of the six "done when" items on the WP-02 card
(docs/IMPLEMENTATION.md section 2, "WP-02 -- Catalogue reconciliation"). Each takes no
arguments, reads the three markdown documents from disk, and returns (ok, message).
Nothing here imports the test harness, pytest, or anything under verticals/ -- this
module's only dependency is the standard library and the three documents themselves, so
it runs before there is a harness to run inside of, and it runs the same way from a
bare checkout with no database and no server.

Run directly:

    python -m tests.harness.catalogue_index

prints one PASS/FAIL line per check and exits 0 if all six pass, 1 otherwise.
docs/IMPLEMENTATION.md section 3.1's shared-file rule has WP-06's
tests/harness/test_runner_contract.py import run_all() and wrap each entry as an
assertion group inside S-124 -- this file does not do that wrapping itself and does not
know S-124 exists; it only knows how to read three files and compare what it finds.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
E2E_PATH = REPO_ROOT / "docs" / "E2E.md"
ACCEPTANCE_PATH = REPO_ROOT / "docs" / "ACCEPTANCE.md"
IMPLEMENTATION_PATH = REPO_ROOT / "docs" / "IMPLEMENTATION.md"

# The nine suite keys E2E.md section 1 names. Fixed by ruling, not derived -- something
# has to seed the search for a "## N. Suite X -- `key`" heading, and this is the
# smallest set that does it without also matching an unrelated backticked word that
# happens to sit in some other "## " heading.
KNOWN_SUITES = {
    "core", "http", "mcp", "ui", "pipeline", "perf", "uidiff", "static", "harness",
}

# Same id shapes IMPLEMENTATION.md section 9.2 and ACCEPTANCE.md section 11.3 already
# grep for -- reused verbatim so this module can never disagree with them about what an
# id looks like.
SCENARIO_ID_RE = re.compile(r"S-\d{2,3}")
CRITERION_ID_RE = re.compile(r"AC-\d{3}")

HEADING_ID_RE = re.compile(r"^###[ \t]+(S-\d{2,3})\b", re.MULTILINE)
BOLD_ROW_ID_RE = re.compile(r"^\|\s*\*\*(S-\d{2,3})\*\*", re.MULTILINE)
SUITE_HEADING_RE = re.compile(r"^##[ \t]+.*$", re.MULTILINE)
BACKTICK_RE = re.compile(r"`(\w+)`")

E2E_SUITE_TABLE_HEADER = "| suite | runner | process reality | count |"
ACCEPTANCE_SCENARIO_TABLE_HEADER = "| S | suite | intent | required by | first needed |"
OWNERSHIP_TABLE_HEADER = (
    "| WP | scenarios owned | criteria owned | also on the hook for (proved elsewhere) |"
)

VERDICT_BLOCK_MARKER = "=== VERTICALS E2E ==="
VERDICT_LINE_MARKER = "VERDICT:"
VERDICT_ROW_RE = re.compile(
    r"^(?P<suite>[a-z]+)\s+(?P<total>\d+)\s+(?P<pass>\d+)\s+(?P<fail>\d+)\s+"
    r"(?P<skip>\d+)\s+(?P<gate>\d+)\s+(?P<seconds>[\d.]+)\s*$"
)
VERDICT_TOTAL_RE = re.compile(
    r"^TOTAL\s+(?P<total>\d+)\s+(?P<pass>\d+)\s+(?P<fail>\d+)\s+"
    r"(?P<skip>\d+)\s+(?P<gate>\d+)\s+(?P<seconds>[\d.]+)\s*$"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _scenario_sort_key(sid: str) -> int:
    return int(sid.split("-")[1])


def _criterion_sort_key(cid: str) -> int:
    return int(cid.split("-")[1])


# ---------------------------------------------------------------------------------------
# Generic markdown-table extraction. Every check below reads a table this way rather than
# hand-parsing its own slice of a document, so there is exactly one place that knows what
# a markdown table looks like.
# ---------------------------------------------------------------------------------------


def _is_separator(line: str) -> bool:
    s = line.strip()
    return bool(s) and s.startswith("|") and set(s) <= set("|:- ")


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [cell.strip() for cell in s.split("|")]


def extract_table_rows(text: str, header_line: str) -> list[list[str]]:
    """Every data row of every markdown table in `text` whose header, stripped, equals
    `header_line` exactly. Scans the whole document rather than stopping at the first
    match, because ACCEPTANCE.md repeats its criteria-table header once per subsection
    and E2E.md's section 9 scenario table splits into two pieces the same way.
    """
    lines = text.splitlines()
    rows: list[list[str]] = []
    i = 0
    n = len(lines)
    while i < n:
        if lines[i].strip() == header_line:
            j = i + 1
            if j < n and _is_separator(lines[j]):
                j += 1
            while j < n and lines[j].strip().startswith("|"):
                rows.append(_split_row(lines[j]))
                j += 1
            i = j
        else:
            i += 1
    return rows


# ---------------------------------------------------------------------------------------
# The catalogue, extracted from E2E.md the way IMPLEMENTATION.md section 9.2 already
# extracts it: "### S-nnn" headings, union the perf-shaped table rows that never got a
# heading of their own.
# ---------------------------------------------------------------------------------------


def _suite_sections(text: str) -> list[tuple[int, str]]:
    """[(char_offset, suite_key), ...] in document order, one per "## ... `key`" heading
    where key is a known suite. A given offset belongs to the last section whose start is
    at or before it.
    """
    sections: list[tuple[int, str]] = []
    for m in SUITE_HEADING_RE.finditer(text):
        heading = m.group(0)
        for token in BACKTICK_RE.findall(heading):
            if token in KNOWN_SUITES:
                sections.append((m.start(), token))
                break
    return sections


def _suite_at(offset: int, sections: list[tuple[int, str]]) -> str | None:
    result: str | None = None
    for start, suite in sections:
        if start <= offset:
            result = suite
        else:
            break
    return result


class Catalogue:
    """The scenario catalogue as E2E.md actually defines it, not as any document
    restates it."""

    def __init__(self, ids_to_suite: dict[str, str | None], problems: list[str]):
        self.ids_to_suite = ids_to_suite
        self.problems = problems  # duplicate-definition findings, if any

    @property
    def ids(self) -> set[str]:
        return set(self.ids_to_suite)


def build_catalogue(e2e_text: str) -> Catalogue:
    sections = _suite_sections(e2e_text)
    problems: list[str] = []

    heading_offsets: dict[str, list[int]] = {}
    for m in HEADING_ID_RE.finditer(e2e_text):
        heading_offsets.setdefault(m.group(1), []).append(m.start())

    bold_offsets: dict[str, list[int]] = {}
    for m in BOLD_ROW_ID_RE.finditer(e2e_text):
        bold_offsets.setdefault(m.group(1), []).append(m.start())

    ids_to_suite: dict[str, str | None] = {}

    for sid, offsets in sorted(heading_offsets.items()):
        if len(offsets) > 1:
            suites = sorted({_suite_at(o, sections) or "?" for o in offsets})
            problems.append(
                f"{sid} has {len(offsets)} '### {sid}' headings (suites: {suites})"
            )
        ids_to_suite[sid] = _suite_at(offsets[0], sections)

    # Table-only ids: a bold leading-cell row for an id that never got its own heading --
    # E2E.md section 1's documented perf shape, S-91..S-99. A bold row for an id that DOES
    # have a heading is a mention (E2E.md has exactly one such table, the "scenarios that
    # own the server" cross-reference for S-45/S-89/S-126), not a second definition, and
    # is deliberately not counted here -- only ids absent from heading_offsets fall
    # through to this loop.
    for sid, offsets in sorted(bold_offsets.items()):
        if sid in heading_offsets:
            continue
        if len(offsets) > 1:
            suites = sorted({_suite_at(o, sections) or "?" for o in offsets})
            problems.append(
                f"{sid} has {len(offsets)} table-only definitions and no heading "
                f"(suites: {suites})"
            )
        ids_to_suite[sid] = _suite_at(offsets[0], sections)

    return Catalogue(ids_to_suite, problems)


def parse_e2e_suite_table(e2e_text: str) -> dict[str, int]:
    table: dict[str, int] = {}
    for cells in extract_table_rows(e2e_text, E2E_SUITE_TABLE_HEADER):
        if len(cells) != 4:
            continue
        names = BACKTICK_RE.findall(cells[0])
        if not names:
            continue
        try:
            table[names[0]] = int(cells[3])
        except ValueError:
            continue
    return table


def parse_e2e_verdict_block(e2e_text: str) -> tuple[dict[str, int], int | None]:
    start = e2e_text.find(VERDICT_BLOCK_MARKER)
    if start == -1:
        return {}, None
    end = e2e_text.find(VERDICT_LINE_MARKER, start)
    block = e2e_text[start : end if end != -1 else len(e2e_text)]

    totals: dict[str, int] = {}
    grand_total: int | None = None
    for line in block.splitlines():
        m = VERDICT_ROW_RE.match(line)
        if m and m.group("suite") in KNOWN_SUITES:
            totals[m.group("suite")] = int(m.group("total"))
            continue
        m = VERDICT_TOTAL_RE.match(line)
        if m:
            grand_total = int(m.group("total"))
    return totals, grand_total


# ---------------------------------------------------------------------------------------
# Check 1 -- the extraction is exactly section 1's suite table, no id twice, no id
# claimed by two suites.
# ---------------------------------------------------------------------------------------


def check_1_extraction_matches_suite_table() -> tuple[bool, str]:
    e2e_text = _read(E2E_PATH)
    catalogue = build_catalogue(e2e_text)
    suite_table = parse_e2e_suite_table(e2e_text)
    table_total = sum(suite_table.values())

    problems = list(catalogue.problems)
    if len(catalogue.ids) != table_total:
        problems.append(
            f"extracted {len(catalogue.ids)} scenario ids, section 1's suite table "
            f"sums to {table_total}"
        )
    unplaced = sorted(
        sid for sid, suite in catalogue.ids_to_suite.items() if suite is None
    )
    if unplaced:
        problems.append(f"{len(unplaced)} ids fall before any suite heading: {unplaced}")

    if problems:
        return False, "; ".join(problems)
    return True, (
        f"{len(catalogue.ids)} scenario ids extracted (headings union perf/static/"
        f"harness table rows), no duplicate definitions, none claimed by two suites, "
        f"matches section 1's total of {table_total}"
    )


# ---------------------------------------------------------------------------------------
# Check 2 -- per-suite counts agree, cell for cell, across the extraction, section 1's
# table, and section 12's verdict-block template.
# ---------------------------------------------------------------------------------------


def check_2_per_suite_counts_match() -> tuple[bool, str]:
    e2e_text = _read(E2E_PATH)
    catalogue = build_catalogue(e2e_text)
    suite_table = parse_e2e_suite_table(e2e_text)
    verdict_totals, verdict_grand_total = parse_e2e_verdict_block(e2e_text)

    extracted_counts: dict[str, int] = {}
    for suite in catalogue.ids_to_suite.values():
        if suite is not None:
            extracted_counts[suite] = extracted_counts.get(suite, 0) + 1

    problems: list[str] = []

    for suite in sorted(KNOWN_SUITES):
        extracted = extracted_counts.get(suite, 0)
        pinned = suite_table.get(suite)
        if pinned is None:
            problems.append(f"'{suite}' has no row in section 1's suite table")
        elif extracted != pinned:
            problems.append(
                f"'{suite}': extraction counts {extracted}, section 1 table says {pinned}"
            )

    non_harness = set(suite_table) - {"harness"}
    missing_from_verdict = non_harness - set(verdict_totals)
    if missing_from_verdict:
        problems.append(
            f"verdict-block template has no row for: {sorted(missing_from_verdict)}"
        )
    extra_in_verdict = set(verdict_totals) - non_harness
    if extra_in_verdict:
        problems.append(
            f"verdict-block template has an unexpected row for: {sorted(extra_in_verdict)}"
        )
    for suite, count in sorted(verdict_totals.items()):
        pinned = suite_table.get(suite)
        if pinned is not None and count != pinned:
            problems.append(
                f"'{suite}': verdict-block template says {count}, section 1 table "
                f"says {pinned}"
            )

    if verdict_grand_total is None:
        problems.append("verdict-block template has no TOTAL line")
    else:
        rows_sum = sum(verdict_totals.values())
        if verdict_grand_total != rows_sum:
            problems.append(
                f"verdict-block TOTAL is {verdict_grand_total}, its own rows sum "
                f"to {rows_sum}"
            )
        expected_total = sum(suite_table.values()) - suite_table.get("harness", 0)
        if verdict_grand_total != expected_total:
            problems.append(
                f"verdict-block TOTAL is {verdict_grand_total}, expected "
                f"{expected_total} (section 1's total minus harness)"
            )

    if problems:
        return False, "; ".join(problems)
    return True, (
        f"extraction, section 1's suite table and section 12's verdict-block template "
        f"agree cell for cell across all {len(KNOWN_SUITES)} suites; verdict TOTAL "
        f"{verdict_grand_total} correctly excludes harness"
    )


# ---------------------------------------------------------------------------------------
# Check 3 -- every scenario id cited anywhere in ACCEPTANCE.md exists in the catalogue,
# and every catalogue id is cited somewhere in ACCEPTANCE.md. The two `comm` directions
# of ACCEPTANCE.md section 11.3, against the extracted set rather than the hardcoded
# `seq -f 'S-%02g' 1 134` that section's own script uses -- a literal replay of that
# line would drift the moment scenario 135 is minted, which is the exact failure mode
# this whole module exists to catch.
# ---------------------------------------------------------------------------------------


def check_3_acceptance_citations_exist() -> tuple[bool, str]:
    e2e_text = _read(E2E_PATH)
    acceptance_text = _read(ACCEPTANCE_PATH)
    catalogue = build_catalogue(e2e_text)

    cited = set(SCENARIO_ID_RE.findall(acceptance_text))
    all_scenarios = catalogue.ids

    uncited = sorted(all_scenarios - cited, key=_scenario_sort_key)
    nonexistent = sorted(cited - all_scenarios, key=_scenario_sort_key)

    problems = []
    if uncited:
        problems.append(
            f"{len(uncited)} catalogue ids never cited in ACCEPTANCE.md: {uncited}"
        )
    if nonexistent:
        problems.append(
            f"{len(nonexistent)} ids cited in ACCEPTANCE.md do not exist in the "
            f"catalogue: {nonexistent}"
        )

    if problems:
        return False, "; ".join(problems)
    return True, (
        f"both comm directions of section 11.3 print nothing -- {len(cited)} cited ids, "
        f"all {len(all_scenarios)} catalogue ids accounted for"
    )


# ---------------------------------------------------------------------------------------
# Check 4 -- section 9.2 half one: nothing is unowned. The same two greps, verbatim in
# spirit, scenario side and criteria side.
# ---------------------------------------------------------------------------------------


def check_4_nothing_unowned() -> tuple[bool, str]:
    e2e_text = _read(E2E_PATH)
    acceptance_text = _read(ACCEPTANCE_PATH)
    implementation_text = _read(IMPLEMENTATION_PATH)
    catalogue = build_catalogue(e2e_text)

    mentioned_scenarios = set(SCENARIO_ID_RE.findall(implementation_text))
    unmentioned_scenarios = sorted(
        catalogue.ids - mentioned_scenarios, key=_scenario_sort_key
    )

    claimed_criteria = set(CRITERION_ID_RE.findall(implementation_text))
    all_criteria = set(CRITERION_ID_RE.findall(acceptance_text))
    unclaimed_criteria = sorted(
        all_criteria - claimed_criteria, key=_criterion_sort_key
    )

    problems = []
    if unmentioned_scenarios:
        problems.append(
            f"{len(unmentioned_scenarios)} scenarios IMPLEMENTATION.md never mentions: "
            f"{unmentioned_scenarios}"
        )
    if unclaimed_criteria:
        problems.append(
            f"{len(unclaimed_criteria)} criteria IMPLEMENTATION.md never mentions: "
            f"{unclaimed_criteria}"
        )

    if problems:
        return False, "; ".join(problems)
    return True, (
        f"both comm invocations print nothing -- {len(catalogue.ids)} scenarios and "
        f"{len(all_criteria)} criteria are all mentioned somewhere in IMPLEMENTATION.md"
    )


# ---------------------------------------------------------------------------------------
# Check 5 -- section 9.2 half two: nothing is owned twice, and every scenario and every
# criterion has exactly one owning row in section 9.1's table. The fourth column ("also
# on the hook for") is excluded, as section 9.2 specifies -- it is a briefing aid, not
# an ownership claim.
# ---------------------------------------------------------------------------------------


def parse_ownership_table(
    implementation_text: str,
) -> list[tuple[str, list[str], list[str]]]:
    parsed = []
    for cells in extract_table_rows(implementation_text, OWNERSHIP_TABLE_HEADER):
        if len(cells) != 4:
            continue
        wp = cells[0].strip("* ")
        scenarios = SCENARIO_ID_RE.findall(cells[1])
        criteria = CRITERION_ID_RE.findall(cells[2])
        parsed.append((wp, scenarios, criteria))
    return parsed


def check_5_ownership_unique_and_complete() -> tuple[bool, str]:
    e2e_text = _read(E2E_PATH)
    acceptance_text = _read(ACCEPTANCE_PATH)
    implementation_text = _read(IMPLEMENTATION_PATH)
    catalogue = build_catalogue(e2e_text)
    all_criteria = set(CRITERION_ID_RE.findall(acceptance_text))
    rows = parse_ownership_table(implementation_text)

    if not rows:
        return False, "section 9.1's ownership table was not found, or has zero rows"

    scenario_owner: dict[str, str] = {}
    criterion_owner: dict[str, str] = {}
    scenario_dupes: list[str] = []
    criterion_dupes: list[str] = []

    for wp, scenarios, criteria in rows:
        for sid in scenarios:
            if sid in scenario_owner:
                scenario_dupes.append(f"{sid} ({scenario_owner[sid]} and {wp})")
            else:
                scenario_owner[sid] = wp
        for cid in criteria:
            if cid in criterion_owner:
                criterion_dupes.append(f"{cid} ({criterion_owner[cid]} and {wp})")
            else:
                criterion_owner[cid] = wp

    owned_scenarios = set(scenario_owner)
    owned_criteria = set(criterion_owner)

    unowned_scenarios = sorted(catalogue.ids - owned_scenarios, key=_scenario_sort_key)
    phantom_scenarios = sorted(owned_scenarios - catalogue.ids, key=_scenario_sort_key)
    unowned_criteria = sorted(all_criteria - owned_criteria, key=_criterion_sort_key)
    phantom_criteria = sorted(owned_criteria - all_criteria, key=_criterion_sort_key)

    problems = []
    if scenario_dupes:
        problems.append(f"scenarios owned by more than one WP row: {scenario_dupes}")
    if unowned_scenarios:
        problems.append(
            f"{len(unowned_scenarios)} scenarios owned by no WP row: {unowned_scenarios}"
        )
    if phantom_scenarios:
        problems.append(
            f"{len(phantom_scenarios)} owned scenario ids do not exist in the "
            f"catalogue: {phantom_scenarios}"
        )
    if criterion_dupes:
        problems.append(f"criteria owned by more than one WP row: {criterion_dupes}")
    if unowned_criteria:
        problems.append(
            f"{len(unowned_criteria)} criteria owned by no WP row: {unowned_criteria}"
        )
    if phantom_criteria:
        problems.append(
            f"{len(phantom_criteria)} owned criteria do not exist in ACCEPTANCE.md: "
            f"{phantom_criteria}"
        )

    if problems:
        return False, "; ".join(problems)
    return True, (
        f"{len(owned_scenarios)} scenarios and {len(owned_criteria)} criteria each "
        f"owned exactly once, across {len(rows)} WP rows in section 9.1"
    )


# ---------------------------------------------------------------------------------------
# Check 6 -- for every id the two documents share, they mean the same scenario. Two
# layers, because they catch different failures:
#
#   (a) STRUCTURAL -- same suite, and ACCEPTANCE.md's description is not empty. Generic,
#       extraction-based, survives the catalogue growing past 134: the shape of the WP-02
#       card's own example (S-127 called a concurrency test in one document and a
#       fault-injection test in the other -- in fact the historical S-126/S-130 mix-up
#       IMPLEMENTATION.md section 0.2 item 11 records, already renumbered away by the
#       time this check was written).
#
#   (b) PINNED FACTS -- a fixed, hand-verified list of specific claims that no extraction
#       can compare, because comparing free text for meaning is not a thing a regex does
#       without becoming a second document-understanding project. There is no general
#       fix for that; the honest one is to do the semantic read once, by hand, and pin
#       what it found so the same drift cannot happen silently a second time. The four
#       entries below are exactly the contradictions the 2026-08-08 reconciliation pass
#       found between ACCEPTANCE.md and the E2E.md text it was describing -- not the
#       suite-and-id mix-ups of (a), which were already clean, but ACCEPTANCE.md
#       carrying a *number* or a *source scenario* that E2E.md's own text had since moved
#       past. Each pins two facts: something E2E.md must still say (the current truth)
#       and something ACCEPTANCE.md must no longer say (the stale claim). A hit on either
#       side is named, because "one of these four disagrees" is not an actionable
#       message, and the pin is deliberately narrow so it fails loudly and specifically
#       rather than papering over the next unrelated edit.
# ---------------------------------------------------------------------------------------


def parse_acceptance_scenario_table(
    acceptance_text: str,
) -> list[tuple[str, str, str]]:
    parsed = []
    for cells in extract_table_rows(acceptance_text, ACCEPTANCE_SCENARIO_TABLE_HEADER):
        if len(cells) != 5:
            continue
        ids = SCENARIO_ID_RE.findall(cells[0])
        if not ids:
            continue
        parsed.append((ids[0], cells[1].strip(), cells[2].strip()))
    return parsed


# (id, human-readable fact, current-truth pattern required in E2E.md,
#  stale-claim pattern forbidden in ACCEPTANCE.md)
PinnedFact = tuple[str, str, re.Pattern, re.Pattern]

PINNED_FACTS: list[PinnedFact] = [
    (
        "S-35/S-128",
        "S-35's body positive-control is 60 KB under E2E section 4's 64 KB cap, not 100 KB",
        re.compile(r'"x"\*60000.{0,40}201'),
        # Excludes section 12 item 1's own historical "...ninth row pinned a 100 KB
        # body..." -- that sentence is the correction's own record of the number this
        # WP found and fixed, deliberately kept and phrased in the past tense. A live
        # claim never reads "pinned a 100 KB body"; every buggy instance this pass found
        # read "carries a 100 KB body" or "100 KB body still/stays returns/returns 201".
        re.compile(r"(?<!pinned a )100\s*KB body"),
    ),
    (
        "S-35",
        "S-35 is nine requests (eight 422s, one 201), not eight",
        re.compile(r"Steps:\s*nine requests"),
        re.compile(r"eight-request table of S-35|S-35'?s? eighth row|`?422\s*x7`?"),
    ),
    (
        "S-130",
        "S-130 replays S-128's bound-violation table over MCP, not S-35's validation table",
        re.compile(r"the S-128 table, re-issued as tool calls"),
        re.compile(r"S-35 (?:validation )?table|the eight cases of the S-35 table"),
    ),
    (
        "S-129/D6",
        "the search floor (D6) is 3 characters, not 2 -- a trigram index cannot serve "
        "fewer",
        re.compile(r"\*\*3-character floor\*\*"),
        re.compile(r"shorter than 2\b|\b2[–-]200 chars of `?q`?"),
    ),
]


def _pinned_fact_problems(e2e_text: str, acceptance_text: str) -> list[str]:
    problems = []
    for sid, fact, e2e_pattern, stale_pattern in PINNED_FACTS:
        if not e2e_pattern.search(e2e_text):
            problems.append(
                f"{sid}: pinned fact no longer found in E2E.md ({fact}) -- either the "
                f"scenario text moved and the pin needs updating, or the fact regressed"
            )
        hit = stale_pattern.search(acceptance_text)
        if hit:
            problems.append(
                f"{sid}: ACCEPTANCE.md still carries the stale claim {hit.group(0)!r} "
                f"({fact})"
            )
    return problems


def check_6_shared_ids_agree() -> tuple[bool, str]:
    e2e_text = _read(E2E_PATH)
    acceptance_text = _read(ACCEPTANCE_PATH)
    catalogue = build_catalogue(e2e_text)
    rows = parse_acceptance_scenario_table(acceptance_text)

    if not rows:
        return False, "ACCEPTANCE.md section 9's scenario table was not found, or has zero rows"

    problems = []
    checked = 0
    for sid, claimed_suite, intent in rows:
        actual_suite = catalogue.ids_to_suite.get(sid)
        if actual_suite is None:
            problems.append(
                f"{sid}: ACCEPTANCE.md section 9 describes it, E2E.md has no such "
                f"scenario"
            )
            continue
        checked += 1
        if actual_suite != claimed_suite:
            problems.append(
                f"{sid}: ACCEPTANCE.md section 9 calls it suite '{claimed_suite}', "
                f"E2E.md places it in suite '{actual_suite}'"
            )
        if not intent:
            problems.append(f"{sid}: ACCEPTANCE.md section 9's intent column is empty")

    problems.extend(_pinned_fact_problems(e2e_text, acceptance_text))

    if problems:
        return False, "; ".join(problems)
    return True, (
        f"{checked} scenario ids appear in both documents and agree on suite "
        f"(structural agreement, presence and suite placement); {len(PINNED_FACTS)} "
        f"hand-verified pinned facts from the 2026-08-08 reconciliation still hold "
        f"(semantic agreement, narrow and explicit rather than general free-text "
        f"comparison)"
    )


# ---------------------------------------------------------------------------------------
# Runner.
# ---------------------------------------------------------------------------------------

CHECKS: list[tuple[str, Callable[[], tuple[bool, str]]]] = [
    ("check_1_extraction_matches_suite_table", check_1_extraction_matches_suite_table),
    ("check_2_per_suite_counts_match", check_2_per_suite_counts_match),
    ("check_3_acceptance_citations_exist", check_3_acceptance_citations_exist),
    ("check_4_nothing_unowned", check_4_nothing_unowned),
    ("check_5_ownership_unique_and_complete", check_5_ownership_unique_and_complete),
    ("check_6_shared_ids_agree", check_6_shared_ids_agree),
]


def run_all() -> list[tuple[str, bool, str]]:
    """One (name, ok, message) triple per check, in card order. Callers that only want
    the six (ok, message) pairs the card specifies can drop the name; it is carried here
    because whatever wraps this list into individual assertions needs something to label
    each one with.
    """
    return [(name, *fn()) for name, fn in CHECKS]


def main() -> int:
    all_ok = True
    for name, ok, message in run_all():
        print(f"{'PASS' if ok else 'FAIL'} {name}: {message}")
        all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
