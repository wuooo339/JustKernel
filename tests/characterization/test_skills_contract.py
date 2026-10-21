from __future__ import annotations

from pathlib import Path

REFACTOR_ROOT = Path(__file__).resolve().parents[2]
LEGACY_ROOT = REFACTOR_ROOT.parent / "JustKernel"
SKILLS_ROOT = LEGACY_ROOT / "src" / "aworker" / "lab" / "resources" / "skills"
EXPECTED = {
    "compliance-review",
    "evidence-distillation",
    "kernel-engineering",
}


# ---- _frontmatter -----------------------------------------------------------
def _frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---", path
    end = lines.index("---", 1)
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


# ---- legacy skill contracts -------------------------------------------------
def test_legacy_skills_have_stable_frontmatter() -> None:
    discovered = {path.parent.name for path in SKILLS_ROOT.glob("*/SKILL.md")}
    assert discovered == EXPECTED

    for name in EXPECTED:
        fields = _frontmatter(SKILLS_ROOT / name / "SKILL.md")
        assert fields["name"] == name
        assert fields["description"]
