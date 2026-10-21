from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "examples" / "confusionmulgrad" / "verified" / "baseline.json"
DIGEST = re.compile(r"^[a-f0-9]{64}$")


# ---- legacy verified fixture ------------------------------------------------
def test_verified_fixture_identity_and_hashes() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert data["schema"] == "justkernel.verified-solution.v1"
    assert data["operator"] == "ConfusionMulGrad"
    assert data["official"]["status"] == "Pass"
    assert len(data["template_files"]) == 34

    digests = [
        data["source_sha256"],
        data["template_sha256"],
        *data["template_files"].values(),
        *data["overlays"].values(),
    ]
    assert all(DIGEST.fullmatch(digest) for digest in digests)
