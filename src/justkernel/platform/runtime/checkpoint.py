"""Session checkpoint storage (recovery data, not evidence)."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from justkernel.platform.runtime.errors import CheckpointError
from justkernel.shared.ids import AgentId, ClusterId
from justkernel.shared.json import canonical_json


# ---- CheckpointStore --------------------------------------------------------
class CheckpointStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(
        self,
        cluster_id: ClusterId,
        agent_id: AgentId,
        session_id: str,
        payload: Mapping[str, object],
    ) -> str:
        self._validate_session(session_id)
        ref = f"{cluster_id.value}/{agent_id.value}/{session_id}.json"
        target = self.root / ref
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._write_atomic(target, canonical_json(dict(payload)))
        return ref

    def load(
        self, cluster_id: ClusterId, agent_id: AgentId, session_id: str
    ) -> dict[str, object] | None:
        self._validate_session(session_id)
        path = self.root / f"{cluster_id.value}/{agent_id.value}/{session_id}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise CheckpointError("checkpoint is unreadable") from error
        if not isinstance(data, dict):
            raise CheckpointError("checkpoint payload must be an object")
        return data

    def list_sessions(self, cluster_id: ClusterId, agent_id: AgentId) -> tuple[str, ...]:
        directory = self.root / cluster_id.value / agent_id.value
        if not directory.is_dir():
            return ()
        return tuple(sorted(path.stem for path in directory.glob("*.json")))

    def _validate_session(self, session_id: str) -> None:
        if (
            not session_id
            or "/" in session_id
            or "\\" in session_id
            or "\x00" in session_id
            or session_id in {".", ".."}
        ):
            raise CheckpointError(f"invalid session id: {session_id!r}")

    def _write_atomic(self, target: Path, text: str) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=".tmp-", dir=target.parent)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, target)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
