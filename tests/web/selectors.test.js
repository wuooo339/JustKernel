import assert from "node:assert/strict";
import test from "node:test";

import { replay } from "../../src/justkernel/web/state/reducer.js";
import {
  selectAgents,
  selectBest,
  selectBoard,
  selectCandidateGraph,
  selectClusterSummary,
  selectPendingBest,
  selectRecords,
  selectTasks,
} from "../../src/justkernel/web/state/selectors.js";

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

function state() {
  return replay([
    event(1, "cluster.started", { state: "RUNNING", phase: "OPTIMIZING" }),
    event(2, "agent.created", {
      agent_id: "mentor",
      role: "MENTOR",
      mentor_id: null,
      state: "IDLE",
    }),
    event(3, "agent.created", {
      agent_id: "optimizer",
      role: "OPTIMIZER",
      mentor_id: "mentor",
      state: "RUNNING",
    }),
    event(4, "task.assigned", {
      task_id: "task-1",
      mentor_id: "mentor",
      worker_id: "optimizer",
      state: "RUNNING",
      created_at: 4,
    }),
    event(5, "candidate.committed", {
      candidate_id: "cand-2",
      parent_id: "cand-1",
      direction_id: "d1",
      created_at: 5,
    }),
    event(6, "candidate.committed", {
      candidate_id: "cand-1",
      parent_id: null,
      direction_id: "d1",
      created_at: 3,
    }),
    event(7, "test_record.created", {
      record_id: "record-1",
      candidate_id: "cand-2",
      outcome: "PASS",
      created_at: 7,
    }),
    event(8, "best.nominated", {
      selection_id: "selection-1",
      candidate_id: "cand-2",
      created_at: 8,
    }),
    event(9, "board.posted", {
      post_id: "post-2",
      board: "mentor",
      topic: "summary",
      author_agent_id: "mentor",
      payload: { summary: "second" },
    }),
    event(10, "board.posted", {
      post_id: "post-1",
      board: "mentor",
      topic: "summary",
      author_agent_id: "mentor",
      payload: { summary: "first" },
    }),
  ]);
}

test("selects cluster agents and tasks", () => {
  const current = state();

  assert.deepEqual(
    selectAgents(current, "c1").map((agent) => agent.id),
    ["mentor", "optimizer"],
  );
  assert.deepEqual(
    selectTasks(current, "c1").map((task) => task.id),
    ["task-1"],
  );
});

test("candidate graph connects parent and child", () => {
  const graph = selectCandidateGraph(state(), "c1");

  assert.deepEqual(
    graph.nodes.map((node) => node.id),
    ["cand-1", "cand-2"],
  );
  assert.deepEqual(graph.edges, [{ from: "cand-1", to: "cand-2" }]);
  assert.deepEqual(
    selectRecords(state(), "cand-2").map((record) => record.id),
    ["record-1"],
  );
});

test("pending best is not final best", () => {
  const current = state();

  assert.equal(selectBest(current, "c1"), null);
  assert.equal(selectPendingBest(current, "c1").id, "selection-1");
});

test("board is ordered by sequence and summary combines views", () => {
  const current = state();

  assert.deepEqual(
    selectBoard(current, "mentor").map((post) => post.seq),
    [9, 10],
  );
  assert.equal(selectClusterSummary(current, "c1").cluster.state, "RUNNING");
  assert.equal(selectClusterSummary(current, "missing"), null);
});
