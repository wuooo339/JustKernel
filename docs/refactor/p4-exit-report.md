# P4 Exit Report

Date: 2026-10-21  
Project: `Refactor/` independent `justkernel`  
Remote: `origin/refactor`

## Completed features

| Feature | Commit | Evidence |
| --- | --- | --- |
| F04-01 Model routing and fallback | `704710c` | 6 routing tests; D-033 |
| F04-02 Runtime pool/checkpoints | `a5df37f` | 7 runtime tests; D-034 |
| F04-03 Skill loading and safety | `d999243` | 7 skill tests; D-035 |
| F04-04 Role and built-in skills | `0c30d71` | 3 role-skill tests; D-036 |
| F04-05 Tool registry and object ACL | `a2c50f4` | 6 tool-matrix tests; D-037 |
| F04-06 Runtime lifecycle and cap | `4f002c7` | 3 integration tests; D-038 |

## Exit criteria

- [x] Six roles have base skills; tester/profiler also have built-in CANN skills.
- [x] Worker skills contain no board tools.
- [x] Tool availability equals the role capability matrix.
- [x] Object grants are checked before handlers run.
- [x] Domain and runtime both reject the 101st active agent.
- [x] A worker with a running task cannot close and keeps its lease.
- [x] Successful worker close releases all tracked device leases.
- [x] `AgentRuntimePool.close_all()` leaves zero active sessions.
- [x] Checkpoints remain available after shutdown.
- [x] No orphan session or untracked lease remains in the integration scenario.

## Verification at P4 exit

```text
uv run pytest -q tests/integration/test_agent_lifecycle.py
3 passed

uv run pytest -q
265 passed

uv run mypy src/justkernel
Success: no issues found in 99 source files

uv run ruff check src tests
All checks passed!

uv run ruff format --check src tests
161 files already formatted

uv build
justkernel-0.1.0.tar.gz
justkernel-0.1.0-py3-none-any.whl
```

## Scope and limitations

P4 establishes routing, runtime/session contracts, skills, tool authorization, and
lifecycle cleanup. The runner is deterministic/fake in tests; real Deep Agents process
integration remains an adapter concern. `WorkerLifecycle` is the required close path
when leases exist; `AgentService.close_worker` alone does not release them. Control
shutdown/recovery coordination and asynchronous ToolJobs start in P5.

## Next

P5 starts with **F05-01 Asynchronous ToolJob service**.
