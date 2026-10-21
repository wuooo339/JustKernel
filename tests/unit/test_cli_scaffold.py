from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from justkernel.bootstrap.cli import main


# ---- CLI scaffold -----------------------------------------------------------
def test_cli_reports_version(capsys) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out == "justkernel 0.1.0\n"


def test_cli_default_message(capsys) -> None:
    assert main([]) == 0
    assert capsys.readouterr().out == "justkernel: P0 scaffold\n"


def test_cli_reads_process_arguments(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["justkernel", "--version"])

    assert main() == 0
    assert capsys.readouterr().out == "justkernel 0.1.0\n"


def test_entry_point_uses_justkernel_cli() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )
    scripts = pyproject["project"]["scripts"]

    assert scripts["justkernel"] == "justkernel.bootstrap.cli:main"
    assert "justkernel-next" not in scripts
