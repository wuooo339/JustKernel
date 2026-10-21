"""Application configuration loaded from .env/environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError

DEFAULT_PORT = 4173
DEFAULT_HOST = "127.0.0.1"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_MAX_AGENTS = 100


class ConfigError(JustKernelError):
    code = ErrorCode.INVALID_CONFIG


class RunMode(StrEnum):
    CLUSTER = "cluster"
    DEMO = "demo"
    WORKER = "worker"
    MIGRATE = "migrate"


@dataclass(frozen=True, slots=True)
class AppConfig:
    mode: RunMode
    data_root: Path
    private_root: Path
    host: str
    port: int
    log_level: str
    max_agents: int = DEFAULT_MAX_AGENTS
    max_workers_per_mentor: int = 8

    def __post_init__(self) -> None:
        if not self.host:
            raise ConfigError("host must be non-empty")
        if not 1 <= self.port <= 65535:
            raise ConfigError("port must be between 1 and 65535")
        if not self.log_level:
            raise ConfigError("log level must be non-empty")
        if self.max_agents < 6:
            raise ConfigError("max_agents must be at least 6")
        if self.max_workers_per_mentor < 1:
            raise ConfigError("max_workers_per_mentor must be positive")


@dataclass(frozen=True, slots=True)
class LimitsConfig:
    model_concurrency: int = 8
    runtime_processes: int = 8
    max_agents: int = DEFAULT_MAX_AGENTS
    max_workers_per_mentor: int = 8
    max_task_duration_s: int = 1800
    max_turn_duration_s: int = 300
    max_message_attempts: int = 3
    queue_timeout_s: int = 600

    def __post_init__(self) -> None:
        for name in (
            "model_concurrency",
            "runtime_processes",
            "max_agents",
            "max_workers_per_mentor",
            "max_task_duration_s",
            "max_turn_duration_s",
            "max_message_attempts",
            "queue_timeout_s",
        ):
            if getattr(self, name) <= 0:
                raise ConfigError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class StorageConfig:
    database: Path
    artifacts: Path
    checkpoints: Path
    retention_days: int = 30


@dataclass(frozen=True, slots=True)
class SkillsConfig:
    base_dir: Path
    builtin_dir: Path
    user_dir: Path
    allow_user_scripts: bool = False


def load_config(
    env: Mapping[str, str] | None = None,
    *,
    cwd: Path | None = None,
) -> AppConfig:
    directory = (cwd or Path.cwd()).resolve()
    values = _dotenv(directory / ".env")
    values.update(dict(os.environ if env is None else env))
    data_root = Path(values.get("JUSTKERNEL_DATA_ROOT", ".justkernel"))
    private_root = Path(
        values.get(
            "JUSTKERNEL_PRIVATE_ROOT",
            str(Path.home() / ".local" / "share" / "justkernel" / "private"),
        )
    )
    return AppConfig(
        mode=_mode(values.get("JUSTKERNEL_MODE", RunMode.CLUSTER.value)),
        data_root=(directory / data_root if not data_root.is_absolute() else data_root).resolve(),
        private_root=(
            directory / private_root if not private_root.is_absolute() else private_root
        ).resolve(),
        host=values.get("JUSTKERNEL_HOST", DEFAULT_HOST),
        port=_int(values, "JUSTKERNEL_PORT", DEFAULT_PORT),
        log_level=values.get("JUSTKERNEL_LOG_LEVEL", DEFAULT_LOG_LEVEL),
        max_agents=_int(values, "JUSTKERNEL_MAX_AGENTS", DEFAULT_MAX_AGENTS),
        max_workers_per_mentor=_int(values, "JUSTKERNEL_MAX_WORKERS_PER_MENTOR", 8),
    )


def apply_cli(
    config: AppConfig,
    *,
    mode: str | None = None,
    data_root: Path | None = None,
    private_root: Path | None = None,
    host: str | None = None,
    port: int | None = None,
    log_level: str | None = None,
) -> AppConfig:
    return replace(
        config,
        mode=_mode(mode) if mode is not None else config.mode,
        data_root=data_root.resolve() if data_root is not None else config.data_root,
        private_root=private_root.resolve() if private_root is not None else config.private_root,
        host=host if host is not None else config.host,
        port=port if port is not None else config.port,
        log_level=log_level if log_level is not None else config.log_level,
    )


def limits_from_env(env: Mapping[str, str] | None = None) -> LimitsConfig:
    values = dict(os.environ if env is None else env)
    return LimitsConfig(
        model_concurrency=_int(values, "JUSTKERNEL_MODEL_CONCURRENCY", 8),
        runtime_processes=_int(values, "JUSTKERNEL_RUNTIME_PROCESSES", 8),
        max_agents=_int(values, "JUSTKERNEL_MAX_AGENTS", DEFAULT_MAX_AGENTS),
        max_workers_per_mentor=_int(values, "JUSTKERNEL_MAX_WORKERS_PER_MENTOR", 8),
        max_task_duration_s=_int(values, "JUSTKERNEL_MAX_TASK_S", 1800),
        max_turn_duration_s=_int(values, "JUSTKERNEL_MAX_TURN_S", 300),
        max_message_attempts=_int(values, "JUSTKERNEL_MAX_MESSAGE_ATTEMPTS", 3),
        queue_timeout_s=_int(values, "JUSTKERNEL_QUEUE_TIMEOUT_S", 600),
    )


def _mode(value: str) -> RunMode:
    try:
        return RunMode(value)
    except ValueError as error:
        raise ConfigError(f"invalid mode: {value}") from error


def _int(values: Mapping[str, str], key: str, default: int) -> int:
    raw = values.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ConfigError(f"{key} must be an integer") from error


def _dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result
