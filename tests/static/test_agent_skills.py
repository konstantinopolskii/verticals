"""Portable Verticals skill-pack regression checks."""

from __future__ import annotations

import os
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents" / "skills"
CLAUDE_SKILLS = ROOT / ".claude" / "skills"
DESIGN_SYSTEM_ARCHIVE = ROOT / "web" / "vendor" / "konstantinopolskii-design-system-2.1.1.tgz"

EXPECTED = {"verticals-planning", "verticals-operator"}
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


def test_vendored_design_system_cannot_reinstall_legacy_skills() -> None:
    with tarfile.open(DESIGN_SYSTEM_ARCHIVE, "r:gz") as archive:
        names = set(archive.getnames())

    forbidden_prefixes = (
        "package/skills/",
        "package/.claude-plugin/",
        "package/scripts/postinstall.js",
    )
    assert not any(name.startswith(forbidden_prefixes) for name in names)
