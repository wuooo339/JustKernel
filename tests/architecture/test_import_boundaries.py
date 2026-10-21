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
PLATFORM_PACKAGES = (
    "persistence",
    "artifacts",
    "runtime",
    "bus",
    "tools",
    "hardware",
    "models",
    "http",
    "security",
)
FORBIDDEN_DOMAIN_IMPORTS = {
    "sqlite3",
    "subprocess",
    "http",
    "deepagents",
    "fastapi",
    "starlette",
    "uvicorn",
}
LEGACY_NAME = "awork" + "er"


# ---- _imported_modules ------------------------------------------------------
def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level >= 2:
                modules.add(f"__relative_level_{node.level}__")
            if node.module:
                modules.add(node.module)
    return modules


# ---- skeleton ---------------------------------------------------------------
def test_package_skeleton_exists() -> None:
    assert (PACKAGE / "__init__.py").is_file()
    for package in (*DOMAIN_PACKAGES, "bootstrap"):
        assert (PACKAGE / package / "__init__.py").is_file(), package
    for package in PLATFORM_PACKAGES:
        assert (PACKAGE / "platform" / package / "__init__.py").is_file(), package


# ---- boundaries -------------------------------------------------------------
def test_new_package_never_imports_legacy_name() -> None:
    for path in PACKAGE.rglob("*.py"):
        imports = _imported_modules(path)
        assert not any(
            name == LEGACY_NAME or name.startswith(f"{LEGACY_NAME}.") for name in imports
        ), path


def test_domain_packages_do_not_import_platform_or_io() -> None:
    for package in DOMAIN_PACKAGES:
        for path in (PACKAGE / package).rglob("*.py"):
            for name in _imported_modules(path):
                assert name not in FORBIDDEN_DOMAIN_IMPORTS, (path, name)
                assert not name.startswith("justkernel.platform"), (path, name)
                assert not name.startswith("__relative_level_"), (path, name)


def test_platform_packages_do_not_import_http_or_bootstrap() -> None:
    for path in (PACKAGE / "platform").rglob("*.py"):
        for name in _imported_modules(path):
            assert not name.startswith("justkernel.bootstrap"), (path, name)
