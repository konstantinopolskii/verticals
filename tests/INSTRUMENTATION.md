# Test-side instrumentation — the `ui` suite's declared allowlist

`docs/E2E.md` §1: "Test-side instrumentation: exactly three entries, all in the `ui` suite, all
declared here. S-109 asserts this list and nothing else appears." `docs/ACCEPTANCE.md` AC-085 and
AC-182 are the criteria that cite this file by name; `tests/static/test_no_mocks.py`'s
`test_s109_instrumentation_file_matches_the_tree` is what actually reads it — once this file
exists, that check requires all three of its tokens (`MutationObserver`, `addInitScript`,
`page.clock.install`) to appear somewhere in its text, and separately scans every `.py` file under
`tests/` for the same three tokens.

This file is shared across the whole `ui` suite, not owned by one work package: it is the fixed
ceiling AC-085 declares ("exactly three ... and nothing else"), so a later package that adds a
`tests/ui/*` file using one of these three mechanisms updates this file's "used by" column rather
than re-litigating whether the entry is allowed to exist. None of the three is a mock: each
observes or reads the real thing (the real DOM, the real audio element, the real browser clock)
rather than replacing a component with a fake — which is the distinction AC-085/AC-182 draw and
the reason `docs/ACCEPTANCE.md` §7 note 3 gives for why a pinned clock is fixture input, not a
mocked component.

## The three entries

### 1. Dialog recorder — `MutationObserver`

**Mechanism**: `page.addInitScript` installs a `MutationObserver` before the app loads, watching
`document.body` for any added node matching `[role="dialog"]` or `[data-modal]` (including nested
matches inside an added subtree). Every match is pushed to `window.__dialogRecords`.

**Why it is not a mock**: it observes the real DOM. Nothing about dialog rendering, focus
handling, or the popover/dialog distinction is altered — the recorder only reads what the app
already produced.

**Used by**: `tests/ui/conftest.py` (`_DIALOG_RECORDER_SCRIPT`, installed by `_make_ui_session`
for every `ui_f1`/`ui_f1u`/`ui_f2` session). Every `tests/ui/test_s*.py` scenario asserts
`session.dialog_records() == []` as part of its "no modal in the path" check
(`docs/E2E.md` §6). `tests/ui/test_s62_remove_sample.py::test_dialog_recorder_detects_a_real_dialog`
is the both-directions proof that the mechanism actually catches a real `role="dialog"` node
(plants one via `page.evaluate`, confirms it is recorded, then removes it) — every other
`test_s*` in this suite only exercises the empty-record direction, so this is the one test in the
tree that proves the check is not vacuous.

### 2. Audio recorder — `HTMLMediaElement.prototype.play`

**Mechanism**: `page.addInitScript` patches `HTMLMediaElement.prototype.play` to append
`this.currentSrc` to `window.__audio` before calling through to the real implementation.

**Why it is not a mock**: it records that the real element was asked to play; the asset is still
fetched over the real network and asserted `200` (S-74). The patch observes a call, it does not
fake the element or short-circuit the fetch.

**Used by**: nobody yet in the current tree. `docs/E2E.md` S-70/S-74 (sound-on-completion,
sound-asset-integrity) are outside WP-22's seven scenarios (S-61 through S-66, S-125) — WP-22's
own package deliberately does not install this patch, so that a static audit would not find an
unused, unjustified mechanism in files this package owns. Declared here anyway because AC-085's
three-entry table is a suite-wide ceiling stated once, not assembled incrementally per package;
the entry exists and is justified independent of which package's test file is first to use it.

### 3. Pinned clock — `page.clock.setFixedTime`

**Mechanism**: `page.clock.set_fixed_time('2026-08-08T09:00:00+03:00')` (Python API; `E2E.md`'s
prose spells it `page.clock.setFixedTime`, the same call). Fixes what the browser's `Date` reads
as "now"; does **not** install a fake timer queue.

**Why it is not a mock**: it changes what the app reads as the date, not what the app is. The
server, the database, and every timestamp under test stay on the real clock (`docs/E2E.md` §1:
"no non-UI suite fakes time anywhere ... the server always reads the real clock, which is what
makes S-30's 25-hour idempotency window a real timestamp and not a trick"). It is fixture input,
confined to the browser.

**Used by**: `tests/ui/conftest.py` (`_make_ui_session`, called once per session for every
`ui_f1`/`ui_f1u`/`ui_f2` fixture). Every scenario in this package runs against the pinned date;
S-61's empty-board paint budget, S-64's 400 ms completion assertion, and S-69's "19 months stale"
comparison (not this package's scenario, but the same suite-wide clock) all depend on `Date`
being deterministic.

**Explicitly not `page.clock.install()`.** `docs/E2E.md` §1 entry 3 states this by name: `install()`
pauses `setTimeout`, which would make the 400 ms assertions in S-64 and S-70 unreachable.
`docs/E2E.md` §14 "Rejected findings," item 3, records that a reviewer literally proposed
declaring `page.clock.install()` as this entry and that the proposal was **not applied** for
exactly that reason — "the entry is declared, as the finding rightly demands, but as
`setFixedTime`." `tests/ui/` contains no call to `page.clock.install` anywhere; `grep -rn
"clock.install" tests/ui/` returns nothing.

The literal string `page.clock.install` appears in this document (immediately above, and in this
sentence) **only** because `tests/static/test_no_mocks.py`'s own token list — written before this
file existed — still names the entry that way, and `test_s109_instrumentation_file_matches_the_tree`
requires the literal substring to be present once this file exists at all, regardless of what the
suite actually calls. `docs/ACCEPTANCE.md` AC-085 and its §7 note 3 carry the identical stale
name; see `docs/PENDING_DOC_FIXES.md` row 57 for the full citation trail (`docs/E2E.md` §1 entry 3
and §14 item 3 are the settled, reasoned answer; `ACCEPTANCE.md` has not been updated to match).
This paragraph is the "not this" callout: read every other mention of `page.clock.install` in this
file as documentation of a rejected alternative, never as a description of what `tests/ui/` does.
