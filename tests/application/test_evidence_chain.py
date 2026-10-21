from __future__ import annotations

import json
from pathlib import Path

import pytest

from justkernel.agent.agent import AgentInstance
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import Role
from justkernel.application.agent_service import AgentService
from justkernel.application.best_report_service import BestSelectionService
from justkernel.application.candidate_service import CandidateService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.evidence_chain import EvidenceChainService, EvidenceGate
from justkernel.application.fakes import (
    FakeIds,
    InMemoryAgentRepository,
    InMemoryBestSelectionRepository,
    InMemoryCandidateRepository,
    InMemoryClusterRepository,
    InMemoryTaskRepository,
    InMemoryTestRecordRepository,
    InMemoryToolJobRepository,
)
from justkernel.application.testing_service import TestingService as Service
from justkernel.candidate.candidate import CandidateVersion
from justkernel.candidate.errors import BestSelectionError
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.platform.artifacts.store import ArtifactStore
from justkernel.platform.tools.cann_simulation import (
    CannEnvironment,
    CannExecution,
    CannSimulationBackend,
    FakeCannRunner,
)
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, DirectionId
from justkernel.shared.ids import TestRecordId as RecordId
from justkernel.task.state import TaskKind
from justkernel.task.task import Task
from justkernel.testing.record import ArtifactRef, Environment
from justkernel.testing.record import TestRecord as Record
from justkernel.testing.record_zip import RecordZipError
from justkernel.testing.state import TestCoverage as Coverage
from justkernel.testing.state import TestOutcome as Outcome
from justkernel.testing.state import TestRecordKind as RecordKind


# ---- helpers ----------------------------------------------------------------
def _operator_ref() -> OperatorRef:
    return OperatorRef(
        operator_id="op-1",
        version="1",
        digest=Digest.from_text("spec"),
        artifact_ref="artifact://spec",
    )


def _skill() -> SkillRef:
    return SkillRef(
        name="cann-simulation-test",
        version="1",
        source_path="/skills/tester-cann-simulation",
        digest=Digest.from_text("skill"),
    )


def _environment() -> CannEnvironment:
    return CannEnvironment(
        soc="Ascend910B4",
        cann_version="9.0.0",
        python_version="3.13.0",
        driver_version="25.0",
        simulator_version="1.0",
    )


def _stack(
    tmp_path: Path,
) -> tuple[
    EvidenceChainService,
    EvidenceGate,
    BestSelectionService,
    Service,
    CannSimulationBackend,
    InMemoryTestRecordRepository,
    ArtifactStore,
    Task,
    CandidateVersion,
    object,
    AgentInstance,
    AgentInstance,
]:
    clusters = InMemoryClusterRepository()
    agents = InMemoryAgentRepository()
    tasks = InMemoryTaskRepository()
    candidates = InMemoryCandidateRepository()
    records = InMemoryTestRecordRepository()
    jobs = InMemoryToolJobRepository()
    selections = InMemoryBestSelectionRepository()
    ids = FakeIds()
    cluster_service = ClusterService(clusters, ids)
    agent_service = AgentService(clusters, agents, tasks, ids)
    candidate_service = CandidateService(candidates, tasks, agents, ids)
    cluster = cluster_service.create_cluster(
        operator_id="op-1",
        supervisor_id=AgentId.generate(),
        operator_spec_ref=_operator_ref(),
        start_mode=StartMode.GENERATE,
        max_agents=6,
        created_at=0,
    )
    cluster_service.start_cluster(cluster.id)
    agent_service.create_agent(
        cluster_id=cluster.id,
        role=Role.SUPERVISOR,
        model_profile="model-1",
        skills=(),
        agent_id=cluster.supervisor_id,
    )
    mentor = agent_service.create_agent(
        cluster_id=cluster.id,
        role=Role.MENTOR,
        model_profile="model-1",
        skills=(),
    )
    tester = agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.TESTER,
        model_profile="model-1",
        skills=(),
    )
    candidate = candidate_service.import_candidate(
        cluster_id=cluster.id,
        direction_id=DirectionId.generate(),
        source_files={"kernel.cpp": "// candidate source"},
        diff_artifact="artifact://diff",
        import_id="import-1",
        created_at=0,
    )
    task = agent_service.assign_task(
        mentor_id=mentor.id,
        worker_id=tester.id,
        kind=TaskKind.TEST,
        direction_id=DirectionId.generate(),
        operator_spec_ref=_operator_ref(),
        context_ref="artifact://context",
        context_digest=Digest.from_text("context"),
        budget_ref="budget-1",
        objective="verify candidate",
        candidate_id=candidate.id,
        skill_ref=_skill(),
        created_at=0,
    )
    env = _environment()
    backend = CannSimulationBackend(env, FakeCannRunner(env))
    testing = Service(tasks, agents, records, jobs, backend, ids)
    store = ArtifactStore(tmp_path / "artifacts")
    chain = EvidenceChainService(testing, store)
    gate = EvidenceGate(store)
    best = BestSelectionService(
        clusters,
        candidates,
        records,
        selections,
        ids,
        evidence=gate,
    )
    return (
        chain,
        gate,
        best,
        testing,
        backend,
        records,
        store,
        task,
        candidate,
        cluster,
        mentor,
        tester,
    )


def _payloads(
    task: Task,
    candidate: CandidateVersion,
    execution: CannExecution,
) -> dict[str, str | bytes]:
    environment = dict(execution.environment.values(execution.device))
    source_name = "kernel.cpp"
    source_digest = candidate.source.digest.value
    return {
        "task.json": json.dumps({"task_id": task.id.value, "kind": task.kind.value}),
        "context.json": "{}",
        "operator-spec.json": "{}",
        "candidate/diff.patch": "diff --git a/kernel.cpp b/kernel.cpp",
        "candidate/source.sha256": f"{source_digest}  {source_name}\n",
        "candidate/source/kernel.cpp": "// candidate source",
        "skill/SKILL.md": "# tester\n",
        "skill/metadata.json": json.dumps({"name": "cann-simulation-test"}),
        "cases.json": json.dumps([case.case_id for case in execution.cases]),
        "config.json": json.dumps({"device": execution.device, "timeout_s": 30}),
        "environment.json": json.dumps(environment, sort_keys=True),
        "commands.log": "\n".join(execution.commands) + "\n",
        "stdout.log": execution.stdout,
        "stderr.log": execution.stderr,
        "results.json": json.dumps(
            {
                "executed": True,
                "outcome": execution.outcome.value,
                "cases": [
                    {"case_id": case.case_id, "passed": case.passed, "error": case.error}
                    for case in execution.cases
                ],
            },
            sort_keys=True,
        ),
        "metrics.json": json.dumps(
            {
                metric.name: {
                    "value": metric.value,
                    "unit": metric.unit,
                    "direction": metric.direction,
                }
                for metric in execution.metrics
            },
            sort_keys=True,
        ),
        "provenance.json": json.dumps({"task_id": task.id.value}, sort_keys=True),
    }


def _seal(
    chain: EvidenceChainService,
    task: Task,
    candidate: CandidateVersion,
    cluster: object,
    execution: CannExecution,
) -> Record:
    return chain.seal_archive(
        task_id=task.id,
        cluster_id=cluster.id.value,
        payloads=_payloads(task, candidate, execution),
        outcome=execution.outcome,
        coverage=execution.coverage,
        environment=Environment(values=execution.environment.values(execution.device)),
        backend="cann-simulation",
        created_at=100,
        extra_manifest={"environment_fingerprint": execution.environment_fingerprint().value},
    )


# ---- evidence chain ---------------------------------------------------------
def test_candidate_job_zip_record_best_chain(tmp_path: Path) -> None:
    chain, _, best, testing, backend, _, store, task, candidate, cluster, _, _ = _stack(tmp_path)
    job = testing.submit_test(
        task_id=task.id,
        case_selection=("case-1", "case-2"),
        timeout_s=30,
        device="sim:0",
    )
    testing.start_job(job.id, now_ms=0)
    execution = backend.execute(job.id)
    record = _seal(chain, task, candidate, cluster, execution)

    assert record.is_full_pass
    assert record.job_id == job.id
    assert record.artifact.digest == Digest.from_bytes(store.get_bytes(record.artifact.digest))
    assert store.verify(record.artifact.digest)
    assert testing.jobs.get(job.id).state.value == "SUCCEEDED"

    selection = best.nominate_best(
        cluster_id=cluster.id,
        candidate_id=candidate.id,
        policy_digest=Digest.from_text("policy"),
        nomination_record_ids=(record.id,),
        reason="validated evidence",
        created_at=200,
    )
    assert selection.candidate_id == candidate.id


def test_fabricated_pass_record_is_rejected(tmp_path: Path) -> None:
    _, _, best, _, _, records, _, task, candidate, cluster, _, _ = _stack(tmp_path)
    fake = Record(
        id=RecordId.generate(),
        candidate_id=candidate.id,
        kind=RecordKind.TEST,
        skill_ref=_skill(),
        backend="cann-simulation",
        outcome=Outcome.PASS,
        coverage=Coverage.FULL,
        executed=True,
        artifact=ArtifactRef(ref="artifact://fake", digest=Digest.from_text("fake zip")),
        environment=Environment(values=(("soc", "Ascend910B4"),)),
        created_at=0,
        task_id=task.id,
        job_id="fake-job",
    )
    records.append(fake)

    with pytest.raises(BestSelectionError):
        best.nominate_best(
            cluster_id=cluster.id,
            candidate_id=candidate.id,
            policy_digest=Digest.from_text("policy"),
            nomination_record_ids=(fake.id,),
            reason="fabricated",
            created_at=200,
        )


def test_invalid_archive_does_not_seal_or_store_record(tmp_path: Path) -> None:
    chain, _, _, testing, backend, _, store, task, candidate, cluster, _, _ = _stack(tmp_path)
    job = testing.submit_test(
        task_id=task.id,
        case_selection=("case-1",),
        timeout_s=30,
    )
    testing.start_job(job.id, now_ms=0)
    execution = backend.execute(job.id)
    payloads = _payloads(task, candidate, execution)
    del payloads["results.json"]

    with pytest.raises(RecordZipError):
        chain.seal_archive(
            task_id=task.id,
            cluster_id=cluster.id.value,
            payloads=payloads,
            outcome=execution.outcome,
            coverage=execution.coverage,
            environment=Environment(values=execution.environment.values(execution.device)),
            backend="cann-simulation",
            created_at=100,
        )
    assert testing.jobs.get(job.id).state.value == "RUNNING"
    assert store.root.exists() is False or list(store.root.rglob("*")) == []


def test_non_pass_execution_is_not_accepted_as_best(tmp_path: Path) -> None:
    chain, _, best, testing, backend, _, _, task, candidate, cluster, _, _ = _stack(tmp_path)
    job = testing.submit_test(
        task_id=task.id,
        case_selection=("fail-case",),
        timeout_s=30,
    )
    testing.start_job(job.id, now_ms=0)
    execution = backend.execute(job.id)
    record = _seal(chain, task, candidate, cluster, execution)

    assert record.outcome is Outcome.FAIL
    with pytest.raises(BestSelectionError):
        best.nominate_best(
            cluster_id=cluster.id,
            candidate_id=candidate.id,
            policy_digest=Digest.from_text("policy"),
            nomination_record_ids=(record.id,),
            reason="failed evidence",
            created_at=200,
        )
