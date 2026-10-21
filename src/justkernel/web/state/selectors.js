function values(map) {
  return Object.values(map || {});
}

function selectCluster(state, clusterId) {
  return state.clusters[clusterId] || null;
}

function selectAgents(state, clusterId) {
  return values(state.agents)
    .filter((agent) => agent.cluster_id === clusterId)
    .sort(
      (a, b) =>
        String(a.role).localeCompare(String(b.role)) ||
        String(a.id).localeCompare(String(b.id)),
    );
}

function selectTasks(state, clusterId) {
  return values(state.tasks)
    .filter((task) => task.cluster_id === clusterId)
    .sort(
      (a, b) =>
        Number(a.created_at || 0) - Number(b.created_at || 0) ||
        String(a.id).localeCompare(String(b.id)),
    );
}

function selectCandidateGraph(state, clusterId) {
  const nodes = values(state.candidates)
    .filter((candidate) => candidate.cluster_id === clusterId)
    .sort((a, b) => String(a.id).localeCompare(String(b.id)));
  const ids = new Set(nodes.map((node) => node.id));
  const edges = nodes
    .filter((node) => node.parent_id && ids.has(node.parent_id))
    .map((node) => ({ from: node.parent_id, to: node.id }));
  return { nodes, edges };
}

function selectRecords(state, candidateId) {
  return values(state.records)
    .filter((record) => record.candidate_id === candidateId)
    .sort((a, b) => Number(b.created_at || 0) - Number(a.created_at || 0));
}

function selectBest(state, clusterId) {
  return (
    values(state.bestSelections)
      .filter((selection) => selection.cluster_id === clusterId && selection.state === "VALIDATED")
      .sort((a, b) => Number(b.created_at || 0) - Number(a.created_at || 0))[0] || null
  );
}

function selectPendingBest(state, clusterId) {
  return (
    values(state.bestSelections)
      .filter((selection) => selection.cluster_id === clusterId && selection.state === "PENDING")
      .sort((a, b) => Number(b.created_at || 0) - Number(a.created_at || 0))[0] || null
  );
}

function selectBoard(state, board) {
  return state.board
    .filter((post) => !board || post.board === board)
    .sort((a, b) => a.seq - b.seq);
}

function selectClusterSummary(state, clusterId) {
  const cluster = selectCluster(state, clusterId);
  if (!cluster) return null;
  return {
    cluster,
    agents: selectAgents(state, clusterId),
    tasks: selectTasks(state, clusterId),
    graph: selectCandidateGraph(state, clusterId),
    best: selectBest(state, clusterId),
    pendingBest: selectPendingBest(state, clusterId),
  };
}

export {
  selectCluster,
  selectAgents,
  selectTasks,
  selectCandidateGraph,
  selectRecords,
  selectBest,
  selectPendingBest,
  selectBoard,
  selectClusterSummary,
};
