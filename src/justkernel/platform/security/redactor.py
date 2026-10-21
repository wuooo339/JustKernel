"""Central redaction for logs, exports, errors and downloadable text."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REDACTED = "[redacted]"
PRIVATE_PATH = "[private-path]"
MIN_SECRET_LENGTH = 8


class Redactor:
    def __init__(
        self,
        *,
        secrets: Sequence[str] = (),
        private_roots: Sequence[Path] = (),
    ) -> None:
        self._secrets: set[str] = set()
        self._roots: list[str] = []
        for secret in secrets:
            self.register_secret(secret)
        for root in private_roots:
            self.register_private_root(root)

    def register_secret(self, value: str) -> None:
        if len(value) >= MIN_SECRET_LENGTH:
            self._secrets.add(value)

    def register_private_root(self, root: Path) -> None:
        text = str(root.resolve())
        if text and text not in self._roots:
            self._roots.append(text)

    def redact_text(self, text: str) -> str:
        result = text
        for secret in sorted(self._secrets, key=len, reverse=True):
            result = result.replace(secret, REDACTED)
        for root in sorted(self._roots, key=len, reverse=True):
            result = result.replace(root, PRIVATE_PATH)
        return result

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, Mapping):
            return {str(key): self.redact(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return tuple(self.redact(item) for item in value)
        return value


def default_redactor() -> Redactor:
    return Redactor()
