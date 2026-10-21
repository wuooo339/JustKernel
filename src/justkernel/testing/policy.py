"""Evaluation and budget policies frozen at cluster start."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from justkernel.shared.digest import Digest
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError
from justkernel.shared.json import digest_json


# ---- PolicyError ------------------------------------------------------------
class PolicyError(JustKernelError):
    code = ErrorCode.INVALID_POLICY


# ---- _check_non_negative ----------------------------------------------------
def _check_non_negative(name: str, value: float | int | None) -> None:
    if value is not None and value < 0:
        raise PolicyError(f"{name} must be non-negative")


# ---- _check_finite ----------------------------------------------------------
def _check_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise PolicyError(f"{name} must be finite")


# ---- EvaluationPolicy -------------------------------------------------------
@dataclass(frozen=True, slots=True)
class EvaluationPolicy:
    """Frozen comparison rules for correctness and performance evidence."""

    case_pack_digest: Digest
    reference_digest: Digest
    accuracy_policy_digest: Digest
    allowed_backends: tuple[str, ...]
    environment_fingerprint: str
    timing_unit: str
    warmup: int
    repeats: int
    aggregation: str
    aggregation_params: tuple[tuple[str, float], ...] = ()
    per_case_regression_limit: float | None = None
    min_improvement: float = 0.0
    performance_target_enabled: bool = False
    profiler_required: bool = False

    def __post_init__(self) -> None:
        if not self.allowed_backends or any(not backend for backend in self.allowed_backends):
            raise PolicyError("allowed_backends must be non-empty")
        for name in ("environment_fingerprint", "timing_unit", "aggregation"):
            if not getattr(self, name):
                raise PolicyError(f"{name} must be non-empty")
        _check_non_negative("warmup", self.warmup)
        _check_non_negative("per_case_regression_limit", self.per_case_regression_limit)
        _check_finite("min_improvement", self.min_improvement)
        _check_finite("per_case_regression_limit", self.per_case_regression_limit or 0.0)
        if self.warmup < 0:
            raise PolicyError("warmup must be non-negative")
        if self.repeats < 1:
            raise PolicyError("repeats must be at least 1")
        if self.min_improvement < 0:
            raise PolicyError("min_improvement must be non-negative")
        if self.per_case_regression_limit is not None and self.per_case_regression_limit < 0:
            raise PolicyError("per_case_regression_limit must be non-negative")
        names = [name for name, _ in self.aggregation_params]
        if any(not name for name in names) or len(set(names)) != len(names):
            raise PolicyError("aggregation_params names must be unique and non-empty")
        for _, value in self.aggregation_params:
            _check_finite("aggregation_params value", value)
        if self.performance_target_enabled and not self.profiler_required:
            raise PolicyError("performance target requires profiler_required=True")

    def digest(self) -> Digest:
        return digest_json(asdict(self))


# ---- BudgetPolicy -----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    """Cluster-level hard limits and convergence controls."""

    max_duration_s: int | None = None
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    max_tool_seconds: int | None = None
    max_device_seconds: int | None = None
    max_rounds: int | None = None
    max_bootstrap_attempts: int | None = None
    plateau_rounds: int = 5
    max_consecutive_failures: int = 3
    final_validation_reserve: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "max_duration_s",
            "max_tokens",
            "max_cost_usd",
            "max_tool_seconds",
            "max_device_seconds",
            "max_rounds",
            "max_bootstrap_attempts",
            "final_validation_reserve",
        ):
            _check_non_negative(name, getattr(self, name))
        if self.max_cost_usd is not None:
            _check_finite("max_cost_usd", self.max_cost_usd)
        for name in ("max_rounds", "max_bootstrap_attempts", "final_validation_reserve"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise PolicyError(f"{name} must be positive")
        if self.plateau_rounds <= 0:
            raise PolicyError("plateau_rounds must be positive")
        if self.max_consecutive_failures <= 0:
            raise PolicyError("max_consecutive_failures must be positive")

        global_caps = (
            self.max_duration_s,
            self.max_tokens,
            self.max_cost_usd,
            self.max_tool_seconds,
            self.max_device_seconds,
            self.max_rounds,
        )
        if all(cap is None for cap in global_caps):
            raise PolicyError("at least one global hard cap is required")

    def digest(self) -> Digest:
        return digest_json(asdict(self))
