import assert from "node:assert/strict";
import test from "node:test";

import { initialState, reduce, replay } from "../../src/justkernel/web/state/reducer.js";

function event(seq, type, payload, id = `e-${seq}`) {
  return {
    seq,
    id,
    type,
    cluster_id: payload.cluster_id || "cluster-1",
    occurred_at: seq,
    payload,
  };
}

test("applies contiguous events and ignores duplicates", () => {
  const first = event(1, "cluster.started", {
    cluster_id: "c1",
    state: "RUNNING",
    phase: "BOOTSTRAPPING",
  });
  const second = event(2, "agent.created", {
    cluster_id: "c1",
    agent_id: "a1",
    role: "MENTOR",
    state: "IDLE",
  });
  let state = reduce(initialState, first);
  state = reduce(state, second);

  assert.equal(state.clusters.c1.state, "RUNNING");
  assert.equal(state.agents.a1.role, "MENTOR");
  assert.equal(state.window.lastSeq, 2);
  assert.equal(reduce(state, second), state);
});

test("buffers out-of-order events until the missing sequence arrives", () => {
  const second = event(2, "agent.created", {
    cluster_id: "c1",
    agent_id: "a1",
    role: "MENTOR",
    state: "IDLE",
  });
  let state = reduce(initialState, second);

  assert.equal(state.window.lastSeq, 0);
  assert.equal(state.agents.a1, undefined);
  assert.ok(state.window.pending[2]);

  state = reduce(state, event(1, "cluster.started", { cluster_id: "c1" }));
  assert.equal(state.window.lastSeq, 2);
  assert.equal(state.clusters.c1.state, "RUNNING");
  assert.equal(state.agents.a1.state, "IDLE");
  assert.deepEqual(state.window.pending, {});
});

test("unknown events advance the cursor without mutating entities", () => {
  const state = reduce(initialState, event(1, "unknown.event", { value: 1 }));

  assert.equal(state.window.lastSeq, 1);
  assert.deepEqual(state.clusters, {});
  assert.deepEqual(state.agents, {});
});

test("live reduction and sorted replay converge", () => {
  const events = [
    event(3, "candidate.committed", {
      cluster_id: "c1",
      candidate_id: "cand-1",
      parent_id: null,
      direction_id: "d1",
    }),
    event(1, "cluster.started", { cluster_id: "c1" }),
    event(2, "agent.created", {
      cluster_id: "c1",
      agent_id: "a1",
      role: "MENTOR",
      state: "IDLE",
    }),
  ];
  const live = events.reduce(reduce, initialState);
  const fromReplay = replay(events);

  assert.deepEqual(live, fromReplay);
  assert.equal(live.window.lastSeq, 3);
  assert.equal(live.candidates["cand-1"].direction_id, "d1");
});

test("board and validated best are reduced once", () => {
  const state = replay([
    event(1, "cluster.started", { cluster_id: "c1" }),
    event(2, "candidate.committed", {
      cluster_id: "c1",
      candidate_id: "cand-1",
      direction_id: "d1",
    }),
    event(3, "best.nominated", {
      cluster_id: "c1",
      selection_id: "s1",
      candidate_id: "cand-1",
      state: "PENDING",
    }),
    event(4, "best.validated", {
      cluster_id: "c1",
      selection_id: "s1",
      candidate_id: "cand-1",
    }),
    event(5, "board.posted", {
      cluster_id: "c1",
      post_id: "p1",
      board: "mentor",
      topic: "direction",
      author_agent_id: "a1",
      payload: { summary: "baseline" },
    }),
  ]);

  assert.equal(state.bestSelections.s1.state, "VALIDATED");
  assert.equal(state.clusters.c1.best_candidate_id, "cand-1");
  assert.equal(state.board.length, 1);
  assert.equal(state.board[0].payload.summary, "baseline");
});
