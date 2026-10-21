---
name: cann-simulation-test
description: Compile and run a candidate with the CANN simulation backend, returning correctness and coarse performance evidence.
metadata:
  role: tester
  backend: cann-simulation
  version: "1"
allowed_tools:
  - read_candidate
  - submit_test
  - read_tool_job
  - read_test_record
  - report_progress
---

# CANN Simulation Tester

Use this skill when the task requires compilation and functional simulation on the
configured CANN target.

## Inputs

- task_id, candidate_id, skill_ref
- case_selection and timeout
- optional device

## Workflow

1. Read the candidate snapshot and the task context.
2. Call submit_test with the task, candidate, this skill, selected cases, timeout, and device.
3. Enter WAIT after receiving a ToolJobRef. Do not poll a board.
4. On the completion event, read the ToolJob and TestRecord.
5. Report outcome, per-case correctness, coarse timing, logs, and artifact digest.

## Output contract

Return the TestRecord summary: outcome, metrics, environment fingerprint, and artifact
digest. A missing or incomplete zip is an ERROR/UNKNOWN record, never PASS.

## Limitations

Simulation results do not prove real-device performance. A subset run is a probe, not
complete submission evidence.
