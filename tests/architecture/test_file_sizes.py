from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "justkernel"
DOMAIN_PACKAGES = (
    "shared",
    "cluster",
    "agent",
    "comm",
    "task",
    "candidate",
    "testing",
    "report",
)
DOMAIN_LIMIT = 300
BOOTSTRAP_LIMIT = 400
PLATFORM_LIMIT = 600
WEB_LIMIT = 400
FUNCTION_LIMIT = 40


# ---- _line_count ------------------------------------------------------------
def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


# ---- _function_lengths ------------------------------------------------------
def _function_lengths(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lengths: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = node.end_lineno or node.lineno
            lengths.append((node.name, end - node.lineno + 1))
    return lengths


# ---- budgets ----------------------------------------------------------------
def test_domain_files_are_small() -> None:
    for package in DOMAIN_PACKAGES:
        for path in (PACKAGE / package).rglob("*.py"):
            assert _line_count(path) <= DOMAIN_LIMIT, path


def test_bootstrap_and_platform_files_are_small() -> None:
    for package, limit in (("bootstrap", BOOTSTRAP_LIMIT), ("platform", PLATFORM_LIMIT)):
        for path in (PACKAGE / package).rglob("*.py"):
            assert _line_count(path) <= limit, path


def test_functions_are_small() -> None:
    for path in PACKAGE.rglob("*.py"):
        for name, length in _function_lengths(path):
            assert length <= FUNCTION_LIMIT, (path, name, length)


def test_web_modules_are_small() -> None:
    for path in (PACKAGE / "web").rglob("*.js"):
        assert _line_count(path) <= WEB_LIMIT, path
