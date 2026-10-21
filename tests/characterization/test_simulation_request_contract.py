from __future__ import annotations

from aworker.lab.simulation import SimulationRequest


# ---- legacy simulator request ----------------------------------------------
def test_simulation_request_defaults_and_alias() -> None:
    request = SimulationRequest(
        id="a" * 32,
        workspace_id="workspace",
        team="team-1",
        operator="ConfusionMulGrad",
        files={"op_kernel/kernel.cpp": "// source"},
        source_sha256="b" * 64,
        cases_json="[]",
        case_pack_sha256="c" * 64,
        case_ids=["case-1"],
        worker_sha256="d" * 64,
        hypothesis="lock the legacy request contract",
        created_at=0.0,
    )

    payload = request.model_dump(by_alias=True)

    assert request.schema_version == "justkernel.simulation.request.v1"
    assert payload["schema"] == "justkernel.simulation.request.v1"
    assert request.target_soc == "Ascend910B4"
    assert request.evaluation_mode == "full-profile"
    assert request.timeout_seconds == 3600
    assert request.profile_case_ids == []
