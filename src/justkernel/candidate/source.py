"""Immutable source revisions with canonical digests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Self

from justkernel.candidate.errors import CandidateError
from justkernel.shared.digest import Digest
from justkernel.shared.json import digest_json
from justkernel.shared.paths import ProjectPath


# ---- SourceRevision ---------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SourceRevision:
    files: tuple[tuple[ProjectPath, str], ...]
    digest: Digest = field(init=False)

    def __post_init__(self) -> None:
        if not self.files:
            raise CandidateError("source revision must contain at least one file")
        normalized = sorted(
            ((path.value, content) for path, content in self.files),
            key=lambda item: item[0],
        )
        paths = [path for path, _ in normalized]
        if len(set(paths)) != len(paths):
            raise CandidateError("source revision paths must be unique")
        object.__setattr__(
            self,
            "files",
            tuple((ProjectPath(path), content) for path, content in normalized),
        )
        object.__setattr__(self, "digest", digest_json(normalized))

    @classmethod
    def from_files(cls, files: Mapping[str, str]) -> Self:
        return cls(tuple((ProjectPath(path), content) for path, content in files.items()))
