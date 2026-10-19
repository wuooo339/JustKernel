---
name: kernel-engineering
description: Implement the active official operator project and retain source, validation and submission evidence separately.
---

Read /statement.md, /CONSTRAINTS.md, /cases.json and /input-source.json.
Record shapes, dtypes, attributes, numerical semantics and the input pack identity.
Read /project-manifest.json when present. Only edit its editable_paths under /project/;
never modify protected build files, test programs or evaluation infrastructure.
For a repair work item, register one concrete hypothesis with record_experiment_plan:
evidence, intended change, original validation criteria, and explicit local case_ids.
Implement directly in single-coder mode. Independent Judger reviews frozen source.
Optional specialists in parallel mode answer narrow questions, not a repeated full task.
Keep an explanation that follows general capacity, alignment, dtype or data dependencies.
Use inspect_policy before an experiment. Check first and repeated outputs, failures,
source SHA and every measured case. A local timing is not an official score.
Publish only measured passing code; retain failed and slower experiments.
Judge-only mode has no physical NPU execution lane; the CPU simulator is separate.
When independent simulation is required, call simulate_kernel for this team's own code:
all selected local INPUT cases receive PVModel functional checks, followed by detailed
CAModel/msopprof profiling on fixed representative cases. Explicit subsets are probes,
not complete submission evidence. Use actual diagnostics to repair the implementation.
Complete an own independent experiment before peer learning, then re-test borrowed ideas.
Full local coverage and matching source/input/worker identities qualify a frozen candidate.
Judger independently reviews and nominates it before official submission. The coding
owner does not approve its own candidate. Never modify the reference or thresholds.
A staged package is not an official submission or passing result.
Public testcase IDs do not reveal hidden input values. Keep provisional cases labeled.
