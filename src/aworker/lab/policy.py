"""Reproducible source checks; a clean result is not a compliance certificate."""

import hashlib
import re
from typing import Literal

from pydantic import BaseModel


# ---- Finding ----------------------------------------------------------------
class Finding(BaseModel):
    rule: str
    severity: Literal["error", "review"]
    message: str
    line: int | None = None


# ---- PolicyReport -----------------------------------------------------------
class PolicyReport(BaseModel):
    source_sha256: str
    automated_pass: bool
    certified: bool = False
    findings: list[Finding]
    checklist: list[str]


# ---- inspect_source ---------------------------------------------------------
def inspect_source(source: str, entrypoint: str = "run_kernel") -> PolicyReport:
    patterns = [
        (r"ACL_MEMCPY_DEVICE_TO_HOST", "host-input", "Device-to-Host copy in candidate source"),
        (
            r"\b(?:getenv|setenv|putenv)\s*\(",
            "judge-environment",
            "Candidate inspects or changes process environment",
        ),
        (
            r"\b(?:clock_gettime|usleep|nanosleep|sleep)\s*\(",
            "timing",
            "Candidate contains timer/sleep manipulation",
        ),
        (
            r"\b(?:system|popen|fork)\s*\(",
            "external-execution",
            "Candidate launches a host process",
        ),
    ]
    findings = []
    # Strip comments before checking activity; retain line numbers.
    cleaned = re.sub(r"/\*.*?\*/|//[^\n]*", lambda m: "\n" * m[0].count("\n"), source, flags=re.S)
    for pattern, rule, message in patterns:
        for match in re.finditer(pattern, cleaned):
            findings.append(
                Finding(
                    rule=rule,
                    severity="error",
                    message=message,
                    line=cleaned[: match.start()].count("\n") + 1,
                )
            )
    if not re.search(r"\b" + re.escape(entrypoint) + r"\s*\(", cleaned):
        findings.append(
            Finding(rule="entrypoint", severity="error", message=entrypoint + " is missing")
        )
    checklist = [
        "Host only validates metadata, performs integer tiling and launches",
        "No Host tensor reads, rearrangement, vector/matrix or inverse-frequency math",
        "No precomputed answers, exact-case matching, skipped computation or markers",
        "No old output, uninitialized memory or cross-call mathematical cache",
        "No changes to precision checks, warmup detection or timing boundaries",
        "Exactly one physical kernel per operator invocation; trace still required",
        "Fresh and repeated inputs, tails and general applicability must be verified",
    ]
    return PolicyReport(
        source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        automated_pass=not findings,
        findings=findings,
        checklist=checklist,
    )
