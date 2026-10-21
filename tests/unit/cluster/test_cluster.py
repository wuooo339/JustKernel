from __future__ import annotations

import pytest

from justkernel.cluster.cluster import Cluster
from justkernel.cluster.errors import ClusterError
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import ClusterPhase, ClusterState, StartMode
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, CandidateId, ClusterId


# ---- helpers ----------------------------------------------------------------
def _cluster(**overrides: object) -> Cluster:
    values: dict[str, object] = {
        "id": ClusterId.generate(),
        "operator_id": "ConfusionMulGrad",
        "supervisor_id": AgentId.generate(),
        "operator_spec_ref": OperatorRef(
            operator_id="ConfusionMulGrad",
            version="1",
            digest=Digest.from_text("spec"),
            artifact_ref="artifact://spec",
        ),
        "start_mode": StartMode.GENERATE,
        "created_at": 0,
    }
    values.update(overrides)
    return Cluster(**values)


# ---- lifecycle --------------------------------------------------------------
def test_cluster_lifecycle_to_completed() -> None:
    cluster = _cluster()
    candidate = CandidateId.generate()

    assert cluster.state is ClusterState.INITIALIZING
    assert cluster.phase is ClusterPhase.BOOTSTRAPPING
    assert cluster.closed_at is None

    cluster.start()
    assert cluster.state is ClusterState.RUNNING

    cluster.establish_baseline(candidate)
    assert cluster.phase is ClusterPhase.OPTIMIZING
    assert cluster.baseline_candidate_id == candidate

    cluster.converge()
    assert cluster.state is ClusterState.CONVERGING
    assert cluster.phase is ClusterPhase.FINALIZING

    cluster.set_best_candidate(candidate)
    cluster.attach_report("report-1")
    cluster.complete(1000)

    assert cluster.state is ClusterState.COMPLETED
    assert cluster.best_candidate_id == candidate
    assert cluster.report_id == "report-1"
    assert cluster.closed_at == 1000
    assert cluster.terminal_reason is None


def test_cluster_pause_and_resume() -> None:
    cluster = _cluster()
    cluster.start()

    cluster.pause()
    assert cluster.state is ClusterState.PAUSED

    cluster.resume()
    assert cluster.state is ClusterState.RUNNING


# ---- terminal states --------------------------------------------------------
def test_cluster_stop_and_fail_record_reason() -> None:
    stopped = _cluster()
    stopped.start()
    stopped.stop("user stop", 500)
    assert stopped.state is ClusterState.STOPPED
    assert stopped.terminal_reason == "user stop"
    assert stopped.closed_at == 500

    failed = _cluster()
    failed.fail("unrecoverable", 600)
    assert failed.state is ClusterState.FAILED
    assert failed.terminal_reason == "unrecoverable"
    assert failed.closed_at == 600


def test_terminal_cluster_rejects_further_transitions() -> None:
    cluster = _cluster()
    cluster.start()
    cluster.stop("done", 100)

    with pytest.raises(ClusterError):
        cluster.start()
    with pytest.raises(ClusterError):
        cluster.stop("again", 200)


# ---- invalid transitions ----------------------------------------------------
def test_invalid_cluster_transitions() -> None:
    cluster = _cluster()

    with pytest.raises(ClusterError):
        cluster.pause()
    with pytest.raises(ClusterError):
        cluster.converge()
    with pytest.raises(ClusterError):
        cluster.complete(100)

    cluster.start()
    with pytest.raises(ClusterError):
        cluster.start()
    with pytest.raises(ClusterError):
        cluster.complete(100)
    with pytest.raises(ClusterError):
        cluster.set_best_candidate(CandidateId.generate())

    cluster.establish_baseline(CandidateId.generate())
    with pytest.raises(ClusterError):
        cluster.establish_baseline(CandidateId.generate())


# ---- max agents -------------------------------------------------------------
def test_max_agents_minimum_and_setter() -> None:
    cluster = _cluster(max_agents=6)

    assert cluster.max_agents == 6
    cluster.set_max_agents(10)
    assert cluster.max_agents == 10

    with pytest.raises(ClusterError):
        cluster.set_max_agents(5)


# ---- completion requirements ------------------------------------------------
def test_complete_requires_best_and_report() -> None:
    cluster = _cluster()
    cluster.start()
    cluster.establish_baseline(CandidateId.generate())
    cluster.converge()

    cluster.attach_report("report-1")
    with pytest.raises(ClusterError):
        cluster.complete(100)

    cluster.set_best_candidate(CandidateId.generate())
    cluster.complete(200)
    assert cluster.state is ClusterState.COMPLETED
