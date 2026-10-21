from __future__ import annotations

from justkernel.application.budget_service import BudgetService
from justkernel.application.candidate_service import CandidateService
from justkernel.application.fakes import (
    FakeIds,
    InMemoryAgentRepository,
    InMemoryBudgetLedger,
    InMemoryCandidateRepository,
    InMemoryTaskRepository,
)
from justkernel.shared.ids import ClusterId, DirectionId
from justkernel.testing.policy import BudgetPolicy


# ---- helpers ----------------------------------------------------------------
def _policy(**overrides: object) -> BudgetPolicy:
    values: dict[str, object] = {
        "max_duration_s": 100,
        "max_rounds": 3,
        "plateau_rounds": 2,
        "max_consecutive_failures": 2,
        "final_validation_reserve": 20,
    }
    values.update(overrides)
    return BudgetPolicy(**values)


def _budget(policy: BudgetPolicy | None = None) -> tuple[BudgetService, ClusterId]:
    cluster = ClusterId.generate()
    return BudgetService(InMemoryBudgetLedger(100), policy or _policy()), cluster


def _candidate_service() -> tuple[CandidateService, InMemoryCandidateRepository, ClusterId]:
    candidates = InMemoryCandidateRepository()
    service = CandidateService(
        candidates,
        InMemoryTaskRepository(),
        InMemoryAgentRepository(),
        FakeIds(),
    )
    return service, candidates, ClusterId.generate()


def _import(service: CandidateService, cluster: ClusterId, source: str, import_id: str) -> object:
    return service.import_candidate(
        cluster_id=cluster,
        direction_id=DirectionId.generate(),
        source_files={"kernel.cpp": source},
        diff_artifact="artifact://diff",
        import_id=import_id,
        created_at=0,
    )


# ---- final validation reserve ----------------------------------------------
def test_exploration_cannot_consume_final_validation_reserve() -> None:
    service, cluster = _budget()

    assert service.available_exploration(cluster) == 80
    assert service.reserve_exploration(cluster, 80, "explore-1") is True
    assert service.available_exploration(cluster) == 0
    assert service.reserve_exploration(cluster, 1, "explore-2") is False
    assert service.reserve_final_validation(cluster, 20, "final-1") is True
    assert service.available_final(cluster) == 0
    assert service.settle(cluster, 80, "explore-1") is True
    assert service.settle(cluster, 20, "final-1") is True
    assert service.available_exploration(cluster) == 0


def test_invalid_reservation_amounts_are_rejected() -> None:
    service, cluster = _budget()

    assert service.reserve_exploration(cluster, 0, "zero") is False
    assert service.reserve_final_validation(cluster, -1, "negative") is False
    assert service.reserve_exploration(cluster, 10, "") is False


# ---- plateau ----------------------------------------------------------------
def test_plateau_requires_consecutive_comparable_non_improvements() -> None:
    service, cluster = _budget(_policy(plateau_rounds=2, max_rounds=3))

    first = service.record_round(cluster, improved=False, comparable=True)
    second = service.record_round(cluster, improved=False, comparable=True)

    assert first.plateaued is False
    assert second.plateaued is True
    assert second.rounds == 2
    assert service.plateaued(cluster) is True


def test_improvement_resets_plateau_and_non_comparable_does_not_count() -> None:
    service, cluster = _budget(_policy(plateau_rounds=2, max_rounds=3))

    service.record_round(cluster, improved=False, comparable=True)
    ignored = service.record_round(cluster, improved=False, comparable=False)
    improved = service.record_round(cluster, improved=True, comparable=True)
    after = service.record_round(cluster, improved=False, comparable=True)

    assert ignored.rounds == 1
    assert ignored.plateau_streak == 1
    assert improved.rounds == 2
    assert improved.plateau_streak == 0
    assert after.plateau_streak == 1
    assert after.plateaued is False


def test_round_and_failure_caps_stop_exploration() -> None:
    service, cluster = _budget(_policy(max_rounds=2, max_consecutive_failures=2))

    first = service.record_round(cluster, improved=False, comparable=True)
    second = service.record_round(cluster, improved=False, comparable=True)
    assert first.can_explore is True
    assert second.can_explore is False
    assert service.can_explore(cluster) is False

    other, other_cluster = _budget(_policy(max_rounds=10, max_consecutive_failures=2))
    assert other.record_failure(other_cluster) is False
    assert other.record_failure(other_cluster) is True
    assert other.can_explore(other_cluster) is False


# ---- duplicate candidates ---------------------------------------------------
def test_duplicate_source_is_detectable_without_deleting_candidates() -> None:
    service, repository, cluster = _candidate_service()
    first = _import(service, cluster, "// same", "import-1")
    second = _import(service, cluster, "// same", "import-2")
    different = _import(service, cluster, "// different", "import-3")

    assert service.find_duplicate(first.id) is None
    assert service.find_duplicate(second.id) == first
    assert service.find_duplicate(different.id) is None
    assert len(repository.list_by_cluster(cluster)) == 3
