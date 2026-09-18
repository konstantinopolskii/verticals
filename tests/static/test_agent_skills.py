"""Portable Verticals skill-pack regression checks."""

from __future__ import annotations

import json
import os
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents" / "skills"
CLAUDE_SKILLS = ROOT / ".claude" / "skills"
DESIGN_SYSTEM_ARCHIVE = ROOT / "web" / "vendor" / "konstantinopolskii-design-system-2.1.1.tgz"
EVIDENCE_DOC = ROOT / "docs" / "EVIDENCE.md"

EXPECTED = {"verticals-planning", "verticals-operator", "verticals-morning-report"}
PRIVATE_RUNTIME_TERMS = {
    "/Users/",
    "DailyRecap",
    "Stillframe",
    "Telegram",
    "claude-sonnet",
    "claude-opus",
    "gpt-",
}


def test_portable_skills_are_repository_owned_and_linked_for_claude() -> None:
    assert {path.name for path in SKILLS.iterdir() if path.is_dir()} == EXPECTED

    for name in EXPECTED:
        skill = SKILLS / name / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert f"name: {name}\n" in text

        portable_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((SKILLS / name).rglob("*"))
            if path.is_file()
        )
        assert all(term not in portable_text for term in PRIVATE_RUNTIME_TERMS)

        link = CLAUDE_SKILLS / name
        assert link.is_symlink()
        assert os.readlink(link) == f"../../.agents/skills/{name}"
        assert (link / "SKILL.md").samefile(skill)


def test_morning_report_references_resolve() -> None:
    skill_dir = SKILLS / "verticals-morning-report"
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    for name in ("setup.md", "report-contract.md"):
        assert f"references/{name}" in text
        assert (skill_dir / "references" / name).is_file()


def test_vendored_design_system_cannot_reinstall_legacy_skills() -> None:
    with tarfile.open(DESIGN_SYSTEM_ARCHIVE, "r:gz") as archive:
        names = set(archive.getnames())

    forbidden_prefixes = (
        "package/skills/",
        "package/.claude-plugin/",
        "package/scripts/postinstall.js",
    )
    assert not any(name.startswith(forbidden_prefixes) for name in names)


def test_evidence_tool_payload_reference_has_a_documented_section() -> None:
    """The agent-visible MCP description links to docs/EVIDENCE.md §4."""
    source = (ROOT / "verticals" / "mcp" / "evidence.py").read_text(encoding="utf-8")
    assert "docs/EVIDENCE.md §4" in source
    assert EVIDENCE_DOC.is_file()
    document = EVIDENCE_DOC.read_text(encoding="utf-8")
    assert "## 4. Payload shape" in document

    from verticals.core.evidence import validate_payload

    example = document.split("```json\n", 1)[1].split("\n```", 1)[0]
    assert validate_payload(json.loads(example)) == json.loads(example)
