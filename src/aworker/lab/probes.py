"""Feedback-linked local hypotheses, separate from immutable baseline/hidden INPUT."""

import hashlib
import json
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aworker.lab.persistence import replace_file


# ---- LocalCaseProposal -----------------------------------------------------
class LocalCaseProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shape: tuple[int, int]
    dtype: Literal["float16", "float32"]
    axis: list[int] = Field(min_length=1, max_length=2)
    keep_dims: bool = False
    seed: int = Field(default=1700, ge=0, le=2**32 - 1)
    low: float = Field(default=-10, ge=-10, le=10, allow_inf_nan=False)
    high: float = Field(default=10, ge=-10, le=10, allow_inf_nan=False)

    @model_validator(mode="after")
    def supported_input(self):
        if any(n < 1 for n in self.shape) or math.prod(self.shape) > 33_554_432:
            raise ValueError("probe shape must be positive and at most 32M elements")
        if any(a not in {-2, -1, 0, 1} for a in self.axis) or self.low >= self.high:
            raise ValueError("invalid axes or numeric range")
        self.axis = sorted({a % 2 for a in self.axis})
        return self


# ---- immutable hypothesis catalogue ----------------------------------------
def local_cases(service, team):
    service.team_folder(team)
    path = service.root / "diagnostic-cases" / (team + ".json")
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


# ---- proposals cite actual official feedback, never assert hidden identity ---
def propose_cases(service, team, submission_id, hypothesis, cases):
    if service.operator != "ConfusionMulGrad":
        raise ValueError("this diagnostic case adapter supports ConfusionMulGrad only")
    if not 20 <= len(hypothesis.strip()) <= 2000 or not 1 <= len(cases) <= 4:
        raise ValueError("provide one concrete hypothesis and 1–4 small, relevant probes")
    receipt = next(
        (
            r
            for r in service.judger.read("queue.json", [])
            if r["team"] == team
            and r.get("official_submission_id") == submission_id
            and service.judger.terminal(r.get("official", {}).get("status"))
        ),
        None,
    )
    if receipt is None:
        raise ValueError("cite this team's actual terminal official submission, not a guessed case")
    drafts = [LocalCaseProposal.model_validate(c) for c in cases]
    with service.judger.data_lock:
        rows = local_cases(service, team)
        selected = []
        for draft in drafts:
            data = draft.model_dump()
            key = (
                "probe-"
                + hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]
            )
            prior = next((r for r in rows if r["id"] == key), None)
            if prior is None:
                if sum(r["evidence_submission_id"] == submission_id for r in rows) >= 8:
                    raise ValueError(
                        "at most 8 new hypotheses per official receipt; test them before expanding"
                    )
                low, high = data.pop("low"), data.pop("high")
                prior = {
                    "id": key,
                    **data,
                    "inputs": ["input0", "input1", "input2"],
                    "distribution": {"kind": "uniform", "low": low, "high": high},
                    "official_case_id": None,
                    "provenance": "feedback-hypothesis-unconfirmed",
                    "evidence_submission_id": submission_id,
                    "evidence_source_sha256": receipt["source_sha256"],
                    "hypothesis": service.redact(hypothesis),
                }
                rows.append(prior)
            selected.append(prior)
        path = service.root / "diagnostic-cases" / (team + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_file(temporary, path)
    service.store.event(
        team,
        "input.hypotheses.proposed",
        submission_id=submission_id,
        cases=selected,
        official_mapping="unconfirmed; not reconstructed hidden cases",
    )
    return selected
