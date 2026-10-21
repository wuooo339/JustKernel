from __future__ import annotations

import os
from pathlib import Path

import pytest

from justkernel.agent import skill_loader
from justkernel.agent.skill_loader import SkillLoader, SkillLoadError
from justkernel.agent.state import Role


# ---- helpers ----------------------------------------------------------------
def _skill_text(
    name: str,
    *,
    role: str = "tester",
    backend: str = "cann-simulation",
    version: str = "1",
    allowed: tuple[str, ...] = ("read_candidate", "submit_test"),
    description: str = "test skill",
) -> str:
    if allowed:
        tools = "allowed_tools:\n" + "\n".join(f"  - {tool}" for tool in allowed)
    else:
        tools = "allowed_tools: []"
    return f"""---
name: {name}
description: {description}
metadata:
  role: {role}
  backend: {backend}
  version: "{version}"
{tools}
---
# Skill body
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    return tmp_path / "base", tmp_path / "builtin", tmp_path / "user"


def _loader(
    tmp_path: Path,
    *,
    allow_user_scripts: bool = False,
    registered_backends: frozenset[str] | None = None,
) -> SkillLoader:
    base, builtin, user = _tree(tmp_path)
    return SkillLoader(
        base,
        builtin,
        user,
        allow_user_scripts=allow_user_scripts,
        registered_backends=registered_backends,
    )


# ---- loading ----------------------------------------------------------------
def test_load_order_and_same_name_override(tmp_path: Path) -> None:
    base, builtin, user = _tree(tmp_path)
    _write(base / "tester" / "SKILL.md", _skill_text("tester-base"))
    _write(
        builtin / "tester-cann-simulation" / "SKILL.md",
        _skill_text("cann-simulation-test", version="1"),
    )
    _write(
        user / "tester" / "custom" / "SKILL.md",
        _skill_text("cann-simulation-test", version="2", description="override"),
    )

    skills = _loader(tmp_path).load(Role.TESTER)
    by_name = {skill.name: skill for skill in skills}

    assert list(by_name) == ["tester-base", "cann-simulation-test"]
    assert by_name["cann-simulation-test"].version == "2"
    assert by_name["cann-simulation-test"].description == "override"
    assert by_name["tester-base"].to_ref().name == "tester-base"


def test_profiler_base_and_builtin(tmp_path: Path) -> None:
    base, builtin, _ = _tree(tmp_path)
    _write(
        base / "profiler" / "SKILL.md",
        _skill_text("profiler-base", role="profiler", allowed=("read_candidate", "submit_profile")),
    )
    _write(
        builtin / "profiler-cann" / "SKILL.md",
        _skill_text(
            "cann-profiler",
            role="profiler",
            backend="cann-profiler",
            allowed=("read_candidate", "submit_profile"),
        ),
    )

    skills = _loader(tmp_path).load(Role.PROFILER)

    assert {skill.name for skill in skills} == {"profiler-base", "cann-profiler"}


# ---- validation -------------------------------------------------------------
def test_frontmatter_role_backend_and_tools_are_validated(tmp_path: Path) -> None:
    user = _tree(tmp_path)[2]
    cases = (
        _skill_text("missing-description", description=""),
        _skill_text("wrong-role", role="supervisor"),
        _skill_text("unknown-backend", backend="unknown"),
        _skill_text("forbidden-tool", allowed=("select_best",)),
    )
    for index, text in enumerate(cases):
        _write(user / "tester" / f"bad-{index}" / "SKILL.md", text)

    with pytest.raises(SkillLoadError):
        _loader(tmp_path).load(Role.TESTER)


def test_oversized_skill_is_rejected(tmp_path: Path, monkeypatch) -> None:
    user = _tree(tmp_path)[2]
    _write(user / "tester" / "large" / "SKILL.md", _skill_text("large"))
    monkeypatch.setattr(skill_loader, "MAX_SKILL_BYTES", 10)

    with pytest.raises(SkillLoadError):
        _loader(tmp_path).load(Role.TESTER)


@pytest.mark.skipif(os.name == "nt", reason="symlink permissions differ on Windows")
def test_symlink_path_escape_is_rejected(tmp_path: Path) -> None:
    user = _tree(tmp_path)[2]
    outside = tmp_path / "outside"
    _write(outside / "SKILL.md", _skill_text("escaped"))
    (user / "tester").mkdir(parents=True)
    (user / "tester" / "evil").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SkillLoadError):
        _loader(tmp_path).load(Role.TESTER)


# ---- scripts and secrets ----------------------------------------------------
def test_user_scripts_require_flag(tmp_path: Path) -> None:
    user = _tree(tmp_path)[2]
    _write(user / "tester" / "scripted" / "SKILL.md", _skill_text("scripted"))
    _write(user / "tester" / "scripted" / "scripts" / "run.sh", "echo test\n")

    with pytest.raises(SkillLoadError):
        _loader(tmp_path).load(Role.TESTER)

    skills = _loader(tmp_path, allow_user_scripts=True).load(Role.TESTER)
    assert skills[0].scripts == ("run.sh",)


def test_secret_files_are_rejected(tmp_path: Path) -> None:
    user = _tree(tmp_path)[2]
    _write(user / "tester" / "secret" / "SKILL.md", _skill_text("secret"))
    _write(user / "tester" / "secret" / ".env", "TOKEN=value\n")

    with pytest.raises(SkillLoadError):
        _loader(tmp_path).load(Role.TESTER)
