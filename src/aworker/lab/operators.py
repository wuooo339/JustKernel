"""Versioned operator packages, with independent evaluation code and inherited rules."""

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, JsonValue, model_validator

from aworker.lab.prepare import prepare_challenge
from aworker.lab.project import prepare_official_challenge


# ---- AdapterFiles -----------------------------------------------------------
class AdapterFiles(BaseModel):
    cmake: str = Field(default="", max_length=100_000)
    main: str = Field(default="", max_length=500_000)
    evaluate: str = Field(default="", max_length=500_000)
    reference: str = Field(default="", max_length=500_000)


# ---- OperatorDraft ----------------------------------------------------------
class OperatorDraft(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=200_000)
    cases: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=200)
    constraints: str = Field(default="", max_length=100_000)
    kernel: str = Field(
        default="// Implement run_kernel for this operator.\n", max_length=2_000_000
    )
    adapter: AdapterFiles = Field(default_factory=AdapterFiles)
    adapter_reviewed: bool = False
    questions: list[str] = Field(default_factory=list, max_length=30)

    # ---- input boundaries ---------------------------------------------------
    @model_validator(mode="after")
    def validate_cases(self):
        seen = set()
        for i, case in enumerate(self.cases):
            case.setdefault("id", f"case-{i + 1:02d}")
            if not isinstance(case["id"], str) or case["id"] in seen:
                raise ValueError("case IDs must be unique strings")
            seen.add(case["id"])
            if "shape" in case and (
                not isinstance(case["shape"], list)
                or not case["shape"]
                or any(type(x) is not int or x < 1 for x in case["shape"])
            ):
                raise ValueError("tensor shape must contain positive integer dimensions")
        return self


# ---- OperatorCatalog --------------------------------------------------------
class OperatorCatalog:
    def __init__(self, root: Path, default_operator: str = "RotaryPosEmb"):
        self.root = root
        self.folder = root / "operators"
        if not (root / "challenge").exists():
            if default_operator == "ConfusionMulGrad":
                prepare_official_challenge(root)
            else:
                prepare_challenge(root)
        self.builtin = json.loads((root / "challenge/manifest.json").read_text(encoding="utf-8"))[
            "operator"
        ]
        if default_operator == "ConfusionMulGrad" and self.builtin != default_operator:
            target = self.folder / default_operator
            if not (target / "definition.json").exists():
                target.mkdir(parents=True, exist_ok=True)
                prepare_official_challenge(target / "lab")
                draft = OperatorDraft(
                    id=default_operator, name=default_operator, description="Official project"
                )
                (target / "definition.json").write_text(draft.model_dump_json(), encoding="utf-8")

    # ---- package lookup -----------------------------------------------------
    def entry(self, key: str) -> dict:
        if key == self.builtin:
            return {"id": key, "name": key, "root": self.root, "builtin": True}
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", key):
            raise ValueError("invalid operator identity")
        path = self.folder / key / "definition.json"
        if not path.is_file():
            raise ValueError("operator does not exist")
        draft = OperatorDraft.model_validate_json(path.read_text(encoding="utf-8"))
        return {"id": key, "name": draft.name, "root": path.parent / "lab", "builtin": False}

    def selected(self) -> str:
        path = self.root / "active-operator.json"
        key = json.loads(path.read_text(encoding="utf-8"))["id"] if path.exists() else self.builtin
        self.entry(key)
        return key

    def catalog(self, include_archived: bool = False) -> list[dict]:
        keys = [self.builtin]
        keys.extend(p.parent.name for p in sorted(self.folder.glob("*/definition.json")))
        archive_file = self.root / "archived-operators.json"
        archived = (
            set(json.loads(archive_file.read_text(encoding="utf-8")))
            if archive_file.exists()
            else set()
        )
        rows = []
        for key in keys:
            if not include_archived and key in archived:
                continue
            entry = self.entry(key)
            manifest = json.loads(
                (entry["root"] / "challenge/manifest.json").read_text(encoding="utf-8")
            )
            cases = json.loads((entry["root"] / "challenge/cases.json").read_text(encoding="utf-8"))
            rows.append(
                {
                    "id": key,
                    "name": entry["name"],
                    "builtin": entry["builtin"],
                    "cases": len(cases),
                    "adapter_ready": manifest.get("adapter_ready", entry["builtin"]),
                    "active": key == self.selected(),
                    "archived": key in archived,
                }
            )
        return rows

    def activate(self, key: str) -> Path:
        entry = self.entry(key)
        (self.root / "active-operator.json").write_text(json.dumps({"id": key}), encoding="utf-8")
        return entry["root"]

    # ---- immutable creation -------------------------------------------------
    def create(self, draft: OperatorDraft) -> dict:
        if draft.id == self.builtin:
            raise ValueError("the bundled operator is immutable; choose a new ID")
        target = self.folder / draft.id
        target.mkdir(parents=True, exist_ok=False)
        challenge = target / "lab/challenge"
        challenge.mkdir(parents=True)
        defaults = (Path(__file__).parent / "resources/default_constraints.md").read_text(
            encoding="utf-8"
        )
        constraints = defaults + (
            "\n\n## Operator-specific constraints\n\n" + draft.constraints
            if draft.constraints
            else ""
        )
        files = {
            "statement.md": draft.description,
            "CONSTRAINTS.md": constraints,
            "kernel.asc": draft.kernel,
            "cases.json": json.dumps(draft.cases, ensure_ascii=False, indent=2),
            "input-source.json": json.dumps(
                {"source": "user operator package", "official_tensor_values_known": False}
            ),
        }
        for name, text in files.items():
            (challenge / name).write_text(text, encoding="utf-8")
        adapter = challenge / "evaluator"
        adapter.mkdir()
        for name, text in [
            ("CMakeLists.txt", draft.adapter.cmake),
            ("main.asc", draft.adapter.main),
            ("evaluate.py", draft.adapter.evaluate),
            ("reference.py", draft.adapter.reference),
        ]:
            if text.strip():
                (adapter / name).write_text(text, encoding="utf-8")
        complete = bool(
            draft.cases
            and all((adapter / n).is_file() for n in ("CMakeLists.txt", "main.asc", "evaluate.py"))
        )
        ready = complete and draft.adapter_reviewed
        manifest = {
            "operator": draft.id,
            "name": draft.name,
            "harness": "deepagents",
            "adapter_ready": ready,
            "baseline_sha256": hashlib.sha256((challenge / "kernel.asc").read_bytes()).hexdigest(),
            "input_definition": "User-defined package; inspect cases/evaluator before measuring",
            "not_official_hidden_cases": True,
            "package_files": {
                p.relative_to(challenge).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(challenge.rglob("*"))
                if p.is_file()
            },
        }
        (challenge / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (target / "definition.json").write_text(draft.model_dump_json(indent=2), encoding="utf-8")
        return {
            "id": draft.id,
            "adapter_ready": ready,
            "cases": len(draft.cases),
            "message": "Ready for trusted device evaluation"
            if ready
            else "Specification saved; complete and review its evaluator before NPU use",
        }
