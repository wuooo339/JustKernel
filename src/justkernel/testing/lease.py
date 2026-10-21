"""Hardware lease aggregate."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.shared.ids import AgentId, LeaseId, TaskId
from justkernel.testing.errors import LeaseError
from justkernel.testing.state import LeaseState


# ---- DeviceId ---------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DeviceId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise LeaseError("device id must be non-empty")


# ---- HardwareLease ----------------------------------------------------------
@dataclass(slots=True)
class HardwareLease:
    id: LeaseId
    device_id: DeviceId
    task_id: TaskId
    owner_agent_id: AgentId
    state: LeaseState = LeaseState.QUEUED
    acquired_at: int | None = None
    expires_at: int | None = None
    released_at: int | None = None

    def __post_init__(self) -> None:
        for name in ("acquired_at", "expires_at", "released_at"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise LeaseError(f"{name} must be non-negative")
        if (
            self.acquired_at is not None
            and self.expires_at is not None
            and self.expires_at <= self.acquired_at
        ):
            raise LeaseError("expires_at must be after acquired_at")
        self._check_state_fields()

    def _check_state_fields(self) -> None:
        if self.state is LeaseState.QUEUED:
            if (
                self.acquired_at is not None
                or self.expires_at is not None
                or self.released_at is not None
            ):
                raise LeaseError("queued lease must not have timestamps")
        elif self.state is LeaseState.LEASED:
            if self.acquired_at is None or self.expires_at is None:
                raise LeaseError("leased lease requires acquired_at and expires_at")
            if self.released_at is not None:
                raise LeaseError("leased lease must not be released")
        elif self.state is LeaseState.RELEASED:
            if self.acquired_at is None or self.expires_at is None or self.released_at is None:
                raise LeaseError("released lease requires all timestamps")
            if self.released_at < self.acquired_at:
                raise LeaseError("released_at must not precede acquired_at")
        elif self.state is LeaseState.EXPIRED:
            if self.acquired_at is None or self.expires_at is None:
                raise LeaseError("expired lease requires acquired_at and expires_at")
            if self.released_at is not None:
                raise LeaseError("expired lease must not be released")

    @property
    def is_active(self) -> bool:
        return self.state is LeaseState.LEASED

    def acquire(self, now_ms: int, ttl_ms: int) -> None:
        if self.state is not LeaseState.QUEUED:
            raise LeaseError(f"cannot acquire lease in {self.state}")
        if now_ms < 0 or ttl_ms <= 0:
            raise LeaseError("acquire requires non-negative time and positive TTL")
        self.acquired_at = now_ms
        self.expires_at = now_ms + ttl_ms
        self.state = LeaseState.LEASED

    def release(self, now_ms: int) -> None:
        if self.state is not LeaseState.LEASED:
            raise LeaseError(f"cannot release lease in {self.state}")
        assert self.acquired_at is not None
        if now_ms < self.acquired_at:
            raise LeaseError("release time must not precede acquisition")
        self.released_at = now_ms
        self.state = LeaseState.RELEASED

    def expire(self, now_ms: int) -> None:
        if self.state is not LeaseState.LEASED:
            raise LeaseError(f"cannot expire lease in {self.state}")
        assert self.expires_at is not None
        if now_ms < self.expires_at:
            raise LeaseError("lease has not reached its expiry")
        self.state = LeaseState.EXPIRED
