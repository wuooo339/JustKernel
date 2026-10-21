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
FORBIDDEN_DOMAIN_IMPORTS = {
    "sqlite3",
    "subprocess",
    "http",
    "deepagents",
    "fastapi",
    "starlette",
    "uvicorn",
}


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


# ---- package boundary -------------------------------------------------------
def test_package_skeleton_exists() -> None:
    assert (PACKAGE / "__init__.py").is_file()


def test_new_package_never_imports_legacy_aworker() -> None:
    for path in PACKAGE.rglob("*.py"):
        imports = _imported_modules(path)
        assert not any(name == "aworker" or name.startswith("aworker.") for name in imports), path


def test_domain_packages_do_not_import_adapters_or_io() -> None:
    for package in DOMAIN_PACKAGES:
        for path in (PACKAGE / package).rglob("*.py"):
            for name in _imported_modules(path):
                assert name not in FORBIDDEN_DOMAIN_IMPORTS, (path, name)
                assert not name.startswith("justkernel.platform"), (path, name)
                assert not name.startswith("__relative_level_"), (path, name)


def test_import_scanner_flags_cross_package_relative_imports(tmp_path: Path) -> None:
    path = tmp_path / "module.py"
    path.write_text("from ..platform import http\n", encoding="utf-8")

    assert "__relative_level_2__" in _imported_modules(path)
