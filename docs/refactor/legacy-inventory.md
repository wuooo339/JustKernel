# Legacy Inventory and Migration Map

> Status: P0 inventory. The legacy `src/aworker/` tree is frozen; new code lives in `src/justkernel/`.
> Decisions: `reuse` (keep the behavior behind a new or existing port), `adapt` (extract/normalize into the new architecture), `delete` (do not migrate), `legacy-only` (read-only migration input), `new` (no legacy counterpart).
> Evidence: characterization tests in `tests/characterization/` and the baseline report in `docs/refactor/baseline-test-report.txt`.

## 1. Top-level legacy modules

| Legacy path | Responsibility | Decision | New location / replacement | Evidence |
| --- | --- | --- | --- | --- |
| `src/aworker/__init__.py` | Package marker and Settings re-export | `delete` | `src/justkernel/__init__.py` | import smoke |
| `src/aworker/__main__.py` | `python -m aworker` entry point | `delete` | `justkernel.bootstrap.cli` | CLI scaffold test |
| `src/aworker/cli.py` | Compatibility entry point | `delete` | `justkernel.bootstrap.cli:main` | CLI scaffold test |
| `src/aworker/config.py` | `AWORKER_*` settings, model/browser/SSH fields | `adapt` | `justkernel.platform.config` with `JUSTKERNEL_*` | P1/P8 config tests |
| `src/aworker/messages.py` | LangChain message text helpers | `adapt` | runtime message normalization | P4 runtime tests |
| `src/aworker/models.py` | LangChain model construction from client credentials | `adapt` | `justkernel.platform.models` | P4 model routing tests |

## 2. Legacy server and swarm

| Legacy path | Responsibility | Decision | New location / replacement | Evidence |
| --- | --- | --- | --- | --- |
| `src/aworker/server/app.py` | FastAPI A2A server | `delete` | `justkernel.platform.http` + A2A adapter | P7 API tests |
| `src/aworker/server/card.py` | A2A agent card built from swarm members | `adapt` | cluster A2A card | `test_agent_card_contract.py` |
| `src/aworker/server/client.py` | A2A client used by members | `delete` | internal message bus/A2A adapter | P7 A2A tests |
| `src/aworker/server/credentials.py` | Client-supplied model credentials in A2A extension | `adapt` | provider secret adapter | P4/P7 security tests |
| `src/aworker/server/executor.py` | A2A request lifecycle to swarm run | `delete` | control service turn orchestration | P6/P7 tests |
| `src/aworker/server/extensions.py` | A2A extension metadata | `adapt` | A2A gateway metadata | P7 A2A tests |
| `src/aworker/server/workspace.py` | Client-supplied workspace extension | `delete` | TaskContext artifact grants | P5/P7 tests |
| `src/aworker/swarm/member.py` | Single Deep Agents member | `delete` | `justkernel.agent` + runtime pool | P4 |
| `src/aworker/swarm/swarm.py` | Dynamic member registry | `delete` | cluster membership + mentor/worker model | P1/P4 |
| `src/aworker/swarm/__init__.py` | Swarm exports | `delete` | — | — |

## 3. Legacy lab core

| Legacy path | Responsibility | Decision | New location / replacement | Evidence |
| --- | --- | --- | --- | --- |
| `src/aworker/lab/__init__.py` | Lab package marker | `delete` | `src/justkernel` packages | — |
| `src/aworker/lab/api.py` | Dashboard, control API, SSE, A2A in one app | `delete` | `justkernel.platform.http` routes/SSE | P7 |
| `src/aworker/lab/bridge.py` | A2A transport dispatch | `delete` | `justkernel.platform.bus` | P4/P7 |
| `src/aworker/lab/cli.py` | Single CLI for old app | `delete` | `justkernel.bootstrap.cli` | P8 |
| `src/aworker/lab/continuous.py` | Continuous per-team model work | `delete` | wake scheduler + direction loop | P6 |
| `src/aworker/lab/dashboard.py` | Dashboard asset/version serving | `delete` | `justkernel.web` + HTTP static adapter | P7 |
| `src/aworker/lab/deepagent.py` | Deep Agents execution, checkpoints, events | `adapt` | `justkernel.platform.runtime` | P4 |
| `src/aworker/lab/domain.py` | Old typed coordinator/tool/dashboard contracts | `delete` | SPEC 04/13 domain types | P1 |
| `src/aworker/lab/export.py` | Portable evidence export without secrets | `adapt` | export service + redactor | P7/P8 |
| `src/aworker/lab/filesystem.py` | Pinned Deep Agents filesystem, Windows ripgrep | `adapt` | runtime workspace/backends | P4 |
| `src/aworker/lab/inputs.py` | Input metadata extraction | `adapt` | OperatorSpec `input_contract`/case pack | P6 |
| `src/aworker/lab/iteration.py` | Durable work items for one coder + Judge | `delete` | Task/TaskContext + wake scheduler | P1/P6 |
| `src/aworker/lab/judge_automation.py` | Official submission automation | `delete` | optional final acceptance skill only | P9 |
| `src/aworker/lab/judge_bridge.py` | Browser worker bridge | `delete` | — | — |
| `src/aworker/lab/judge_browser.py` | Ephemeral official-site browser | `delete` | — | — |
| `src/aworker/lab/judge_browser_worker.py` | Browser JSON-line transport | `delete` | — | — |
| `src/aworker/lab/judger.py` | Official public evidence and submission staging | `delete` | optional final acceptance skill only | P9 |
| `src/aworker/lab/lifecycle.py` | Service lock and interrupted-work recovery | `adapt` | `bootstrap.initialize` + recovery | P2/P8 |
| `src/aworker/lab/model_settings.py` | Private model settings in workbench | `adapt` | model profile registry | P4 |
| `src/aworker/lab/notices.py` | Judger/SOTA outbox | `delete` | events/outbox for cluster | P2 |
| `src/aworker/lab/operators.py` | Versioned operator packages/evaluators | `adapt` | OperatorSpec/import + artifact store | P6/P8 |
| `src/aworker/lab/persistence.py` | Serialized synchronous read/modify/write | `adapt` | SQLite UnitOfWork/transactions | P2 |
| `src/aworker/lab/policy.py` | Reproducible source checks | `adapt` | engineering policy checks | P5/P9 |
| `src/aworker/lab/prepare.py` | Operator challenge and team workspace prep | `delete` | cluster bootstrap/workspace adapter | P6 |
| `src/aworker/lab/probes.py` | Local hypotheses linked to feedback | `adapt` | TaskContext history/feedback | P6 |
| `src/aworker/lab/progress.py` | Baseline turn productivity gate | `delete` | budget/plateau/watchdog | P6 |
| `src/aworker/lab/project.py` | Multi-file operator identity/build inputs | `adapt` | SourceRevision/ProjectPath/artifact store | P1/P2 |
| `src/aworker/lab/providers.py` | Model interface/credential isolation | `adapt` | `platform.models` provider adapter | P4 |
| `src/aworker/lab/public_session.py` | Read-only public model/tool events | `delete` | event log/read models | P2/P7 |
| `src/aworker/lab/receipts.py` | Case-level performance/accuracy parsing | `adapt` | TestRecord metrics parser | P5 |
| `src/aworker/lab/runner.py` | Immutable candidate snapshots/device queue | `adapt` | candidate snapshots + hardware queue | P2/P5 |
| `src/aworker/lab/selection.py` | Read-only nomination of challenger | `delete` | BestSelection | P1/P6 |
| `src/aworker/lab/servers.py` | SSH profiles/credential vault/probes | `adapt` | hardware/tool device adapter | P5/P9 |
| `src/aworker/lab/service.py` | Team/experiment/artifact/learning service locator | `delete` | application services + ports | P3 |
| `src/aworker/lab/setup_agent.py` | Operator/server setup assistants | `delete` | operator intake/validation | P6 |
| `src/aworker/lab/simulation.py` | CANN worker experiments, queue, evidence | `adapt` | `platform.tools.cann_simulation` + ToolJob | P5 |
| `src/aworker/lab/store.py` | Experiment journal and device leases | `adapt` | SQLite journal + hardware ledger | P2 |
| `src/aworker/lab/supervisor.py` | Interpreter crash recovery | `delete` | control recovery/PAUSED semantics | P2/P6 |
| `src/aworker/lab/tool_arguments.py` | Tool argument compatibility normalization | `delete` | typed tool inputs | P4 |
| `src/aworker/lab/tools.py` | Engineering tools and evidence access | `adapt` | role tool registry/backends | P4/P5 |
| `src/aworker/lab/workbench_api.py` | Local workbench/SSH PTY API | `delete` | optional admin UI/API | P7/P9 |

## 4. Reusable resources

| Legacy path | Responsibility | Decision | New location | Evidence |
| --- | --- | --- | --- | --- |
| `lab/resources/simulator/worker.py` | CANN simulation worker and request/result protocol | `reuse` | `platform/tools/cann_simulation` adapter | `test_simulation_request_contract.py` |
| `lab/resources/simulator/runner.cpp` | Native simulation runner | `reuse` | tool backend resource | P5 contract test |
| `lab/resources/simulator/CMakeLists.txt` | Simulator build | `reuse` | tool backend resource | P5 |
| `lab/resources/simulator/pool.py` | Simulator pool helper | `adapt` | hardware queue/pool | P5 |
| `lab/resources/skills/compliance-review/SKILL.md` | Compliance review skill | `reuse` | `resources/skills` (or user skill) | `test_skills_contract.py` |
| `lab/resources/skills/evidence-distillation/SKILL.md` | Evidence distillation skill | `reuse` | `resources/skills` | `test_skills_contract.py` |
| `lab/resources/skills/kernel-engineering/SKILL.md` | Kernel engineering skill | `reuse` | `resources/skills` | `test_skills_contract.py` |
| `lab/resources/confusion_mul_grad/*` | Operator example/statement/cases | `legacy-only` | import fixture / OperatorSpec samples | `test_verified_fixture_contract.py` |
| `lab/resources/rotary_pos_emb/*` | Additional operator sample | `legacy-only` | import fixture | P8 |
| `lab/resources/evaluator/*` | Old evaluator assets | `adapt` | evaluation backend resource | P5 |
| `lab/resources/models.toml` | Old model profiles | `adapt` | `models.toml` / model registry | P4 |
| `lab/resources/web/*` | Old multi-team dashboard | `delete` | `src/justkernel/web` | P7 |

## 5. Legacy data and compatibility

| Item | Decision | Handling |
| --- | --- | --- |
| `.justkernel` / lab roots with `work-items`, judge, queue JSON | `legacy-only` | read-only importer; mark records `LEGACY`; never active board/candidate |
| `AWORKER_*` environment variables | `legacy-only` | only `justkernel migrate` may read; runtime uses `JUSTKERNEL_*` |
| Old HTTP/A2A endpoints | `delete` | no compatibility guarantee; new `/api/v1` and cluster card |
| Old CLI names | `delete` in P8 | transitional aliases only until cutover |
| Old best/champion records | `legacy-only` | import as read-only; re-validate before any new best |

## 6. New modules without legacy counterpart

| New area | Why new |
| --- | --- |
| `cluster`, `agent`, `comm`, `task`, `candidate`, `testing`, `report` | SPEC 04 domain model, ACL, state machines, TestRecord/BestSelection |
| `platform/persistence`, `artifacts`, `runtime`, `bus`, `hardware`, `models`, `http`, `security` | SPEC 03 ports/adapters and SPEC 08 storage |
| `bootstrap` | composition root, CLI, migration, recovery |
| `resources/skills/base`, `resources/skills/builtin` | six role skills + built-in tester/profiler |
| `resources/templates` | GENERATE templates |
| `web` | single-cluster board/task/candidate/record/queue/report UI |

## 7. Reuse evidence

The following tests must stay green until the corresponding adapter is replaced:

- `tests/characterization/test_simulation_request_contract.py` — simulation request schema/defaults.
- `tests/characterization/test_skills_contract.py` — legacy skill frontmatter/names.
- `tests/characterization/test_agent_card_contract.py` — A2A card defaults/transport.
- `tests/characterization/test_verified_fixture_contract.py` — verified fixture identity/hashes.

When P5/P8 replaces an adapter, add an equivalent contract test under `tests/adapters/` before deleting the characterization test.
