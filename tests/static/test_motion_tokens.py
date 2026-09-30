"""S0.P1.043 (docs/design-handoff): new components take their curves from the look's tokens, so no file outside the
tokens and the files that predate them writes its own `cubic-bezier`."""

from __future__ import annotations

from tests.static.conftest import WEB_SRC_DIR

TOKENS = {"style.css", "lib/motion.ts", "lib/look.ts"}
PREDATE_THE_TOKENS = {
    "components/Column.vue",
    "components/GoalCard.vue",
    "components/GoalCardTools.vue",
    "components/InlineAdd.vue",
    "components/SubgoalAddRow.vue",
    "components/goalCard.css",
    "components/goalDetail.css",
    "lib/drag.ts",
    "lib/familyMotion.ts",
}


def test_new_files_take_curves_from_tokens() -> None:
    offenders = []
    for path in sorted(WEB_SRC_DIR.rglob("*")):
        if path.suffix not in {".vue", ".ts", ".css"}:
            continue
        rel = path.relative_to(WEB_SRC_DIR).as_posix()
        if rel.startswith("kit-ext/") or rel in TOKENS | PREDATE_THE_TOKENS:
            continue
        if "cubic-bezier" in path.read_text(encoding="utf-8"):
            offenders.append(rel)
    assert offenders == [], f"use var(--vt-ease-*) or lib/motion.ts curve() instead of cubic-bezier in {offenders}"
