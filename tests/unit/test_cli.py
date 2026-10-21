from __future__ import annotations

import sys

from justkernel.bootstrap.cli import main


# ---- CLI --------------------------------------------------------------------
def test_cli_reports_version(capsys) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out == "justkernel 0.1.0\n"


def test_cli_without_arguments_prints_usage(capsys) -> None:
    assert main([]) == 0
    assert capsys.readouterr().out == "usage: justkernel --version\n"


def test_cli_reads_process_arguments(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["justkernel", "--version"])

    assert main() == 0
    assert capsys.readouterr().out == "justkernel 0.1.0\n"
