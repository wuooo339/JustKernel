from __future__ import annotations

import pytest

from justkernel.application.cluster_service import ClusterService
from justkernel.application.fakes import FakeIds, InMemoryClusterRepository
from justkernel.cluster.cluster import Cluster
from justkernel.cluster.errors import ClusterError
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import ClusterPhase, ClusterState, StartMode
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, CandidateId, ClusterId


# ---- helpers ----------------------------------------------------------------
def _service() -> tuple[ClusterService, InMemoryClusterRepository]:
    repository = InMemoryClusterRepository()
    return ClusterService(repository, FakeIds()), repository


def _operator_ref() -> OperatorRef:
    return OperatorRef(
        operator_id="op-1",
        version="1",
        digest=Digest.from_text("spec"),
        artifact_ref="artifact://spec",
    )


def _create(service: ClusterService, **overrides: object) -> Cluster:
    values: dict[str, object] = {
        "operator_id": "op-1",
        "supervisor_id": AgentId.generate(),
        "operator_spec_ref": _operator_ref(),
        "start_mode": StartMode.GENERATE,
        "max_agents": 10,
        "created_at": 0,
    }
    values.update(overrides)
    return service.create_cluster(**values)


# ---- lifecycle --------------------------------------------------------------
def test_cluster_lifecycle() -> None:
    service, repository = _service()
    cluster = _create(service)

    assert cluster.state is ClusterState.INITIALIZING
    assert repository.version(cluster.id) == 0
    assert service.get(cluster.id) == cluster

    started = service.start_cluster(cluster.id)
    assert started.state is ClusterState.RUNNING
    assert repository.version(cluster.id) == 1

    paused = service.pause_cluster(cluster.id)
    assert paused.state is ClusterState.PAUSED
    assert repository.version(cluster.id) == 2

    resumed = service.resume_cluster(cluster.id)
    assert resumed.state is ClusterState.RUNNING
    assert repository.version(cluster.id) == 3

    baseline = CandidateId.generate()
    optimized = service.establish_baseline(cluster.id, baseline)
    assert optimized.phase is ClusterPhase.OPTIMIZING
    assert optimized.baseline_candidate_id == baseline

    converged = service.converge_cluster(cluster.id)
    assert converged.state is ClusterState.CONVERGING
    assert converged.phase is ClusterPhase.FINALIZING

    stopped = service.stop_cluster(cluster.id, "user stop", 100)
    assert stopped.state is ClusterState.STOPPED
    assert stopped.terminal_reason == "user stop"
    assert stopped.closed_at == 100


def test_set_max_agents() -> None:
    service, _ = _service()
    cluster = _create(service, max_agents=6)

    updated = service.set_max_agents(cluster.id, 10)
    assert updated.max_agents == 10

    with pytest.raises(ClusterError):
        service.set_max_agents(cluster.id, 5)


# ---- invalid transitions ----------------------------------------------------
def test_invalid_transitions_raise_domain_errors() -> None:
    service, _ = _service()
    cluster = _create(service)

    with pytest.raises(ClusterError):
        service.pause_cluster(cluster.id)
    with pytest.raises(ClusterError):
        service.converge_cluster(cluster.id)

    service.start_cluster(cluster.id)
    with pytest.raises(ClusterError):
        service.start_cluster(cluster.id)
    with pytest.raises(ClusterError):
        service.converge_cluster(cluster.id)

    service.stop_cluster(cluster.id, "done", 100)
    with pytest.raises(ClusterError):
        service.start_cluster(cluster.id)


def test_stop_requires_reason() -> None:
    service, _ = _service()
    cluster = _create(service)
    service.start_cluster(cluster.id)

    with pytest.raises(ClusterError):
        service.stop_cluster(cluster.id, "", 100)


def test_unknown_cluster_raises_key_error() -> None:
    service, _ = _service()

    with pytest.raises(KeyError):
        service.get(ClusterId.generate())
