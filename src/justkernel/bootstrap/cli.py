"""Command-line entry point scaffold for JustKernel v2."""

from __future__ import annotations

import sys
from collections.abc import Sequence

VERSION = "0.1.0"


# ---- main -------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    """Print the scaffold version or a placeholder message."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--version"]:
        print(f"justkernel {VERSION}")
    else:
        print("justkernel: P0 scaffold")
    return 0
