from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from justkernel.candidate.candidate import CandidateVersion
from justkernel.candidate.errors import CandidateError
from justkernel.candidate.graph import CandidateGraph
from justkernel.candidate.source import SourceRevision
from justkernel.shared.ids import AgentId, CandidateId, ClusterId, DirectionId, TaskId
from justkernel.shared.paths import ProjectPath
from justkernel.shared.principal import Principal


# ---- helpers ----------------------------------------------------------------
def _source(files: dict[str, str] | None = None) -> SourceRevision:
    return SourceRevision.from_files(
        files
        or {
            "op_host/tiling.cpp": "// tiling",
            "op_kernel/kernel.cpp": "// kernel",
        }
    )


def _candidate(
    *,
    parent_id: CandidateId | None = None,
    cluster_id: ClusterId | None = None,
    imported: bool = False,
    **overrides: object,
) -> CandidateVersion:
    agent = AgentId.generate()
    values: dict[str, object] = {
        "id": CandidateId.generate(),
        "cluster_id": cluster_id or ClusterId.generate(),
        "direction_id": DirectionId.generate(),
        "parent_id": parent_id,
        "author_agent_id": agent,
        "author_principal": Principal.agent(agent),
        "task_id": TaskId.generate(),
        "import_id": None,
        "source": _source(),
        "diff_artifact": "artifact://diff",
        "created_at": 0,
    }
    if imported:
        values.update(
            author_agent_id=None,
            author_principal=Principal.system(),
            task_id=None,
            import_id="import-1",
        )
    values.update(overrides)
    return CandidateVersion(**values)


# ---- source revision --------------------------------------------------------
def test_source_digest_is_order_independent() -> None:
    first = SourceRevision.from_files({"b.cpp": "b", "a.cpp": "a"})
    second = SourceRevision.from_files({"a.cpp": "a", "b.cpp": "b"})

    assert first.digest == second.digest
    assert first.files == second.files


def test_source_rejects_empty_and_duplicate_paths() -> None:
    with pytest.raises(CandidateError):
        SourceRevision.from_files({})

    with pytest.raises(CandidateError):
        SourceRevision(
            files=(
                (ProjectPath("a.cpp"), "first"),
                (ProjectPath("a.cpp"), "second"),
            )
        )


# ---- candidate provenance ---------------------------------------------------
def test_task_and_import_candidates_are_valid() -> None:
    assert _candidate().task_id is not None
    assert _candidate(imported=True).import_id == "import-1"


def test_candidate_requires_exactly_one_provenance_source() -> None:
    with pytest.raises(CandidateError):
        _candidate(import_id="import-2")
    with pytest.raises(CandidateError):
        _candidate(task_id=None, author_agent_id=None, author_principal=Principal.system())
    with pytest.raises(CandidateError):
        _candidate(imported=True, author_agent_id=AgentId.generate())
    with pytest.raises(CandidateError):
        _candidate(imported=True, author_principal=Principal.human())


def test_candidate_is_frozen_and_parent_cannot_be_self() -> None:
    candidate = _candidate()

    with pytest.raises(FrozenInstanceError):
        candidate.diff_artifact = "other"

    candidate_id = CandidateId.generate()
    with pytest.raises(CandidateError):
        _candidate(id=candidate_id, parent_id=candidate_id)
    with pytest.raises(CandidateError):
        _candidate(diff_artifact="")


# ---- candidate graph --------------------------------------------------------
def test_graph_tracks_parent_children_and_ancestors() -> None:
    cluster = ClusterId.generate()
    root = _candidate(cluster_id=cluster)
    child = _candidate(cluster_id=cluster, parent_id=root.id)
    graph = CandidateGraph()

    graph.add(root)
    graph.add(child)

    assert len(graph) == 2
    assert graph.get(child.id) == child
    assert graph.children(root.id) == (child,)
    assert graph.ancestors(child.id) == (root,)


def test_graph_rejects_duplicate_missing_and_cross_cluster_parents() -> None:
    cluster = ClusterId.generate()
    root = _candidate(cluster_id=cluster)
    graph = CandidateGraph()

    graph.add(root)
    with pytest.raises(CandidateError):
        graph.add(root)

    other = CandidateGraph()
    missing_parent = _candidate(cluster_id=cluster, parent_id=CandidateId.generate())
    with pytest.raises(CandidateError):
        other.add(missing_parent)

    cross_cluster = _candidate(parent_id=root.id, cluster_id=ClusterId.generate())
    with pytest.raises(CandidateError):
        graph.add(cross_cluster)
