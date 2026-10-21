const initialState = Object.freeze({
  clusters: {},
  agents: {},
  tasks: {},
  candidates: {},
  records: {},
  bestSelections: {},
  board: [],
  messages: [],
  window: Object.freeze({ lastSeq: 0, pending: {}, seen: {} }),
  stream: Object.freeze({ mode: "live", status: "idle" }),
});

const CLUSTER_STATE = {
  "cluster.started": ["RUNNING", "BOOTSTRAPPING"],
  "cluster.converging": ["CONVERGING", "FINALIZING"],
  "cluster.completed": ["COMPLETED", "FINALIZING"],
  "cluster.stopped": ["STOPPED", null],
  "cluster.resumed": ["RUNNING", null],
};

const AGENT_STATE = {
  "agent.idle": "IDLE",
  "agent.running": "RUNNING",
  "agent.failed": "FAILED",
  "agent.closed": "CLOSED",
};

const TASK_STATE = {
  "task.running": "RUNNING",
  "task.succeeded": "SUCCEEDED",
  "task.failed": "FAILED",
  "task.cancelled": "CANCELLED",
  "task.interrupted": "INTERRUPTED",
};

function merge(existing, updates) {
  const next = { ...(existing || {}) };
  for (const [key, value] of Object.entries(updates || {})) {
    if (value !== undefined) next[key] = value;
  }
  return next;
}

function eventClusterId(event) {
  return event.payload?.cluster_id || event.cluster_id;
}

function applyCluster(state, event, payload) {
  const id = payload.cluster_id || event.cluster_id;
  if (!id) return state;
  const cluster = state.clusters[id] || { id };
  const transition = CLUSTER_STATE[event.type];
  const next = merge(cluster, {
    ...payload,
    id,
    state: transition ? transition[0] : payload.state || cluster.state,
    phase: transition && transition[1] ? transition[1] : payload.phase || cluster.phase,
    closed_at: payload.closed_at !== undefined ? payload.closed_at : cluster.closed_at,
  });
  return { ...state, clusters: { ...state.clusters, [id]: next } };
}

function applyAgent(state, event, payload) {
  const id = payload.agent_id || event.aggregate_id;
  if (!id) return state;
  const current = state.agents[id] || { id };
  const agentState = AGENT_STATE[event.type] || payload.state || current.state;
  const next = merge(current, {
    ...payload,
    id,
    state: agentState,
    cluster_id: payload.cluster_id || current.cluster_id || eventClusterId(event),
    mentor_id: payload.mentor_id !== undefined ? payload.mentor_id : current.mentor_id,
  });
  return { ...state, agents: { ...state.agents, [id]: next } };
}

function applyTask(state, event, payload) {
  const id = payload.task_id || event.aggregate_id;
  if (!id) return state;
  const current = state.tasks[id] || { id };
  const next = merge(current, {
    ...payload,
    id,
    state: TASK_STATE[event.type] || payload.state || current.state,
    cluster_id: payload.cluster_id || current.cluster_id || eventClusterId(event),
  });
  return { ...state, tasks: { ...state.tasks, [id]: next } };
}

function applyCandidate(state, event, payload) {
  const id = payload.candidate_id || event.aggregate_id;
  if (!id) return state;
  const current = state.candidates[id] || { id };
  const update = { ...payload, id };
  if (event.type === "candidate.evaluation.updated") {
    update.evaluation = payload.evaluation || payload;
  } else if (!current.evaluation) {
    update.evaluation = { status: "UNTESTED" };
  }
  const next = merge(current, update);
  return { ...state, candidates: { ...state.candidates, [id]: next } };
}

function applyRecord(state, event, payload) {
  const id = payload.record_id || payload.id || event.aggregate_id;
  if (!id) return state;
  const record = merge(state.records[id] || { id }, { ...payload, id });
  return { ...state, records: { ...state.records, [id]: record } };
}

function applyBest(state, event, payload) {
  const id = payload.selection_id || payload.id || event.aggregate_id;
  if (!id) return state;
  const status = {
    "best.nominated": "PENDING",
    "best.validated": "VALIDATED",
    "best.failed": "FAILED",
  }[event.type];
  const selection = merge(state.bestSelections[id] || { id }, {
    ...payload,
    id,
    state: status || payload.state,
  });
  let clusters = state.clusters;
  if (status === "VALIDATED" && payload.candidate_id && payload.cluster_id) {
    const cluster = state.clusters[payload.cluster_id];
    if (cluster) {
      clusters = {
        ...state.clusters,
        [payload.cluster_id]: { ...cluster, best_candidate_id: payload.candidate_id },
      };
    }
  }
  return {
    ...state,
    clusters,
    bestSelections: { ...state.bestSelections, [id]: selection },
  };
}

function applyOne(state, event) {
  const payload = event.payload || {};
  if (event.type.startsWith("cluster.")) return applyCluster(state, event, payload);
  if (event.type === "baseline.established") {
    const id = payload.cluster_id || event.cluster_id;
    const cluster = state.clusters[id];
    if (!cluster) return state;
    return {
      ...state,
      clusters: {
        ...state.clusters,
        [id]: {
          ...cluster,
          baseline_candidate_id: payload.candidate_id || cluster.baseline_candidate_id,
        },
      },
    };
  }
  if (event.type.startsWith("agent.")) return applyAgent(state, event, payload);
  if (event.type.startsWith("task.")) return applyTask(state, event, payload);
  if (event.type.startsWith("candidate.")) return applyCandidate(state, event, payload);
  if (event.type.startsWith("test_record.") || event.type === "record.created") {
    return applyRecord(state, event, payload);
  }
  if (event.type.startsWith("best.")) return applyBest(state, event, payload);
  if (event.type === "board.posted") {
    const post = {
      id: payload.post_id || event.aggregate_id,
      seq: event.seq,
      board: payload.board,
      topic: payload.topic,
      author_agent_id: payload.author_agent_id,
      payload: payload.payload || {},
      occurred_at: event.occurred_at,
    };
    if (!post.id || state.board.some((item) => item.id === post.id)) return state;
    return { ...state, board: [...state.board, post] };
  }
  if (event.type.startsWith("message.")) {
    return {
      ...state,
      messages: [
        ...state.messages,
        { id: event.id, seq: event.seq, type: event.type, occurred_at: event.occurred_at, payload },
      ],
    };
  }
  return state;
}

function reduce(state = initialState, event) {
  if (!event || typeof event.seq !== "number" || !event.id || event.seq < 0) return state;
  if (state.window.lastSeq >= event.seq || state.window.seen[event.id]) return state;
  const pending = { ...state.window.pending, [event.seq]: event };
  const seen = { ...state.window.seen, [event.id]: event.seq };
  let next = state;
  let lastSeq = state.window.lastSeq;
  while (pending[lastSeq + 1]) {
    next = applyOne(next, pending[lastSeq + 1]);
    delete pending[lastSeq + 1];
    lastSeq += 1;
  }
  return { ...next, window: { lastSeq, pending, seen } };
}

function replay(events, state = initialState) {
  return [...events].sort((a, b) => a.seq - b.seq).reduce(reduce, state);
}

function setStream(state, status, mode = state.stream.mode) {
  return { ...state, stream: { mode, status } };
}

export { initialState, reduce, replay, setStream };
