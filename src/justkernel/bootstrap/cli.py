"""Command-line entry point for JustKernel v2."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from justkernel import __version__


# ---- main -------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    """Report the package version or a minimal usage line."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--version"]:
        print(f"justkernel {__version__}")
        return 0
    print("usage: justkernel --version")
    return 0
