"""Command-line entry point for JustKernel v2."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from justkernel import __version__
from justkernel.platform.data_root import ServiceLock, initialize_data_root
from justkernel.platform.config import (
    AppConfig,
    ConfigError,
    RunMode,
    apply_cli,
    load_config,
)
from justkernel.platform.persistence.database import connect
from justkernel.platform.persistence.legacy_import import LegacyImporter
from justkernel.platform.persistence.migrations import apply_migrations
from justkernel.shared.errors import JustKernelError

USAGE = "usage: justkernel --version"
DEMO_FIXTURE = Path(__file__).resolve().parents[1] / "web" / "demo" / "fixture.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="justkernel")
    parser.add_argument("--mode", choices=[mode.value for mode in RunMode])
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--private-root", type=Path)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--log-level")
    parser.add_argument("--legacy-db", type=Path)
    return parser


def _config(arguments: argparse.Namespace) -> AppConfig:
    return apply_cli(
        load_config(),
        mode=arguments.mode,
        data_root=arguments.data_root,
        private_root=arguments.private_root,
        host=arguments.host,
        port=arguments.port,
        log_level=arguments.log_level,
    )


def _print_config(config: AppConfig) -> None:
    print(
        f"mode={config.mode.value} "
        f"data_root={config.data_root} "
        f"private_root={config.private_root} "
        f"host={config.host} port={config.port} log_level={config.log_level}"
    )


def _run_mode(config: AppConfig, legacy_db: Path | None) -> int:
    if config.mode is RunMode.MIGRATE:
        return _migrate(config, legacy_db)
    if config.mode is RunMode.DEMO and not DEMO_FIXTURE.is_file():
        raise ConfigError(f"demo fixture is missing: {DEMO_FIXTURE}")
    _print_config(config)
    return 0


def _migrate(config: AppConfig, legacy_db: Path | None) -> int:
    if legacy_db is None:
        raise ConfigError("migrate requires --legacy-db")
    layout = initialize_data_root(config)
    with ServiceLock(layout.service_lock):
        connection = connect(str(config.data_root / "journal.db"))
        try:
            apply_migrations(connection)
            report = LegacyImporter(connection, legacy_db).import_data()
        finally:
            connection.close()
    print(
        f"mode=migrate imported={report.records_imported} "
        f"idempotent={str(report.already_imported).lower()} "
        f"import_id={report.import_id} data_root={config.data_root}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse config/mode arguments and dispatch the selected runtime mode."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--version"]:
        print(f"justkernel {__version__}")
        return 0
    if not arguments:
        print(USAGE)
        return 0
    try:
        parsed = _parser().parse_args(arguments)
        return _run_mode(_config(parsed), parsed.legacy_db)
    except (ConfigError, JustKernelError) as error:
        print(f"error: {error.message}", file=sys.stderr)
        return 2
