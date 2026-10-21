from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from justkernel.agent.skills import SkillRef
from justkernel.agent.state import AgentState, Role
from justkernel.application.agent_service import AgentService
from justkernel.application.baseline_service import BaselineService
from justkernel.application.best_report_service import BestSelectionService, ReportService
from justkernel.application.bootstrap_service import BootstrapService
from justkernel.application.candidate_service import CandidateService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.convergence_service import (
    ConvergenceRequest,
    ConvergenceService,
)
from justkernel.application.fakes import (
    FakeIds,
    FakeToolBackend,
    InMemoryAgentRepository,
    InMemoryBestSelectionRepository,
    InMemoryCandidateRepository,
    InMemoryClusterRepository,
    InMemoryDirectionRepository,
    InMemoryReportRepository,
    InMemoryTaskRepository,
    InMemoryTestRecordRepository,
    InMemoryToolJobRepository,
)
from justkernel.application.feedback_handoff_service import FeedbackHandoffService
from justkernel.application.resume_service import ResumeService
from justkernel.application.start_cluster_service import (
    ClusterStartService,
    StartClusterRequest,
    StartedCluster,
)
from justkernel.application.testing_service import TestingService as Service
from justkernel.application.wake_scheduler import WakeScheduler
from justkernel.application.watchdog_service import (
    ClusterActivity,
    WatchdogAction,
    WatchdogService,
)
from justkernel.candidate.candidate import CandidateVersion
from justkernel.candidate.errors import BestSelectionError
from justkernel.cluster.operator_spec import (
    AccuracyPolicy,
    CasePackRef,
    EngineeringPolicy,
    OperatorSpec,
    OutputTolerance,
    ReferenceSpec,
    TargetSpec,
)
from justkernel.cluster.state import ClusterState, StartMode
from justkernel.comm.wake import WakePolicy
from justkernel.platform.hardware.ledger import HardwareLedger, apply_hardware_schema
from justkernel.platform.hardware.queue import HardwareQueue
from justkernel.platform.persistence.database import connect
from justkernel.platform.persistence.registry import (
    OperatorActiveError,
    OperatorRegistry,
    apply_registry_schema,
)
from justkernel.report.report import ReportDirection
from justkernel.shared.digest import Digest
from justkernel.shared.events import DomainEvent, EventType
from justkernel.shared.ids import AgentId, CandidateId, DirectionId, EventId, TaskId
from justkernel.shared.ids import TestRecordId as RecordId
from justkernel.shared.paths import ProjectPath
from justkernel.shared.principal import Principal
from justkernel.task.context import TaskBudget
from justkernel.task.state import TaskKind, TaskState
from justkernel.task.task import Task
from justkernel.testing.policy import BudgetPolicy, EvaluationPolicy
from justkernel.testing.record import ArtifactRef, Environment
from justkernel.testing.record import TestRecord as Record
from justkernel.testing.state import TestCoverage as Coverage
from justkernel.testing.state import TestOutcome as Outcome
from justkernel.testing.state import TestRecordKind as RecordKind


# ---- fixtures ---------------------------------------------------------------
def _digest(text: str) -> Digest:
    return Digest.from_text(text)


def _skill(name: str = "cann-simulation-test") -> SkillRef:
    return SkillRef(
        name=name,
        version="1",
        source_path=f"/skills/{name}",
        digest=_digest(name),
    )


def _environment() -> Environment:
    return Environment(values=(("soc", "Ascend910B4"), ("cann", "9.0.0")))


def _artifact(name: str = "record") -> ArtifactRef:
    return ArtifactRef(ref=f"artifact://{name}", digest=_digest(f"{name} zip"))


def _spec(operator_id: str = "op-1", performance: bool = False) -> OperatorSpec:
    reference = ReferenceSpec(
        kind="executable",
        description="reference",
        artifact_digest=_digest("reference"),
    )
    accuracy = AccuracyPolicy(
        outputs=(OutputTolerance(dtype="float32", atol=1e-5, rtol=1e-5),),
    )
    case_pack = CasePackRef(digest=_digest("cases"), case_count=10, seed=7)
    evaluation = EvaluationPolicy(
        case_pack_digest=case_pack.digest,
        reference_digest=reference.digest(),
        accuracy_policy_digest=accuracy.digest(),
        allowed_backends=("cann-simulation",),
        environment_fingerprint="env-1",
        timing_unit="ms",
        warmup=1,
        repeats=3,
        aggregation="median",
        performance_target_enabled=performance,
        profiler_required=performance,
    )
    return OperatorSpec(
        operator_id=operator_id,
        version="1",
        semantics="operator semantics",
        input_contract="float32 [N,C]",
        reference=reference,
        accuracy_policy=accuracy,
        case_pack=case_pack,
        target=TargetSpec(
            soc="Ascend910B4",
            language="cpp",
            abi="aclnn",
            cann_version="9.0.0",
            build_entry="build.sh",
            run_entry="run.sh",
        ),
        engineering_policy=EngineeringPolicy(
            editable_paths=(ProjectPath("op_kernel/kernel.cpp"),),
            read_only_paths=(ProjectPath("tests/cases.json"),),
            forbidden_actions=("modify oracle",),
        ),
        evaluation_policy=evaluation,
    )


def _loop(tmp_path: Path, *, performance: bool = False) -> SimpleNamespace:
    clusters = InMemoryClusterRepository()
    agents = InMemoryAgentRepository()
    tasks = InMemoryTaskRepository()
    candidates = InMemoryCandidateRepository()
    records = InMemoryTestRecordRepository()
    jobs = InMemoryToolJobRepository()
    directions = InMemoryDirectionRepository()
    selections = InMemoryBestSelectionRepository()
    reports = InMemoryReportRepository()
    ids = FakeIds()
    cluster_service = ClusterService(clusters, ids)
    agent_service = AgentService(clusters, agents, tasks, ids)
    candidate_service = CandidateService(candidates, tasks, agents, ids)
    testing = Service(tasks, agents, records, jobs, FakeToolBackend(), ids)
    best = BestSelectionService(
        clusters,
        candidates,
        records,
        selections,
        ids,
        profile_required=performance,
    )
    report_service = ReportService(clusters, candidates, records, reports)
    convergence = ConvergenceService(cluster_service, best, report_service)
    connection = connect(str(tmp_path / "registry.db"))
    apply_registry_schema(connection)
    registry = OperatorRegistry(connection)
    start = ClusterStartService(cluster_service, agent_service, registry)
    bootstrap = BootstrapService(directions, candidate_service)
    return SimpleNamespace(
        clusters=clusters,
        agents=agents,
        tasks=tasks,
        candidates=candidates,
        records=records,
        jobs=jobs,
        directions=directions,
        reports=reports,
        ids=ids,
        cluster_service=cluster_service,
        agent_service=agent_service,
        candidate_service=candidate_service,
        testing=testing,
        best=best,
        report_service=report_service,
        convergence=convergence,
        registry=registry,
        start=start,
        bootstrap=bootstrap,
        spec=_spec(performance=performance),
        performance=performance,
    )


def _request(loop: SimpleNamespace, mode: StartMode = StartMode.GENERATE) -> StartClusterRequest:
    return StartClusterRequest(
        operator_spec=loop.spec,
        operator_artifact_ref="artifact://spec",
        start_mode=mode,
        baseline_source_ref="artifact://baseline" if mode is StartMode.IMPORT else None,
        tester_skill=_skill(),
        profiler_skill=_skill("cann-profiler") if loop.performance else None,
        backend="cann-simulation",
        devices=("sim:0",),
        max_agents=6,
        initial_consultants=1,
        initial_mentors=1,
        model_profile="model-1",
        budget=BudgetPolicy(max_duration_s=60),
        reservation_key="reservation-1",
        journal_ref="journal/cluster-1",
        created_at=0,
    )


def _started(loop: SimpleNamespace) -> StartedCluster:
    return loop.start.start(_request(loop))


def _workers(loop: SimpleNamespace, started: StartedCluster) -> tuple[object, object]:
    mentor = started.mentors[0]
    optimizer = loop.agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.OPTIMIZER,
        model_profile="model-1",
        skills=(_skill("optimizer"),),
    )
    tester = loop.agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.TESTER,
        model_profile="model-1",
        skills=(_skill(),),
    )
    return optimizer, tester


def _assign(
    loop: SimpleNamespace,
    mentor: object,
    worker: object,
    kind: TaskKind,
    *,
    candidate_id: CandidateId | None = None,
) -> Task:
    return loop.agent_service.assign_task(
        mentor_id=mentor.id,
        worker_id=worker.id,
        kind=kind,
        direction_id=DirectionId.generate(),
        operator_spec_ref=loop.spec.to_ref("artifact://spec"),
        context_ref="artifact://context",
        context_digest=_digest("context"),
        budget_ref="budget-1",
        objective=kind.value,
        candidate_id=candidate_id,
        skill_ref=_skill() if kind in (TaskKind.TEST, TaskKind.PROFILE) else None,
        created_at=0,
    )


def _commit(
    loop: SimpleNamespace,
    task: Task,
    worker: object,
    source: str,
) -> CandidateVersion:
    return loop.candidate_service.commit_candidate(
        task_id=task.id,
        author_agent_id=worker.id,
        source_files={"kernel.cpp": source},
        diff_artifact="artifact://diff",
        created_at=0,
    )


def _record(
    candidate: CandidateVersion,
    task: Task,
    *,
    outcome: Outcome = Outcome.PASS,
    kind: RecordKind = RecordKind.TEST,
) -> Record:
    return Record(
        id=RecordId.generate(),
        candidate_id=candidate.id,
        kind=kind,
        skill_ref=_skill(),
        backend="cann-simulation",
        outcome=outcome,
        coverage=Coverage.FULL,
        executed=True,
        artifact=_artifact(f"{candidate.id.value}-{kind.value}"),
        environment=_environment(),
        created_at=0,
        task_id=task.id,
        job_id=f"job-{task.id.value}",
    )


def _test_candidate(
    loop: SimpleNamespace,
    mentor: object,
    tester: object,
    candidate: CandidateVersion,
    *,
    outcome: Outcome = Outcome.PASS,
) -> Record:
    task = _assign(loop, mentor, tester, TaskKind.TEST, candidate_id=candidate.id)
    job = loop.testing.submit_test(task_id=task.id, case_selection=("case-1",), timeout_s=30)
    loop.testing.start_job(job.id, now_ms=0)
    record = loop.testing.seal_record(
        task_id=task.id,
        outcome=outcome,
        coverage=Coverage.FULL,
        artifact=_artifact(f"record-{candidate.id.value}"),
        environment=_environment(),
        backend="cann-simulation",
        created_at=10,
        summary="test",
    )
    loop.agent_service.complete_task(
        mentor_id=mentor.id,
        task_id=task.id,
        result_ref=record.artifact.ref,
        now_ms=20,
    )
    return record


# ---- scenario 1: generate -> baseline -> optimize -> complete --------------
def test_generate_to_completed_closed_loop(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    started = _started(loop)
    direction = loop.bootstrap.generate(
        started=started,
        objective="build baseline",
        created_at=1,
    )
    mentor = started.mentors[0]
    optimizer, tester = _workers(loop, started)

    generate = _assign(loop, mentor, optimizer, TaskKind.GENERATE)
    first = _commit(loop, generate, optimizer, "// first")
    loop.agent_service.complete_task(
        mentor_id=mentor.id,
        task_id=generate.id,
        result_ref="artifact://generated",
        now_ms=2,
    )
    first_record = _test_candidate(loop, mentor, tester, first)

    baseline = BaselineService(
        loop.clusters,
        loop.candidates,
        loop.records,
        BudgetPolicy(max_duration_s=60, max_bootstrap_attempts=2),
    )
    baseline_result = baseline.attempt(
        cluster_id=started.cluster.id,
        candidate_id=first.id,
        record_ids=(first_record.id,),
        now_ms=3,
    )
    assert baseline_result.accepted is True

    optimize = _assign(loop, mentor, optimizer, TaskKind.OPTIMIZE, candidate_id=first.id)
    second = _commit(loop, optimize, optimizer, "// optimized")
    loop.agent_service.complete_task(
        mentor_id=mentor.id,
        task_id=optimize.id,
        result_ref="artifact://optimized",
        now_ms=4,
    )
    second_record = _test_candidate(loop, mentor, tester, second)

    selection = loop.best.nominate_best(
        cluster_id=started.cluster.id,
        candidate_id=second.id,
        policy_digest=_digest("policy"),
        nomination_record_ids=(second_record.id,),
        reason="best full pass",
        created_at=5,
    )
    result = loop.convergence.complete(
        ConvergenceRequest(
            cluster_id=started.cluster.id,
            selection_id=selection.id,
            final_task_ids=(second_record.task_id,),
            final_record_ids=(second_record.id,),
            report_id="report-1",
            revision=1,
            directions=(
                ReportDirection(
                    direction_id=direction.id,
                    objective="baseline",
                    outcome="optimized",
                ),
            ),
            candidate_ids=(first.id, second.id),
            record_ids=(first_record.id, second_record.id),
            failures=(),
            decision="completed",
            now_ms=30,
        )
    )

    assert second.parent_id == first.id
    assert result.cluster.state is ClusterState.COMPLETED
    assert result.cluster.best_candidate_id == second.id
    assert result.cluster.report_id == "report-1"
    assert loop.reports.get("report-1").best_candidate_id == second.id


# ---- scenario 2: failed candidate handoff ----------------------------------
def test_failed_candidate_handoff_repairs_with_new_optimizer(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    started = _started(loop)
    loop.bootstrap.generate(started=started, objective="repair", created_at=1)
    mentor = started.mentors[0]
    optimizer, tester = _workers(loop, started)

    generate = _assign(loop, mentor, optimizer, TaskKind.GENERATE)
    first = _commit(loop, generate, optimizer, "// broken")
    loop.agent_service.complete_task(
        mentor_id=mentor.id,
        task_id=generate.id,
        result_ref="artifact://generated",
        now_ms=2,
    )
    failed = _test_candidate(loop, mentor, tester, first, outcome=Outcome.FAIL)
    handoff = FeedbackHandoffService(
        loop.agent_service,
        loop.tasks,
        loop.candidates,
        loop.records,
    )
    handed = handoff.handoff(
        mentor_id=mentor.id,
        old_task_id=generate.id,
        failed_record_id=failed.id,
        base_candidate_id=first.id,
        budget=TaskBudget(max_duration_s=100),
        objective="repair failed candidate",
        acceptance=("full test passes",),
        now_ms=10,
    )
    assert handed.old_worker.state is AgentState.CLOSED
    assert handed.new_worker.state is AgentState.RUNNING
    assert handed.context.feedback[0].record_id == failed.id

    second = loop.candidate_service.commit_candidate(
        task_id=handed.task.id,
        author_agent_id=handed.new_worker.id,
        source_files={"kernel.cpp": "// fixed"},
        diff_artifact="artifact://diff",
        created_at=11,
    )
    loop.agent_service.complete_task(
        mentor_id=mentor.id,
        task_id=handed.task.id,
        result_ref="artifact://fixed",
        now_ms=12,
    )
    passed = _test_candidate(loop, mentor, tester, second)
    assert passed.outcome is Outcome.PASS
    assert second.parent_id == first.id


# ---- scenario 3/6: profile gate --------------------------------------------
def test_profile_gate_requires_comparable_profile(tmp_path: Path) -> None:
    loop = _loop(tmp_path, performance=True)
    started = _started(loop)
    candidate = loop.candidate_service.import_candidate(
        cluster_id=started.cluster.id,
        direction_id=DirectionId.generate(),
        source_files={"kernel.cpp": "// candidate"},
        diff_artifact="artifact://diff",
        import_id="import-1",
        created_at=0,
    )
    task = Task(
        id=TaskId.generate(),
        cluster_id=started.cluster.id,
        mentor_id=started.mentors[0].id,
        worker_id=AgentId.generate(),
        kind=TaskKind.TEST,
        direction_id=DirectionId.generate(),
        operator_spec_ref=loop.spec.to_ref("artifact://spec"),
        context_ref="artifact://context",
        context_digest=_digest("context"),
        budget_ref="budget-1",
        objective="test",
        candidate_id=candidate.id,
        skill_ref=_skill(),
        created_at=0,
    )
    test_record = _record(candidate, task)
    loop.records.append(test_record)

    with pytest.raises(BestSelectionError):
        loop.best.nominate_best(
            cluster_id=started.cluster.id,
            candidate_id=candidate.id,
            policy_digest=_digest("policy"),
            nomination_record_ids=(test_record.id,),
            reason="missing profile",
            created_at=0,
        )

    profile = _record(candidate, task, kind=RecordKind.PROFILE)
    loop.records.append(profile)
    selection = loop.best.nominate_best(
        cluster_id=started.cluster.id,
        candidate_id=candidate.id,
        policy_digest=_digest("policy"),
        nomination_record_ids=(test_record.id, profile.id),
        reason="test and profile pass",
        created_at=0,
    )
    assert selection.candidate_id == candidate.id


# ---- scenario 4/5: duplicate events and watchdog WAIT ----------------------
def test_duplicate_events_and_watchdog_wait(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    started = _started(loop)
    event = DomainEvent(
        id=EventId.generate(),
        cluster_id=started.cluster.id,
        type=EventType.TASK_ASSIGNED,
        event_version=1,
        aggregate_type="task",
        aggregate_id="task-1",
        aggregate_version=0,
        actor=Principal.system(),
        occurred_at=0,
    )
    scheduler = WakeScheduler(WakePolicy(wake_debounce_ms=100))
    agent = started.mentors[0].id

    assert scheduler.notify(agent, event, agent_version=0, now_ms=0) is True
    assert scheduler.notify(agent, event, agent_version=0, now_ms=1) is False
    assert scheduler.claim(agent, agent_version=0, now_ms=50) is None
    wake = scheduler.claim(agent, agent_version=0, now_ms=100)
    assert wake is not None
    scheduler.wait(agent, reason="result", deadline_ms=500, now_ms=100)
    scheduler.complete(agent, now_ms=101)

    watchdog = WatchdogService(loop.cluster_service, WakePolicy(max_stalled_wakes=1))
    assert (
        watchdog.check(
            started.cluster.id,
            activity=ClusterActivity(valid_waits=1),
            now_ms=100,
        ).action
        is WatchdogAction.NONE
    )
    assert (
        watchdog.check(
            started.cluster.id,
            activity=ClusterActivity(),
            now_ms=101,
        ).action
        is WatchdogAction.WOKE_SUPERVISOR
    )

    first = loop.candidate_service.import_candidate(
        cluster_id=started.cluster.id,
        direction_id=DirectionId.generate(),
        source_files={"kernel.cpp": "// duplicate"},
        diff_artifact="artifact://diff",
        import_id="import-a",
        created_at=0,
    )
    second = loop.candidate_service.import_candidate(
        cluster_id=started.cluster.id,
        direction_id=DirectionId.generate(),
        source_files={"kernel.cpp": "// duplicate"},
        diff_artifact="artifact://diff",
        import_id="import-b",
        created_at=0,
    )
    assert loop.candidate_service.find_duplicate(second.id) == first


# ---- scenario 7: pause/resume without replay ------------------------------
def test_paused_cluster_resume_does_not_replay_task(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    started = _started(loop)
    mentor = started.mentors[0]
    testing = loop.testing
    candidate = loop.candidate_service.import_candidate(
        cluster_id=started.cluster.id,
        direction_id=DirectionId.generate(),
        source_files={"kernel.cpp": "// interrupted"},
        diff_artifact="artifact://diff",
        import_id="import-1",
        created_at=0,
    )
    task = _assign(
        loop, mentor, _worker_for_test(loop, mentor), TaskKind.TEST, candidate_id=candidate.id
    )
    job = testing.submit_test(task_id=task.id, case_selection=("case-1",), timeout_s=30)
    testing.start_job(job.id, now_ms=0)
    loop.agent_service.interrupt_task(
        mentor_id=mentor.id,
        task_id=task.id,
        reason="control restart",
        now_ms=10,
    )
    testing.interrupt_job(job.id, reason="control restart", now_ms=10)
    loop.cluster_service.pause_cluster(started.cluster.id)
    resume = ResumeService(loop.clusters, loop.tasks, loop.jobs, loop.records, loop.ids)

    resumed = resume.resume(started.cluster.id, now_ms=20)

    assert resumed.state is ClusterState.RUNNING
    assert loop.tasks.get(task.id).state is TaskState.INTERRUPTED
    assert loop.jobs.get(job.id).state.value == "INTERRUPTED"
    assert loop.records.get_by_task(task.id) is None


def _worker_for_test(loop: SimpleNamespace, mentor: object) -> object:
    return loop.agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.TESTER,
        model_profile="model-1",
        skills=(_skill(),),
    )


# ---- scenario 8: registry and device exclusivity ---------------------------
def test_duplicate_operator_is_rejected(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    _started(loop)

    with pytest.raises(OperatorActiveError):
        _started(loop)


def test_device_lease_is_exclusive(tmp_path: Path) -> None:
    connection = connect(str(tmp_path / "hardware.db"))
    apply_hardware_schema(connection)
    queue = HardwareQueue(HardwareLedger(connection))
    first = queue.enqueue(
        cluster_id="cluster-a",
        task_id="task-a",
        job_id="job-a",
        device_id="npu:0",
        purpose="test",
        priority=1,
        dedupe_key="a",
        now_ms=0,
    )
    second = queue.enqueue(
        cluster_id="cluster-b",
        task_id="task-b",
        job_id="job-b",
        device_id="npu:0",
        purpose="test",
        priority=2,
        dedupe_key="b",
        now_ms=0,
    )
    assert first == 1
    assert second == 2
    lease = queue.claim_next(lease_id="lease-a", device_id="npu:0", ttl_ms=100, now_ms=0)
    assert lease is not None
    assert queue.claim_next(lease_id="lease-b", device_id="npu:0", ttl_ms=100, now_ms=1) is None
    queue.release(lease.lease_id, lease.fencing_token, 2)
    assert queue.claim_next(lease_id="lease-b", device_id="npu:0", ttl_ms=100, now_ms=3) is not None


# ---- scenario 9: bootstrap budget failure ----------------------------------
def test_bootstrap_budget_failure_report_has_no_best(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    started = _started(loop)
    candidate = loop.candidate_service.import_candidate(
        cluster_id=started.cluster.id,
        direction_id=DirectionId.generate(),
        source_files={"kernel.cpp": "// failing"},
        diff_artifact="artifact://diff",
        import_id="import-1",
        created_at=0,
    )
    task = Task(
        id=TaskId.generate(),
        cluster_id=started.cluster.id,
        mentor_id=started.mentors[0].id,
        worker_id=AgentId.generate(),
        kind=TaskKind.TEST,
        direction_id=DirectionId.generate(),
        operator_spec_ref=loop.spec.to_ref("artifact://spec"),
        context_ref="artifact://context",
        context_digest=_digest("context"),
        budget_ref="budget-1",
        objective="fail",
        candidate_id=candidate.id,
        skill_ref=_skill(),
        created_at=0,
    )
    failed = _record(candidate, task, outcome=Outcome.FAIL)
    loop.records.append(failed)
    baseline = BaselineService(
        loop.clusters,
        loop.candidates,
        loop.records,
        BudgetPolicy(max_duration_s=60, max_bootstrap_attempts=1),
    )
    result = baseline.attempt(
        cluster_id=started.cluster.id,
        candidate_id=candidate.id,
        record_ids=(failed.id,),
        now_ms=1,
    )
    assert result.stopped is True
    report = loop.report_service.write_report(
        report_id="failure-report",
        cluster_id=started.cluster.id,
        best_candidate_id=None,
        revision=1,
        directions=(
            ReportDirection(
                direction_id=DirectionId.generate(),
                objective="bootstrap",
                outcome="failed",
            ),
        ),
        candidate_ids=(candidate.id,),
        record_ids=(failed.id,),
        failures=("bootstrap budget exhausted",),
        decision="failed without best",
        created_at=2,
    )
    assert report.best_candidate_id is None
    assert loop.clusters.get(started.cluster.id).best_candidate_id is None
