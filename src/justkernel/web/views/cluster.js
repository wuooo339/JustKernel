import { badge, escapeHtml, section } from "../components/html.js";
import { display, formatMetric } from "../format.js";
import { selectAgents, selectClusterSummary } from "../state/selectors.js";

function renderCluster(state, clusterId) {
  const summary = selectClusterSummary(state, clusterId);
  if (!summary) return section("cluster", "Cluster", "<p>Cluster not loaded.</p>");
  const { cluster } = summary;
  const active = selectAgents(state, clusterId).filter((agent) => agent.state !== "CLOSED").length;
  const best =
    summary.best !== null
      ? badge(`BEST ${summary.best.candidate_id}`, "validated", 'data-best="validated"')
      : summary.pendingBest !== null
        ? badge("PENDING — not final", "pending", 'data-best="pending"')
        : badge("No best", "none");
  return section(
    "cluster",
    `Cluster ${cluster.id}`,
    `<dl>
      <dt>State</dt><dd>${badge(display(cluster.state), display(cluster.state))}</dd>
      <dt>Phase</dt><dd>${escapeHtml(display(cluster.phase))}</dd>
      <dt>Active agents</dt><dd>${formatMetric(active)}</dd>
      <dt>Baseline</dt><dd>${escapeHtml(display(cluster.baseline_candidate_id))}</dd>
      <dt>Best</dt><dd>${best}</dd>
    </dl>`,
    'data-view="cluster"',
  );
}

export { renderCluster };
