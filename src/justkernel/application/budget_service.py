"""Cluster budget reservations, rounds, plateau and failure accounting."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.application.ports import BudgetLedgerPort
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError
from justkernel.shared.ids import ClusterId
from justkernel.testing.policy import BudgetPolicy


# ---- errors -----------------------------------------------------------------
class BudgetError(JustKernelError):
    code = ErrorCode.BUDGET_ERROR


# ---- RoundResult ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RoundResult:
    rounds: int
    plateau_streak: int
    plateaued: bool
    can_explore: bool


# ---- BudgetService ----------------------------------------------------------
class BudgetService:
    def __init__(self, ledger: BudgetLedgerPort, policy: BudgetPolicy) -> None:
        self.ledger = ledger
        self.policy = policy
        self._rounds: dict[ClusterId, int] = {}
        self._streaks: dict[ClusterId, int] = {}
        self._failures: dict[ClusterId, int] = {}

    def reserve_exploration(
        self,
        cluster_id: ClusterId,
        amount: int,
        idempotency_key: str,
    ) -> bool:
        if amount <= 0 or not idempotency_key:
            return False
        if amount > self.available_exploration(cluster_id):
            return False
        return self.ledger.reserve(cluster_id, amount, idempotency_key)

    def reserve_final_validation(
        self,
        cluster_id: ClusterId,
        amount: int,
        idempotency_key: str,
    ) -> bool:
        if amount <= 0 or not idempotency_key:
            return False
        return self.ledger.reserve(cluster_id, amount, idempotency_key)

    def settle(self, cluster_id: ClusterId, amount: int, idempotency_key: str) -> bool:
        return self.ledger.settle(cluster_id, amount, idempotency_key)

    def available_exploration(self, cluster_id: ClusterId) -> int:
        reserve = self.policy.final_validation_reserve or 0
        return max(0, self.ledger.available(cluster_id) - reserve)

    def available_final(self, cluster_id: ClusterId) -> int:
        return self.ledger.available(cluster_id)

    def record_round(
        self,
        cluster_id: ClusterId,
        *,
        improved: bool,
        comparable: bool = True,
    ) -> RoundResult:
        rounds = self._rounds.get(cluster_id, 0)
        streak = self._streaks.get(cluster_id, 0)
        if comparable:
            rounds += 1
            streak = 0 if improved else streak + 1
            self._rounds[cluster_id] = rounds
            self._streaks[cluster_id] = streak
            if improved:
                self._failures[cluster_id] = 0
        plateaued = streak >= self.policy.plateau_rounds
        return RoundResult(rounds, streak, plateaued, self.can_explore(cluster_id))

    def record_failure(self, cluster_id: ClusterId) -> bool:
        failures = self._failures.get(cluster_id, 0) + 1
        self._failures[cluster_id] = failures
        return failures >= self.policy.max_consecutive_failures

    def can_explore(self, cluster_id: ClusterId) -> bool:
        if (
            self.policy.max_rounds is not None
            and self._rounds.get(cluster_id, 0) >= self.policy.max_rounds
        ):
            return False
        return self._failures.get(cluster_id, 0) < self.policy.max_consecutive_failures

    def plateaued(self, cluster_id: ClusterId) -> bool:
        return self._streaks.get(cluster_id, 0) >= self.policy.plateau_rounds

    def rounds(self, cluster_id: ClusterId) -> int:
        return self._rounds.get(cluster_id, 0)

    def consecutive_failures(self, cluster_id: ClusterId) -> int:
        return self._failures.get(cluster_id, 0)
