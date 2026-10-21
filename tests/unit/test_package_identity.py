from __future__ import annotations

import justkernel


# ---- package identity -------------------------------------------------------
def test_package_exposes_version() -> None:
    assert justkernel.__version__ == "0.1.0"
