"""Cluster aggregate and its lifecycle commands."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.cluster.errors import ClusterError
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import ClusterPhase, ClusterState, StartMode
from justkernel.shared.ids import AgentId, CandidateId, ClusterId

TERMINAL_STATES = frozenset({ClusterState.COMPLETED, ClusterState.STOPPED, ClusterState.FAILED})
MIN_MAX_AGENTS = 6


# ---- Cluster ----------------------------------------------------------------
@dataclass(slots=True)
class Cluster:
    id: ClusterId
    operator_id: str
    supervisor_id: AgentId
    operator_spec_ref: OperatorRef
    start_mode: StartMode
    created_at: int
    max_agents: int = 100
    state: ClusterState = ClusterState.INITIALIZING
    phase: ClusterPhase = ClusterPhase.BOOTSTRAPPING
    baseline_candidate_id: CandidateId | None = None
    best_candidate_id: CandidateId | None = None
    report_id: str | None = None
    continued_from_cluster_id: ClusterId | None = None
    closed_at: int | None = None
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.operator_id:
            raise ClusterError("operator_id must be non-empty")
        if self.created_at < 0:
            raise ClusterError("created_at must be non-negative")
        if self.max_agents < MIN_MAX_AGENTS:
            raise ClusterError(f"max_agents must be at least {MIN_MAX_AGENTS}")
        if self.report_id is not None and not self.report_id:
            raise ClusterError("report_id must be non-empty")
        self._check_terminal_fields()
        if self.state is ClusterState.CONVERGING and self.phase is not ClusterPhase.FINALIZING:
            raise ClusterError("CONVERGING requires FINALIZING phase")
        if self.state is ClusterState.COMPLETED:
            if self.phase is not ClusterPhase.FINALIZING:
                raise ClusterError("COMPLETED requires FINALIZING phase")
            if self.best_candidate_id is None or self.report_id is None:
                raise ClusterError("COMPLETED requires best candidate and report")
        if self.phase is not ClusterPhase.BOOTSTRAPPING and self.baseline_candidate_id is None:
            raise ClusterError("non-bootstrapping phase requires a baseline")
        if self.best_candidate_id is not None and self.phase is not ClusterPhase.FINALIZING:
            raise ClusterError("best candidate requires FINALIZING phase")

    # ---- validation helpers -------------------------------------------------
    def _check_terminal_fields(self) -> None:
        terminal = self.state in TERMINAL_STATES
        if terminal != (self.closed_at is not None):
            raise ClusterError("closed_at must be set exactly for terminal states")
        if self.closed_at is not None and self.closed_at < self.created_at:
            raise ClusterError("closed_at must not precede created_at")
        if self.state in (ClusterState.STOPPED, ClusterState.FAILED):
            if not self.terminal_reason:
                raise ClusterError("terminal stop/fail requires a reason")
        elif self.terminal_reason is not None:
            raise ClusterError("only STOPPED/FAILED carry a terminal reason")

    def _require_open(self) -> None:
        if self.state in TERMINAL_STATES:
            raise ClusterError(f"cluster is terminal: {self.state}")

    def _require_state(self, *allowed: ClusterState) -> None:
        if self.state not in allowed:
            raise ClusterError(f"cannot transition from {self.state}")

    def _require_time(self, now_ms: int) -> None:
        if now_ms < self.created_at:
            raise ClusterError("event time must not precede created_at")

    # ---- commands -----------------------------------------------------------
    def start(self) -> None:
        self._require_state(ClusterState.INITIALIZING)
        self.state = ClusterState.RUNNING

    def pause(self) -> None:
        self._require_state(ClusterState.RUNNING)
        self.state = ClusterState.PAUSED

    def resume(self) -> None:
        self._require_state(ClusterState.PAUSED)
        self.state = ClusterState.RUNNING

    def establish_baseline(self, candidate_id: CandidateId) -> None:
        self._require_state(ClusterState.RUNNING)
        if self.phase is not ClusterPhase.BOOTSTRAPPING:
            raise ClusterError("baseline can only be established during bootstrapping")
        if self.baseline_candidate_id is not None:
            raise ClusterError("baseline is already established")
        self.baseline_candidate_id = candidate_id
        self.phase = ClusterPhase.OPTIMIZING

    def converge(self) -> None:
        self._require_state(ClusterState.RUNNING)
        if self.phase is not ClusterPhase.OPTIMIZING:
            raise ClusterError("convergence requires an optimized baseline")
        self.state = ClusterState.CONVERGING
        self.phase = ClusterPhase.FINALIZING

    def set_best_candidate(self, candidate_id: CandidateId) -> None:
        self._require_state(ClusterState.CONVERGING)
        if self.phase is not ClusterPhase.FINALIZING:
            raise ClusterError("best candidate requires finalizing phase")
        self.best_candidate_id = candidate_id

    def attach_report(self, report_id: str) -> None:
        if not report_id:
            raise ClusterError("report_id must be non-empty")
        if self.state is ClusterState.COMPLETED:
            raise ClusterError("completed cluster cannot replace its report")
        if self.report_id is not None and self.report_id != report_id:
            raise ClusterError("report is already attached")
        self.report_id = report_id

    def complete(self, now_ms: int) -> None:
        self._require_state(ClusterState.CONVERGING)
        self._require_time(now_ms)
        if self.best_candidate_id is None or self.report_id is None:
            raise ClusterError("completion requires best candidate and report")
        self.state = ClusterState.COMPLETED
        self.closed_at = now_ms

    def stop(self, reason: str, now_ms: int) -> None:
        self._require_open()
        if not reason:
            raise ClusterError("stop reason must be non-empty")
        self._require_state(ClusterState.RUNNING, ClusterState.PAUSED, ClusterState.CONVERGING)
        self._require_time(now_ms)
        self.state = ClusterState.STOPPED
        self.closed_at = now_ms
        self.terminal_reason = reason

    def fail(self, reason: str, now_ms: int) -> None:
        self._require_open()
        if not reason:
            raise ClusterError("failure reason must be non-empty")
        self._require_state(ClusterState.INITIALIZING, ClusterState.RUNNING)
        self._require_time(now_ms)
        self.state = ClusterState.FAILED
        self.closed_at = now_ms
        self.terminal_reason = reason

    def set_max_agents(self, max_agents: int) -> None:
        self._require_open()
        if max_agents < MIN_MAX_AGENTS:
            raise ClusterError(f"max_agents must be at least {MIN_MAX_AGENTS}")
        self.max_agents = max_agents
