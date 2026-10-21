import assert from "node:assert/strict";
import test from "node:test";

import { replay } from "../../src/justkernel/web/state/reducer.js";
import {
  renderAgents,
  renderBoard,
  renderCandidates,
  renderCluster,
  renderClusterPage,
  renderHardware,
  renderRecords,
  renderReport,
} from "../../src/justkernel/web/views/index.js";

function event(seq, type, payload) {
  return {
    seq,
    id: `e-${seq}`,
    type,
    cluster_id: "c1",
    occurred_at: seq,
    payload: { cluster_id: "c1", ...payload },
  };
}

function baseEvents() {
  return [
    event(1, "cluster.started", { state: "RUNNING", phase: "OPTIMIZING" }),
    event(2, "agent.created", {
      agent_id: "mentor",
      role: "MENTOR",
      mentor_id: null,
      model_profile: "model",
      state: "IDLE",
    }),
    event(3, "agent.created", {
      agent_id: "tester",
      role: "TESTER",
      mentor_id: "mentor",
      model_profile: "model",
      state: "IDLE",
    }),
    event(4, "task.assigned", {
      task_id: "task-1",
      worker_id: "tester",
      kind: "TEST",
      state: "RUNNING",
    }),
    event(5, "candidate.committed", {
      candidate_id: "cand-1",
      parent_id: null,
      direction_id: "d1",
      created_at: 5,
    }),
    event(6, "test_record.created", {
      record_id: "record-1",
      candidate_id: "cand-1",
      kind: "TEST",
      outcome: "PASS",
      backend: "cann-simulation",
      coverage: "FULL",
      executed: true,
    }),
  ];
}

test("cluster and agents views expose accessible structure", () => {
  const state = replay(baseEvents());
  const clusterHtml = renderCluster(state, "c1");
  const agentsHtml = renderAgents(state, "c1");

  assert.match(clusterHtml, /aria-labelledby="cluster"/);
  assert.match(clusterHtml, /Phase/);
  assert.match(clusterHtml, /No best/);
  assert.match(agentsHtml, /<caption>Cluster agents and assigned tasks<\/caption>/);
  assert.match(agentsHtml, /data-agent-id="tester"/);
  assert.match(agentsHtml, /TESTER/);
});

test("pending best is visible but never labelled final best", () => {
  const pending = replay([
    ...baseEvents(),
    event(7, "best.nominated", {
      selection_id: "selection-1",
      candidate_id: "cand-1",
      created_at: 7,
    }),
  ]);
  const html = renderCandidates(pending, "c1");

  assert.match(html, /data-best="pending"/);
  assert.match(html, /PENDING — not final/);
  assert.doesNotMatch(html, /data-best="validated"/);
});

test("validated best is visible on cluster and candidate", () => {
  const validated = replay([
    ...baseEvents(),
    event(7, "best.nominated", {
      selection_id: "selection-1",
      candidate_id: "cand-1",
      created_at: 7,
    }),
    event(8, "best.validated", {
      selection_id: "selection-1",
      candidate_id: "cand-1",
    }),
  ]);
  const clusterHtml = renderCluster(validated, "c1");
  const candidateHtml = renderCandidates(validated, "c1");

  assert.match(clusterHtml, /data-best="validated"/);
  assert.match(candidateHtml, /data-best="validated"/);
  assert.match(candidateHtml, /BEST/);
});

test("failed candidates and missing metrics stay visible", () => {
  const failed = replay([
    ...baseEvents(),
    event(7, "candidate.committed", {
      candidate_id: "cand-2",
      parent_id: "cand-1",
      direction_id: "d1",
    }),
    event(8, "test_record.created", {
      record_id: "record-2",
      candidate_id: "cand-2",
      kind: "TEST",
      outcome: "FAIL",
      backend: "cann-simulation",
      coverage: "FULL",
      executed: true,
    }),
  ]);
  const html = renderCandidates(failed, "c1");
  const records = renderRecords(failed, "cand-2");

  assert.match(html, /data-candidate-id="cand-2"/);
  assert.match(html, /data-candidate-state="FAIL"/);
  assert.match(records, /FAIL/);
  assert.match(records, /cann-simulation/);
  assert.match(records, /coverage FULL/);
});

test("board content is escaped and read-only", () => {
  const state = replay([
    ...baseEvents(),
    event(7, "board.posted", {
      post_id: "post-1",
      board: "mentor",
      topic: "<script>alert(1)</script>",
      author_agent_id: "mentor",
      payload: { summary: "<img src=x onerror=alert(1)>" },
    }),
  ]);
  const html = renderBoard(state, "mentor");

  assert.match(html, /aria-readonly="true"/);
  assert.doesNotMatch(html, /<script>/);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;script&gt;/);
});

test("hardware, report and page composition render empty/unknown values safely", () => {
  const state = replay(baseEvents());
  state.hardware = {
    devices: [],
    queued: [],
    leased: [{ device_id: "npu:0", lease_id: "lease-1" }],
  };
  state.reports = {
    c1: { id: "report-1", best_candidate_id: null, decision: "failed", failures: [] },
  };

  assert.match(renderHardware(state), /npu:0/);
  assert.match(renderHardware(state), /LEASED/);
  assert.match(renderReport(state, "c1"), /Best: —/);
  assert.match(renderClusterPage(state, "c1"), /data-view="candidates"/);
});
