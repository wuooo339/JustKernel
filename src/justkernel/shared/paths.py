"""Safe relative POSIX project paths."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.shared.errors import InvalidProjectPathError


# ---- ProjectPath ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ProjectPath:
    """A relative POSIX path that cannot escape a project root."""

    value: str

    def __post_init__(self) -> None:
        value = self.value
        if not value:
            raise InvalidProjectPathError("project path must not be empty")
        if "\x00" in value or "\\" in value:
            raise InvalidProjectPathError(f"unsafe project path {value!r}")
        if value.startswith("/"):
            raise InvalidProjectPathError(f"project path must be relative: {value!r}")
        if len(value) >= 2 and value[0].isalpha() and value[1] == ":":
            raise InvalidProjectPathError(f"project path must not contain a drive: {value!r}")

        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise InvalidProjectPathError(f"project path must be canonical: {value!r}")

    def __str__(self) -> str:
        return self.value
