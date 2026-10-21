from __future__ import annotations

import sys
from importlib.util import find_spec
from pathlib import Path

REFACTOR_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SRC = REFACTOR_ROOT.parent / "JustKernel" / "src"

if LEGACY_SRC.is_dir():
    sys.path.insert(0, str(LEGACY_SRC))

# The legacy contracts are relevant only while the sibling legacy tree is
# available. A clean checkout (CI) has no ../JustKernel, so pytest must not
# import these modules at all; otherwise collection fails on `import aworker`.
if find_spec("aworker") is None:
    collect_ignore_glob = ["test_*.py"]
