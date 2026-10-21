from __future__ import annotations

import math

import pytest

from justkernel.agent.skills import SkillRef
from justkernel.application.ports import ToolBackendPort
from justkernel.platform.tools.cann_simulation import (
    CannBackendError,
    CannEnvironment,
    CannSimulationBackend,
    FakeCannRunner,
)
from justkernel.shared.digest import Digest
from justkernel.shared.ids import CandidateId, TaskId
from justkernel.testing.state import TestCoverage as Coverage
from justkernel.testing.state import TestOutcome as Outcome
from justkernel.testing.state import TestRecordKind as RecordKind


# ---- helpers ----------------------------------------------------------------
def _skill(name: str = "cann-simulation-test") -> SkillRef:
    return SkillRef(
        name=name,
        version="1",
        source_path=f"/skills/{name}",
        digest=Digest.from_text(name),
    )


def _environment(**overrides: str) -> CannEnvironment:
    values = {
        "soc": "Ascend910B4",
        "cann_version": "9.0.0",
        "python_version": "3.13.0",
        "driver_version": "25.0",
        "simulator_version": "1.0",
    }
    values.update(overrides)
    return CannEnvironment(**values)


def _backend(
    *,
    environment: CannEnvironment | None = None,
    runner: FakeCannRunner | None = None,
) -> CannSimulationBackend:
    env = environment or _environment()
    return CannSimulationBackend(env, runner or FakeCannRunner(env))


def _submit_test(
    backend: CannSimulationBackend,
    *,
    cases: tuple[str, ...] = ("case-1",),
    timeout_s: int = 30,
    device: str | None = "sim:0",
) -> str:
    return backend.submit_test(
        task_id=TaskId.generate(),
        candidate_id=CandidateId.generate(),
        skill_ref=_skill(),
        case_selection=cases,
        timeout_s=timeout_s,
        device=device,
    )


# ---- contract ---------------------------------------------------------------
def test_backend_implements_tool_backend_contract() -> None:
    backend = _backend()
    assert isinstance(backend, ToolBackendPort)
    assert backend.backend_name == "cann-simulation"

    job_id = _submit_test(backend)
    request = backend.request_for(job_id)
    assert request.kind is RecordKind.TEST
    assert request.case_selection == ("case-1",)
    assert request.timeout_s == 30
    assert request.device == "sim:0"


def test_profile_submission_is_recorded() -> None:
    backend = _backend()
    job_id = backend.submit_profile(
        task_id=TaskId.generate(),
        candidate_id=CandidateId.generate(),
        skill_ref=_skill("cann-profiler"),
        case_selection=("case-1", "case-2"),
        timeout_s=60,
        device=None,
    )

    request = backend.request_for(job_id)
    assert request.kind is RecordKind.PROFILE
    assert request.case_selection == ("case-1", "case-2")
    assert request.device is None


# ---- validation -------------------------------------------------------------
def test_invalid_requests_are_rejected() -> None:
    backend = _backend()

    with pytest.raises(CannBackendError):
        _submit_test(backend, cases=())
    with pytest.raises(CannBackendError):
        _submit_test(backend, timeout_s=0)
    with pytest.raises(CannBackendError):
        _submit_test(backend, device="")

    with pytest.raises(CannBackendError):
        backend.request_for("missing")
    with pytest.raises(CannBackendError):
        backend.execute("missing")


# ---- execution --------------------------------------------------------------
def test_fake_execution_binds_request_and_environment() -> None:
    backend = _backend()
    job_id = _submit_test(backend, cases=("case-1", "case-2"))

    execution = backend.execute(job_id)

    assert execution.outcome is Outcome.PASS
    assert execution.coverage is Coverage.FULL
    assert [case.case_id for case in execution.cases] == ["case-1", "case-2"]
    assert execution.environment_fingerprint() == backend.environment.fingerprint("sim:0")
    assert all(math.isfinite(metric.value) for metric in execution.metrics)
    assert execution.commands
    assert execution.stdout


def test_fake_runner_reports_fail_and_error() -> None:
    backend = _backend()
    fail_job = _submit_test(backend, cases=("ok", "fail-case"))
    error_job = _submit_test(backend, cases=("ok", "error-case"))

    failed = backend.execute(fail_job)
    errored = backend.execute(error_job)

    assert failed.outcome is Outcome.FAIL
    assert errored.outcome is Outcome.ERROR
    assert failed.cases[1].passed is False
    assert errored.cases[1].error == "simulated execution error"
    assert backend.execute(fail_job) is failed


def test_environment_fingerprint_is_stable_and_device_sensitive() -> None:
    first = _environment()
    second = _environment()
    changed = _environment(cann_version="9.1.0")

    assert first.fingerprint() == second.fingerprint()
    assert first.fingerprint() != changed.fingerprint()
    assert first.fingerprint("sim:0") != first.fingerprint("sim:1")
    assert dict(first.values("sim:0"))["device"] == "sim:0"


def test_environment_rejects_missing_values() -> None:
    with pytest.raises(CannBackendError):
        _environment(soc="")
    with pytest.raises(CannBackendError):
        CannSimulationBackend(_environment(), FakeCannRunner(_environment()), backend_name="")
