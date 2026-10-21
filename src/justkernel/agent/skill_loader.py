"""Role-aware SKILL.md loading and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from justkernel.agent.skills import SkillRef
from justkernel.agent.state import Role
from justkernel.comm.capabilities import Tool, can_use_tool
from justkernel.shared.digest import Digest
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError

MAX_SKILL_BYTES = 10 * 1024 * 1024
SECRET_NAMES = frozenset({".env", "id_rsa", "id_ed25519"})
SECRET_SUFFIXES = frozenset({".key", ".pem"})
DEFAULT_BACKENDS = frozenset({"cann-simulation", "cann-profiler", "npu"})


# ---- SkillLoadError ---------------------------------------------------------
class SkillLoadError(JustKernelError):
    code = ErrorCode.SKILL_INVALID


# ---- SkillDefinition --------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SkillDefinition:
    name: str
    description: str
    role: Role
    backend: str
    version: str
    allowed_tools: frozenset[Tool]
    source_path: str
    digest: Digest
    scripts: tuple[str, ...] = ()

    def to_ref(self) -> SkillRef:
        return SkillRef(
            name=self.name,
            version=self.version,
            source_path=self.source_path,
            digest=self.digest,
        )


# ---- SkillLoader ------------------------------------------------------------
class SkillLoader:
    def __init__(
        self,
        base_dir: Path,
        builtin_dir: Path,
        user_dir: Path,
        *,
        allow_user_scripts: bool = False,
        registered_backends: frozenset[str] | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.builtin_dir = builtin_dir
        self.user_dir = user_dir
        self.allow_user_scripts = allow_user_scripts
        self.registered_backends = registered_backends or DEFAULT_BACKENDS

    def load(self, role: Role) -> tuple[SkillDefinition, ...]:
        skills: dict[str, SkillDefinition] = {}
        paths: list[tuple[Path, Path, bool]] = []
        base = self.base_dir / role.value.lower() / "SKILL.md"
        if base.is_file():
            paths.append((base, self.base_dir, False))
        if role is Role.TESTER:
            builtin = self.builtin_dir / "tester-cann-simulation" / "SKILL.md"
            user_root = self.user_dir / "tester"
        elif role is Role.PROFILER:
            builtin = self.builtin_dir / "profiler-cann" / "SKILL.md"
            user_root = self.user_dir / "profiler"
        else:
            builtin = None
            user_root = None
        if builtin is not None and builtin.is_file():
            paths.append((builtin, self.builtin_dir, False))
        if user_root is not None and user_root.is_dir():
            for path in sorted(user_root.glob("*/SKILL.md")):
                paths.append((path, self.user_dir, True))
        for path, root, user_skill in paths:
            skill = self._load(path, root, role, user_skill)
            skills[skill.name] = skill
        return tuple(skills.values())

    def _load(
        self,
        path: Path,
        root: Path,
        role: Role,
        user_skill: bool,
    ) -> SkillDefinition:
        self._safe_path(path, root)
        if not path.is_file():
            raise SkillLoadError(f"skill file is missing: {path}")
        if path.stat().st_size > MAX_SKILL_BYTES:
            raise SkillLoadError(f"skill file exceeds size limit: {path}")
        raw = path.read_bytes()
        self._scan_secrets(path.parent)
        header = self._frontmatter(raw.decode("utf-8"))
        name = self._text(header, "name")
        description = self._text(header, "description")
        metadata = header.get("metadata")
        if not isinstance(metadata, dict):
            raise SkillLoadError("skill metadata must be an object")
        expected_role = role.value.lower()
        if metadata.get("role") != expected_role:
            raise SkillLoadError(f"skill role must be {expected_role}")
        backend = self._metadata_text(metadata, "backend")
        if backend not in self.registered_backends:
            raise SkillLoadError(f"skill backend is not registered: {backend}")
        version = self._metadata_text(metadata, "version")
        allowed = self._allowed_tools(header.get("allowed_tools"), role)
        scripts = self._scripts(path.parent, user_skill)
        return SkillDefinition(
            name=name,
            description=description,
            role=role,
            backend=backend,
            version=version,
            allowed_tools=allowed,
            source_path=path.as_posix(),
            digest=Digest.from_bytes(raw),
            scripts=scripts,
        )

    def _safe_path(self, path: Path, root: Path) -> None:
        if not path.resolve().is_relative_to(root.resolve()):
            raise SkillLoadError(f"skill path escapes its root: {path}")

    def _scan_secrets(self, directory: Path) -> None:
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if name in SECRET_NAMES or path.suffix.lower() in SECRET_SUFFIXES:
                raise SkillLoadError(f"secret file is not allowed in a skill: {path.name}")

    def _frontmatter(self, text: str) -> dict[str, Any]:
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            raise SkillLoadError("SKILL.md must start with YAML frontmatter")
        try:
            end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
        except StopIteration as error:
            raise SkillLoadError("SKILL.md frontmatter is not closed") from error
        try:
            data = yaml.safe_load("\n".join(lines[1:end]))
        except yaml.YAMLError as error:
            raise SkillLoadError("SKILL.md frontmatter is invalid YAML") from error
        if not isinstance(data, dict):
            raise SkillLoadError("SKILL.md frontmatter must be an object")
        return data

    def _text(self, data: dict[str, Any], key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise SkillLoadError(f"skill {key} must be non-empty")
        return value

    def _metadata_text(self, metadata: dict[str, Any], key: str) -> str:
        value = metadata.get(key)
        if not isinstance(value, str) or not value:
            raise SkillLoadError(f"skill metadata.{key} must be non-empty")
        return value

    def _allowed_tools(self, value: object, role: Role) -> frozenset[Tool]:
        if not isinstance(value, list):
            raise SkillLoadError("skill allowed_tools must be a list")
        tools: set[Tool] = set()
        for name in value:
            if not isinstance(name, str):
                raise SkillLoadError("skill allowed_tools entries must be strings")
            try:
                tool = Tool(name)
            except ValueError as error:
                raise SkillLoadError(f"unknown skill tool: {name}") from error
            if not can_use_tool(role, tool):
                raise SkillLoadError(f"tool {name} is not allowed for {role.value}")
            tools.add(tool)
        return frozenset(tools)

    def _scripts(self, directory: Path, user_skill: bool) -> tuple[str, ...]:
        scripts_dir = directory / "scripts"
        if not scripts_dir.is_dir():
            return ()
        scripts = tuple(
            path.relative_to(scripts_dir).as_posix()
            for path in sorted(scripts_dir.rglob("*"))
            if path.is_file()
        )
        if user_skill and scripts and not self.allow_user_scripts:
            raise SkillLoadError("user skill scripts are disabled")
        return scripts
