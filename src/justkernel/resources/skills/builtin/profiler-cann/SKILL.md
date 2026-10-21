---
name: cann-profiler
description: Collect detailed CANN performance profiles for representative candidate cases.
metadata:
  role: profiler
  backend: cann-profiler
  version: "1"
allowed_tools:
  - read_candidate
  - submit_profile
  - read_tool_job
  - read_test_record
  - report_progress
---

# CANN Profiler

Use this skill when a candidate has passed correctness and the task needs comparable
performance evidence.

## Inputs

- task_id, candidate_id, skill_ref
- representative case_selection and timeout
- optional device

## Workflow

1. Read the candidate snapshot and evaluation policy.
2. Call submit_profile with the task, candidate, this skill, cases, timeout, and device.
3. Enter WAIT for the completion event.
4. Read the ToolJob and TestRecord; return per-case timing/cycles, hotspots, profile
   artifact references, environment fingerprint, and artifact digest.

## Limitations

Profile only within the frozen environment and measurement protocol. Simulation
cycles cannot be converted into real-device time. Do not reuse a profile from another
candidate or environment as evidence for this candidate.
