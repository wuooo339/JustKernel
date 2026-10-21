from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


# ---- import smoke -----------------------------------------------------------
def test_importing_all_justkernel_modules_creates_no_files(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["HOME"] = str(tmp_path)
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg")
    script = """
import importlib
import pkgutil

import justkernel

for module in pkgutil.walk_packages(justkernel.__path__, justkernel.__name__ + "."):
    importlib.import_module(module.name)
"""
    before = {path for path in tmp_path.rglob("*")}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    after = {path for path in tmp_path.rglob("*")}
    assert after == before
