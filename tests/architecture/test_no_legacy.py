from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEGACY_NAME = "awork" + "er"


# ---- no legacy references ---------------------------------------------------
def test_source_and_tests_have_no_legacy_name() -> None:
    for path in (ROOT / "src").rglob("*"):
        if path.is_file() and path.suffix in {".py", ".js", ".md"}:
            assert LEGACY_NAME not in path.read_text(encoding="utf-8"), path
    for path in (ROOT / "tests").rglob("*"):
        if path.is_file() and path.suffix in {".py", ".js", ".md"}:
            assert LEGACY_NAME not in path.read_text(encoding="utf-8"), path
