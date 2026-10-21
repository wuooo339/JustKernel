"""Candidate version DAG."""

from __future__ import annotations

from dataclasses import dataclass, field

from justkernel.candidate.candidate import CandidateVersion
from justkernel.candidate.errors import CandidateError
from justkernel.shared.ids import CandidateId


# ---- CandidateGraph ---------------------------------------------------------
@dataclass(slots=True)
class CandidateGraph:
    _items: dict[CandidateId, CandidateVersion] = field(default_factory=dict)

    def add(self, candidate: CandidateVersion) -> None:
        if candidate.id in self._items:
            raise CandidateError(f"candidate already exists: {candidate.id}")
        if candidate.parent_id is not None:
            parent = self._items.get(candidate.parent_id)
            if parent is None:
                raise CandidateError(f"parent candidate not found: {candidate.parent_id}")
            if parent.cluster_id != candidate.cluster_id:
                raise CandidateError("parent candidate belongs to another cluster")
        self._items[candidate.id] = candidate

    def get(self, candidate_id: CandidateId) -> CandidateVersion:
        candidate = self._items.get(candidate_id)
        if candidate is None:
            raise CandidateError(f"candidate not found: {candidate_id}")
        return candidate

    def children(self, candidate_id: CandidateId) -> tuple[CandidateVersion, ...]:
        return tuple(
            sorted(
                (item for item in self._items.values() if item.parent_id == candidate_id),
                key=lambda item: item.id.value,
            )
        )

    def ancestors(self, candidate_id: CandidateId) -> tuple[CandidateVersion, ...]:
        chain: list[CandidateVersion] = []
        seen: set[CandidateId] = set()
        current = self.get(candidate_id)
        while current.parent_id is not None:
            if current.parent_id in seen:
                raise CandidateError("candidate graph contains a cycle")
            seen.add(current.parent_id)
            current = self.get(current.parent_id)
            chain.insert(0, current)
        return tuple(chain)

    def __len__(self) -> int:
        return len(self._items)
