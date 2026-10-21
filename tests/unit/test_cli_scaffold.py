from __future__ import annotations

from justkernel.bootstrap.cli import main


# ---- CLI scaffold -----------------------------------------------------------
def test_cli_reports_version(capsys) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out == "justkernel 0.1.0\n"


def test_cli_default_message(capsys) -> None:
    assert main([]) == 0
    assert capsys.readouterr().out == "justkernel: P0 scaffold\n"


def test_cli_reads_process_arguments(monkeypatch, capsys) -> None:
    import sys

    monkeypatch.setattr(sys, "argv", ["justkernel", "--version"])

    assert main() == 0
    assert capsys.readouterr().out == "justkernel 0.1.0\n"
