# Real Acceptance Requirements

F09-04 remains blocked until a real CANN device/toolchain and a real model provider are
available. The boundary intentionally rejects simulation evidence.

## Required external run

Produce a deterministic evidence bundle from a real model + real CANN execution:

```text
real-acceptance/
├── manifest.json
├── final-record.zip
└── report.json
```

`manifest.json` must contain:

```json
{
  "schema": "justkernel.real_acceptance.v1",
  "real_model": true,
  "real_cann": true,
  "backend": "npu",
  "model_provider": "openai-compatible",
  "model_name": "...",
  "model_version": "...",
  "soc": "Ascend...",
  "cann_version": "...",
  "device": "npu:0",
  "record_id": "...",
  "artifact_digest": "<sha256 of final-record.zip>",
  "report": "report.json"
}
```

`final-record.zip` must be a complete executed `coverage=FULL`, `outcome=PASS` TEST
record. Its manifest `backend` must match the external backend and must not be
`cann-simulation`.

## Run

```bash
JUSTKERNEL_REAL_ACCEPTANCE_DIR=/absolute/path/to/real-acceptance \
  uv run pytest -q tests/e2e/test_real_acceptance.py
```

CI skips this test when the variable is absent. It never falls back to demo/fake PASS.
