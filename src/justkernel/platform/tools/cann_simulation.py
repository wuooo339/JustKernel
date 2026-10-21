"""Deterministic CANN simulation backend contract and fake runner."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from justkernel.agent.skills import SkillRef
from justkernel.shared.digest import Digest
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError
from justkernel.shared.ids import CandidateId, TaskId
from justkernel.shared.json import digest_json
from justkernel.testing.state import TestCoverage, TestOutcome, TestRecordKind


# ---- errors -----------------------------------------------------------------
class CannBackendError(JustKernelError):
    code = ErrorCode.TOOL_BACKEND_INVALID


# ---- environment ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CannEnvironment:
    soc: str
    cann_version: str
    python_version: str
    driver_version: str
    simulator_version: str

    def __post_init__(self) -> None:
        for name in (
            "soc",
            "cann_version",
            "python_version",
            "driver_version",
            "simulator_version",
        ):
            if not getattr(self, name):
                raise CannBackendError(f"environment {name} must be non-empty")

    def values(self, device: str | None = None) -> tuple[tuple[str, str], ...]:
        values = [
            ("soc", self.soc),
            ("cann_version", self.cann_version),
            ("python_version", self.python_version),
            ("driver_version", self.driver_version),
            ("simulator_version", self.simulator_version),
        ]
        if device is not None:
            values.append(("device", device))
        return tuple(sorted(values))

    def fingerprint(self, device: str | None = None) -> Digest:
        return digest_json(dict(self.values(device)))


# ---- metrics/cases ----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CannMetric:
    name: str
    value: float
    unit: str
    direction: str

    def __post_init__(self) -> None:
        if not self.name or not self.unit:
            raise CannBackendError("metric name and unit must be non-empty")
        if self.direction not in {"min", "max"}:
            raise CannBackendError("metric direction must be min or max")
        if not math.isfinite(self.value):
            raise CannBackendError("metric value must be finite")


@dataclass(frozen=True, slots=True)
class CannCaseResult:
    case_id: str
    passed: bool
    metrics: tuple[CannMetric, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.case_id:
            raise CannBackendError("case id must be non-empty")
        if self.error is not None and not self.error:
            raise CannBackendError("case error must be non-empty")


# ---- requests/execution -----------------------------------------------------
@dataclass(frozen=True, slots=True)
class CannRunRequest:
    kind: TestRecordKind
    task_id: TaskId
    candidate_id: CandidateId
    skill_ref: SkillRef
    case_selection: tuple[str, ...]
    timeout_s: int
    device: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in (TestRecordKind.TEST, TestRecordKind.PROFILE):
            raise CannBackendError("run kind must be TEST or PROFILE")
        if not self.case_selection or any(not case for case in self.case_selection):
            raise CannBackendError("case selection must be non-empty")
        if len(set(self.case_selection)) != len(self.case_selection):
            raise CannBackendError("case selection must not contain duplicates")
        if self.timeout_s <= 0:
            raise CannBackendError("timeout must be positive")
        if self.device is not None and not self.device:
            raise CannBackendError("device must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class CannExecution:
    outcome: TestOutcome
    coverage: TestCoverage
    cases: tuple[CannCaseResult, ...]
    metrics: tuple[CannMetric, ...]
    commands: tuple[str, ...]
    stdout: str
    stderr: str
    environment: CannEnvironment
    device: str | None
    duration_ms: int

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            raise CannBackendError("duration must be non-negative")

    def environment_fingerprint(self) -> Digest:
        return self.environment.fingerprint(self.device)


# ---- runner contract --------------------------------------------------------
class CannRunner(Protocol):
    def run(self, request: CannRunRequest) -> CannExecution: ...


# ---- fake runner ------------------------------------------------------------
class FakeCannRunner:
    def __init__(self, environment: CannEnvironment) -> None:
        self.environment = environment
        self.calls: list[CannRunRequest] = []

    def run(self, request: CannRunRequest) -> CannExecution:
        self.calls.append(request)
        cases = [self._case(case_id, index) for index, case_id in enumerate(request.case_selection)]
        outcome = self._outcome(cases)
        metrics = (
            CannMetric(
                name="sim_total_cycles",
                value=float(sum(case.metrics[0].value for case in cases)),
                unit="cycles",
                direction="min",
            ),
        )
        return CannExecution(
            outcome=outcome,
            coverage=TestCoverage.FULL,
            cases=tuple(cases),
            metrics=metrics,
            commands=tuple(f"cann-sim --case {case}" for case in request.case_selection),
            stdout="simulation complete\n",
            stderr="" if outcome is TestOutcome.PASS else "simulation failed\n",
            environment=self.environment,
            device=request.device,
            duration_ms=len(cases) * 10,
        )

    def _case(self, case_id: str, index: int) -> CannCaseResult:
        lower = case_id.lower()
        error = "simulated execution error" if "error" in lower else None
        passed = error is None and "fail" not in lower
        return CannCaseResult(
            case_id=case_id,
            passed=passed,
            metrics=(
                CannMetric(
                    name="sim_cycles",
                    value=100.0 + index,
                    unit="cycles",
                    direction="min",
                ),
            ),
            error=error,
        )

    def _outcome(self, cases: Sequence[CannCaseResult]) -> TestOutcome:
        if any(case.error is not None for case in cases):
            return TestOutcome.ERROR
        if any(not case.passed for case in cases):
            return TestOutcome.FAIL
        return TestOutcome.PASS


# ---- backend ----------------------------------------------------------------
class CannSimulationBackend:
    def __init__(
        self,
        environment: CannEnvironment,
        runner: CannRunner,
        *,
        backend_name: str = "cann-simulation",
    ) -> None:
        if not backend_name:
            raise CannBackendError("backend name must be non-empty")
        self.environment = environment
        self.runner = runner
        self.backend_name = backend_name
        self._requests: dict[str, CannRunRequest] = {}
        self._results: dict[str, CannExecution] = {}
        self._counter = 0

    def submit_test(
        self,
        *,
        task_id: TaskId,
        candidate_id: CandidateId,
        skill_ref: SkillRef,
        case_selection: tuple[str, ...],
        timeout_s: int,
        device: str | None = None,
    ) -> str:
        return self._submit(
            TestRecordKind.TEST,
            task_id,
            candidate_id,
            skill_ref,
            case_selection,
            timeout_s,
            device,
        )

    def submit_profile(
        self,
        *,
        task_id: TaskId,
        candidate_id: CandidateId,
        skill_ref: SkillRef,
        case_selection: tuple[str, ...],
        timeout_s: int,
        device: str | None = None,
    ) -> str:
        return self._submit(
            TestRecordKind.PROFILE,
            task_id,
            candidate_id,
            skill_ref,
            case_selection,
            timeout_s,
            device,
        )

    def request_for(self, job_id: str) -> CannRunRequest:
        request = self._requests.get(job_id)
        if request is None:
            raise CannBackendError(f"unknown job: {job_id}")
        return request

    def execute(self, job_id: str) -> CannExecution:
        cached = self._results.get(job_id)
        if cached is not None:
            return cached
        result = self.runner.run(self.request_for(job_id))
        self._results[job_id] = result
        return result

    def _submit(
        self,
        kind: TestRecordKind,
        task_id: TaskId,
        candidate_id: CandidateId,
        skill_ref: SkillRef,
        case_selection: tuple[str, ...],
        timeout_s: int,
        device: str | None,
    ) -> str:
        request = CannRunRequest(
            kind=kind,
            task_id=task_id,
            candidate_id=candidate_id,
            skill_ref=skill_ref,
            case_selection=case_selection,
            timeout_s=timeout_s,
            device=device,
        )
        self._counter += 1
        job_id = f"{self.backend_name}-{self._counter}"
        self._requests[job_id] = request
        return job_id
