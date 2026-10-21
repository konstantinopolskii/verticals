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

EXPECTED = {"verticals-planning", "verticals-operator", "verticals-morning-report", "verticals-pr"}
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
    for name in ("setup.md", "source-reconciliation.md", "report-contract.md", "second-check.md", "worked-example.md"):
        assert f"references/{name}" in text
        assert (skill_dir / "references" / name).is_file()


def test_the_ten_checks_are_the_same_in_the_skill_the_second_agents_prompt_and_the_fake_agent() -> None:
    """The second check's keys and names live once, in `verticals/core/morning_check_list.json`. The skill's table, the second
    agent's prompt and the fake agent of the UI tests must name the same ten, in the same order, or a check goes unasked."""
    import importlib.util

    listed = json.loads((ROOT / "verticals" / "core" / "morning_check_list.json").read_text(encoding="utf-8"))
    keys = [item["key"] for item in listed]
    assert len(keys) == 10 and len(set(keys)) == 10

    table = (SKILLS / "verticals-morning-report" / "references" / "second-check.md").read_text(encoding="utf-8")
    rows = [[cell.strip() for cell in line.split("|")] for line in table.splitlines() if line.startswith("| `")]
    assert [row[1].strip("`") for row in rows] == keys
    assert [row[2] for row in rows] == [item["label"] for item in listed]

    prompt = (ROOT / "desktop" / "chat" / "prompt-check.md").read_text(encoding="utf-8")
    example = next(line for line in prompt.splitlines() if line.strip().startswith('{"checks"'))
    assert set(json.loads(example)["checks"]) <= set(keys)
    assert "ten checks" in prompt

    fake_path = ROOT / "tests" / "ui" / "fake_agent" / "fake_morning.py"
    spec = importlib.util.spec_from_file_location("fake_morning", fake_path)
    assert spec is not None and spec.loader is not None
    fake = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fake)
    assert list(fake.KEYS) == keys


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


def test_the_skills_say_where_a_steps_date_puts_it() -> None:
    """A step's date decides where it shows (docs/design/checklist-steps.md). The owner, 21 Oct 2026: "it should be written
    in the agent's mc that vertical uses, so NOBODY will do same mistake again." The words the `create` and `schedule` tools
    carry stand in every skill that writes goals: the operator's (and its MCP reference, which the app's chat reads), the
    planning one and the morning report's."""
    from verticals.mcp.tool_schemas import STEP_DATES

    for path in (
        SKILLS / "verticals-operator" / "SKILL.md",
        SKILLS / "verticals-operator" / "references" / "mcp-operations.md",
        SKILLS / "verticals-planning" / "SKILL.md",
        SKILLS / "verticals-morning-report" / "SKILL.md",
    ):
        assert " ".join(STEP_DATES.split()) in " ".join(path.read_text(encoding="utf-8").split()), path
