from __future__ import annotations

import justkernel


# ---- public package ---------------------------------------------------------
def test_package_does_not_reexport_legacy_stack() -> None:
    assert not hasattr(justkernel, "aworker")
