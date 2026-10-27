"""S0.P1.043 (docs/design-handoff): new components take their curves from the look's tokens, so no file outside the
tokens and the files that predate them writes its own `cubic-bezier`."""

from __future__ import annotations

from tests.static.conftest import WEB_SRC_DIR

TOKENS = {"design/tokens.css", "design/vars.css", "lib/motion.ts", "lib/look.ts"}
PREDATE_THE_TOKENS = {
    "components/Column.tsx",
    "components/GoalCard.tsx",
    "components/goalCard.css",
    "components/goalCardTools.css",
    "components/goalDetail.css",
    "components/inlineAdd.css",
    "components/subgoalAddRow.css",
    "lib/drag.ts",
    "lib/dragSettle.ts",  # the settle curve, split out of lib/drag.ts unchanged (S5.P1.038)
    "lib/familyMotion.ts",
}


def test_new_files_take_curves_from_tokens() -> None:
    offenders = []
    for path in sorted(WEB_SRC_DIR.rglob("*")):
        if path.suffix not in {".ts", ".tsx", ".css"}:
            continue
        rel = path.relative_to(WEB_SRC_DIR).as_posix()
        if rel.startswith("kit-ext/") or rel in TOKENS | PREDATE_THE_TOKENS:
            continue
        if "cubic-bezier" in path.read_text(encoding="utf-8"):
            offenders.append(rel)
    assert offenders == [], f"use var(--vt-ease-*) or lib/motion.ts curve() instead of cubic-bezier in {offenders}"
