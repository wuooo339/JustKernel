from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEGACY_NAME = "awork" + "er"
LEGACY_ENV = "AWORK" + "ER_"
TEXT_SUFFIXES = {".py", ".js", ".md", ".toml", ".yml", ".yaml"}


# ---- helpers ----------------------------------------------------------------
def _text_files(*roots: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            if root.suffix in TEXT_SUFFIXES:
                files.append(root)
            continue
        files.extend(
            path for path in root.rglob("*") if path.is_file() and path.suffix in TEXT_SUFFIXES
        )
    return tuple(files)


# ---- no legacy references ---------------------------------------------------
def test_source_and_tests_have_no_legacy_name() -> None:
    for path in _text_files(ROOT / "src", ROOT / "tests"):
        text = path.read_text(encoding="utf-8")
        assert LEGACY_NAME not in text, path
        assert LEGACY_ENV not in text, path


def test_package_metadata_and_entrypoints_are_justkernel() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert LEGACY_NAME not in pyproject
    assert LEGACY_ENV not in pyproject
    assert "[project.scripts]" in pyproject
    assert 'justkernel = "justkernel.bootstrap.cli:main"' in pyproject


def test_runtime_config_has_no_legacy_environment_branch() -> None:
    config = (ROOT / "src" / "justkernel" / "platform" / "config.py").read_text(encoding="utf-8")
    cli = (ROOT / "src" / "justkernel" / "bootstrap" / "cli.py").read_text(encoding="utf-8")

    assert LEGACY_ENV not in config
    assert LEGACY_ENV not in cli
    assert "JUSTKERNEL_MODE" in config
    assert "JUSTKERNEL_MODE" not in cli  # CLI only applies mode, config reads env


def test_legacy_data_importer_does_not_import_legacy_modules() -> None:
    importer = (
        ROOT / "src" / "justkernel" / "platform" / "persistence" / "legacy_import.py"
    ).read_text(encoding="utf-8")

    assert f"import {LEGACY_NAME}" not in importer
    assert f"from {LEGACY_NAME}" not in importer
