from __future__ import annotations

import pytest

from justkernel.shared.errors import InvalidProjectPathError
from justkernel.shared.paths import ProjectPath


# ---- valid paths ------------------------------------------------------------
def test_accepts_relative_posix_paths() -> None:
    for value in ("a.cpp", "op_kernel/kernel.cpp", "a/b/c", "a-b_c.1", "算子/kernel.cpp"):
        path = ProjectPath(value)

        assert path.value == value
        assert str(path) == value


# ---- invalid paths ----------------------------------------------------------
def test_rejects_unsafe_paths() -> None:
    invalid = [
        "",
        "/absolute/path",
        "a/../b",
        "..",
        "a/..",
        "a\\b",
        "a\x00b",
        "a//b",
        "./a",
        "a/",
        "C:/a",
    ]

    for value in invalid:
        with pytest.raises(InvalidProjectPathError):
            ProjectPath(value)
