"""Cluster journal SQLite schema (migration 1)."""

from __future__ import annotations

INITIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS clusters (
  id TEXT PRIMARY KEY,
  operator_id TEXT NOT NULL,
  supervisor_id TEXT NOT NULL,
  operator_spec_digest TEXT NOT NULL,
  start_mode TEXT NOT NULL CHECK (start_mode IN ('GENERATE','IMPORT')),
  phase TEXT NOT NULL CHECK (phase IN ('BOOTSTRAPPING','OPTIMIZING','FINALIZING')),
  baseline_candidate_id TEXT,
  continued_from_cluster_id TEXT,
  state TEXT NOT NULL,
  max_agents INTEGER NOT NULL,
  best_candidate_id TEXT,
  report_id TEXT,
  created_at INTEGER NOT NULL,
  closed_at INTEGER,
  version INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS cluster_operator ON clusters(operator_id);

CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL REFERENCES clusters(id),
  role TEXT NOT NULL,
  mentor_id TEXT REFERENCES agents(id),
  model_profile TEXT NOT NULL,
  skills_json TEXT NOT NULL,
  state TEXT NOT NULL,
  session_id TEXT,
  created_at INTEGER NOT NULL,
  closed_at INTEGER,
  version INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS one_supervisor
  ON agents(cluster_id) WHERE role = 'SUPERVISOR' AND state != 'CLOSED';

CREATE TABLE IF NOT EXISTS directions (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL REFERENCES clusters(id),
  mentor_id TEXT NOT NULL REFERENCES agents(id),
  objective TEXT NOT NULL,
  constraints_json TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  closed_at INTEGER,
  version INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_direction
  ON directions(mentor_id) WHERE state IN ('PROPOSED','ACTIVE','PAUSED');

CREATE TABLE IF NOT EXISTS candidates (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL REFERENCES clusters(id),
  parent_id TEXT REFERENCES candidates(id),
  direction_id TEXT NOT NULL REFERENCES directions(id),
  author_agent_id TEXT REFERENCES agents(id),
  author_principal TEXT NOT NULL,
  task_id TEXT REFERENCES tasks(id),
  import_id TEXT,
  source_digest TEXT NOT NULL,
  source_artifact TEXT NOT NULL,
  diff_artifact TEXT,
  evaluation_json TEXT,
  created_at INTEGER NOT NULL,
  CHECK ((task_id IS NOT NULL AND import_id IS NULL AND author_agent_id IS NOT NULL)
      OR (task_id IS NULL AND import_id IS NOT NULL AND author_agent_id IS NULL
          AND author_principal = 'system'))
);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL REFERENCES clusters(id),
  mentor_id TEXT NOT NULL REFERENCES agents(id),
  worker_id TEXT NOT NULL REFERENCES agents(id),
  kind TEXT NOT NULL CHECK (kind IN ('GENERATE','OPTIMIZE','TEST','PROFILE')),
  direction_id TEXT NOT NULL REFERENCES directions(id),
  operator_spec_digest TEXT NOT NULL,
  context_artifact TEXT NOT NULL,
  context_digest TEXT NOT NULL,
  retry_of_task_id TEXT REFERENCES tasks(id),
  budget_ref TEXT NOT NULL,
  candidate_id TEXT REFERENCES candidates(id),
  skill_json TEXT,
  objective TEXT NOT NULL,
  constraints_json TEXT NOT NULL,
  state TEXT NOT NULL,
  result_ref TEXT,
  created_at INTEGER NOT NULL,
  finished_at INTEGER,
  version INTEGER NOT NULL DEFAULT 0,
  CHECK ((kind = 'GENERATE' AND candidate_id IS NULL)
      OR (kind IN ('OPTIMIZE','TEST','PROFILE') AND candidate_id IS NOT NULL)),
  CHECK (kind NOT IN ('TEST','PROFILE') OR skill_json IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_running_task_per_agent
  ON tasks(worker_id) WHERE state IN ('ASSIGNED','RUNNING');

CREATE TABLE IF NOT EXISTS test_records (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL REFERENCES clusters(id),
  candidate_id TEXT NOT NULL REFERENCES candidates(id),
  task_id TEXT REFERENCES tasks(id),
  job_id TEXT,
  audit_id TEXT UNIQUE,
  executed INTEGER NOT NULL CHECK (executed IN (0,1)),
  coverage TEXT NOT NULL CHECK (coverage IN ('FULL','SUBSET','NONE')),
  operator_spec_digest TEXT NOT NULL,
  case_pack_digest TEXT NOT NULL,
  reference_digest TEXT NOT NULL,
  accuracy_policy_digest TEXT NOT NULL,
  evaluation_policy_digest TEXT NOT NULL,
  environment_fingerprint TEXT NOT NULL,
  measurement_protocol_digest TEXT,
  kind TEXT NOT NULL,
  skill_json TEXT NOT NULL,
  backend TEXT NOT NULL,
  outcome TEXT NOT NULL,
  metrics_json TEXT,
  environment_json TEXT NOT NULL,
  artifact TEXT NOT NULL,
  artifact_digest TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  CHECK (outcome != 'PASS' OR (executed = 1 AND coverage IN ('FULL','SUBSET'))),
  CHECK ((task_id IS NOT NULL AND audit_id IS NULL)
      OR (task_id IS NULL AND audit_id IS NOT NULL AND executed = 0
          AND outcome IN ('CANCELLED','UNKNOWN') AND coverage = 'NONE'))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_record_per_task
  ON test_records(task_id) WHERE task_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS hardware_leases (
  id TEXT PRIMARY KEY,
  device_id TEXT NOT NULL,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  owner_agent_id TEXT NOT NULL REFERENCES agents(id),
  state TEXT NOT NULL,
  acquired_at INTEGER,
  expires_at INTEGER,
  released_at INTEGER,
  version INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS board_posts (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  cluster_id TEXT NOT NULL,
  board TEXT NOT NULL,
  topic TEXT NOT NULL,
  author_agent_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  schema_version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  seq INTEGER NOT NULL,
  type TEXT NOT NULL,
  sender TEXT NOT NULL,
  recipient TEXT,
  correlation_id TEXT,
  causation_id TEXT,
  payload_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  delivered_at INTEGER,
  schema_version INTEGER NOT NULL,
  UNIQUE(channel, seq)
);

CREATE TABLE IF NOT EXISTS reports (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  best_candidate_id TEXT,
  report_artifact TEXT NOT NULL,
  report_digest TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE(cluster_id, revision)
);

CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  cluster_id TEXT NOT NULL,
  type TEXT NOT NULL,
  event_version INTEGER NOT NULL,
  aggregate_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  aggregate_version INTEGER NOT NULL,
  actor TEXT NOT NULL,
  correlation_id TEXT,
  causation_id TEXT,
  payload_json TEXT NOT NULL,
  occurred_at INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
  SELECT RAISE(ABORT, 'events are append-only');
END;
CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
  SELECT RAISE(ABORT, 'events are append-only');
END;

CREATE TABLE IF NOT EXISTS outbox (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  available_at INTEGER NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projections (
  name TEXT PRIMARY KEY,
  last_seq INTEGER NOT NULL,
  schema_version INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_jobs (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id),
  candidate_id TEXT NOT NULL REFERENCES candidates(id),
  request_digest TEXT NOT NULL,
  state TEXT NOT NULL,
  record_id TEXT REFERENCES test_records(id),
  error_json TEXT,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_inbox (
  agent_id TEXT NOT NULL REFERENCES agents(id),
  event_id TEXT NOT NULL REFERENCES events(event_id),
  event_seq INTEGER NOT NULL,
  state TEXT NOT NULL,
  wake_id TEXT,
  PRIMARY KEY(agent_id, event_id)
);

CREATE TABLE IF NOT EXISTS wake_requests (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agents(id),
  reason TEXT NOT NULL,
  event_ids_json TEXT NOT NULL,
  expected_agent_version INTEGER NOT NULL,
  not_before INTEGER NOT NULL,
  state TEXT NOT NULL,
  turn_id TEXT UNIQUE,
  wait_json TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_claimed_wake_per_agent
  ON wake_requests(agent_id) WHERE state = 'CLAIMED';

CREATE TABLE IF NOT EXISTS best_selections (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL REFERENCES clusters(id),
  candidate_id TEXT NOT NULL REFERENCES candidates(id),
  policy_digest TEXT NOT NULL,
  nomination_record_ids_json TEXT NOT NULL,
  final_task_ids_json TEXT NOT NULL,
  final_record_ids_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('PENDING','VALIDATED','FAILED')),
  reason TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS task_artifact_grants (
  grant_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  artifact_digest TEXT NOT NULL,
  readonly_scope_json TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE(task_id, artifact_digest)
);

CREATE TABLE IF NOT EXISTS budget_ledger (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  amount REAL NOT NULL,
  state TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL
);
"""


LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS legacy_imports (
  id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL,
  source_digest TEXT NOT NULL,
  imported_at INTEGER NOT NULL,
  record_count INTEGER NOT NULL,
  UNIQUE(source_path, source_digest)
);

CREATE TABLE IF NOT EXISTS legacy_records (
  id TEXT PRIMARY KEY,
  import_id TEXT NOT NULL REFERENCES legacy_imports(id),
  kind TEXT NOT NULL,
  legacy_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  readonly INTEGER NOT NULL DEFAULT 1 CHECK (readonly = 1),
  UNIQUE(import_id, kind, legacy_id)
);

CREATE TRIGGER IF NOT EXISTS legacy_records_no_update
BEFORE UPDATE ON legacy_records
BEGIN
  SELECT RAISE(ABORT, 'legacy records are read-only');
END;

CREATE TRIGGER IF NOT EXISTS legacy_records_no_delete
BEFORE DELETE ON legacy_records
BEGIN
  SELECT RAISE(ABORT, 'legacy records are read-only');
END;
"""
