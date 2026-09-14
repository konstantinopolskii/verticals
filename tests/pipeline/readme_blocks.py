"""One parser for `README.md`, shared by the three suite-E scenarios that read it (S-116, S-121,
S-122) and available to any later scenario that needs the same view.

The catalogue's whole mechanism for executable docs (`docs/E2E.md` S-121) is that the *test*
extracts commands from the README instead of holding its own copy — AC-162, "the README's config
block cannot drift from the tested one". A second copy of the extraction logic in each scenario
file would reintroduce exactly the drift the rule exists to prevent, one level up: two parsers
disagreeing about what "marked" means is the same defect as two copies of a command. So the
parser lives here, once, and every scenario reads the same `Fence` list.

Not a harness module (`tests/harness/` is cross-suite machinery: reporting, redaction, the
runner contract) — this is suite-E's own reading of one file in the repository root, and it sits
beside the scenarios that use it, the same way `tests/fixtures/census.py` sits beside the import
scenarios that read it.

Marking grammar, as `README.md` itself already writes it and `docs/E2E.md` S-121 defines it:

    ```bash e2e                          -> replayed verbatim by the suite
    ```bash e2e-skip: <one-line reason>   -> deliberately not replayed, reason required
    ```json / ```text / no language       -> not executable, not marked, ignored

`EXECUTABLE_LANGUAGES` is the closed list from S-121 ("every fence whose language is `bash`, `sh`
or `console`"). A fence in one of those languages carrying neither mark is the failure S-121
exists to catch — it is a command a reader will run that nothing has ever executed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README_PATH = REPO_ROOT / "README.md"

EXECUTABLE_LANGUAGES = frozenset({"bash", "sh", "console"})

_FENCE_RE = re.compile(r"^```(?P<info>.*)$")
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")


@dataclass(frozen=True)
class Fence:
    """One fenced block, with everything a scenario needs to judge it without re-reading the
    file: where it starts (1-based, for a failure message that a human can jump to), what its
    info string claimed, the body verbatim, and the nearest heading above it."""

    line_no: int
    info: str
    body: str
    section: str
    preceding_line: str

    @property
    def language(self) -> str:
        return self.info.split()[0].lower() if self.info.split() else ""

    @property
    def is_executable_language(self) -> bool:
        return self.language in EXECUTABLE_LANGUAGES

    @property
    def attributes(self) -> str:
        """Everything after the language word — `e2e`, or `e2e-skip: <reason>`, or nothing."""
        parts = self.info.split(maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""

    @property
    def is_marked_run(self) -> bool:
        return self.attributes == "e2e" or self.attributes.startswith("e2e ")

    @property
    def is_marked_skip(self) -> bool:
        return self.attributes.startswith("e2e-skip")

    @property
    def skip_reason(self) -> str:
        """The reason a skip mark carries. `README.md` writes it on the info string
        (```bash e2e-skip: <reason>```); `docs/E2E.md` S-121 describes it as sitting on the
        preceding line. Both are accepted here and the scenario asserts that *one of them* is
        non-empty — see the contradiction noted in `test_s121_readme.py`."""
        inline = self.attributes[len("e2e-skip"):].lstrip(": ").strip()
        if inline:
            return inline
        stripped = self.preceding_line.strip()
        return stripped if stripped else ""


def parse_fences(text: str) -> list[Fence]:
    """Every fenced block in document order. Deliberately a line scanner and not a markdown
    library: the six-dependency allowlist (`docs/DEPENDENCIES.md`) has no markdown parser in it,
    and the grammar this needs is three rules wide."""
    fences: list[Fence] = []
    lines = text.splitlines()
    section = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        heading = _HEADING_RE.match(line)
        if heading:
            section = heading.group("title")
            i += 1
            continue
        opening = _FENCE_RE.match(line)
        if not opening:
            i += 1
            continue
        info = opening.group("info").strip()
        body_lines: list[str] = []
        j = i + 1
        while j < len(lines) and not lines[j].startswith("```"):
            body_lines.append(lines[j])
            j += 1
        fences.append(
            Fence(
                line_no=i + 1,
                info=info,
                body="\n".join(body_lines),
                section=section,
                preceding_line=lines[i - 1] if i > 0 else "",
            )
        )
        i = j + 1
    return fences


def read_fences(path: Path = README_PATH) -> list[Fence]:
    return parse_fences(path.read_text(encoding="utf-8"))


def sections(text: str) -> dict[str, str]:
    """`{heading title: body text under it}` for every heading level, in document order. Used by
    the AC-165 five-questions check and by S-116/S-122, which each need to read one named
    section's prose to find out whether the procedure it documents exists at all."""
    out: dict[str, str] = {}
    current = ""
    buf: list[str] = []
    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            if current:
                out[current] = "\n".join(buf)
            current = heading.group("title")
            buf = []
        else:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf)
    return out
