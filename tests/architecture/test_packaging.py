from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict[str, object]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_runtime_dependencies_are_pinned_and_allowlisted() -> None:
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    dependencies = project["dependencies"]
    assert dependencies == ["fastapi>=0.115", "pyyaml>=6.0"]
    assert project["scripts"] == {"justkernel": "justkernel.bootstrap.cli:main"}


def test_sdist_whitelist_excludes_local_agent_and_index_state() -> None:
    build = _pyproject()["tool"]
    assert isinstance(build, dict)
    sdist = build["hatch"]["build"]["targets"]["sdist"]  # type: ignore[index]
    assert isinstance(sdist, dict)
    include = sdist["include"]
    exclude = sdist["exclude"]
    assert "src/justkernel" in include
    assert "tests" in include
    assert ".codegraph" in exclude
    assert "AGENTS.md" in exclude
    assert "3q" in exclude
    assert "opencode.jsonc" in exclude


def test_distribution_checker_is_available() -> None:
    checker = (ROOT / "scripts" / "check_dist.py").read_text(encoding="utf-8")
    assert "check_wheel" in checker
    assert "check_sdist" in checker
