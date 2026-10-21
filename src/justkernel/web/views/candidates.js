import { badge, escapeHtml, section } from "../components/html.js";
import { display, formatMetric } from "../format.js";
import { selectCandidateGraph, selectRecords } from "../state/selectors.js";

function candidateStatus(records) {
  if (records.length === 0) return "UNTESTED";
  if (records.some((record) => record.outcome === "FAIL")) return "FAIL";
  if (records.some((record) => record.outcome === "PASS")) return "PASS";
  return records[0].outcome || "UNKNOWN";
}

function renderCandidates(state, clusterId) {
  const graph = selectCandidateGraph(state, clusterId);
  const best = state.bestSelections
    ? Object.values(state.bestSelections).find(
        (selection) => selection.cluster_id === clusterId && selection.state === "VALIDATED",
      )
    : null;
  const pending = state.bestSelections
    ? Object.values(state.bestSelections).find(
        (selection) => selection.cluster_id === clusterId && selection.state === "PENDING",
      )
    : null;
  const cards = graph.nodes
    .map((candidate) => {
      const records = selectRecords(state, candidate.id);
      const status = candidateStatus(records);
      const bestMark =
        best?.candidate_id === candidate.id
          ? badge("BEST", "validated", 'data-best="validated"')
          : pending?.candidate_id === candidate.id
            ? badge("PENDING — not final", "pending", 'data-best="pending"')
            : "";
      return `<article data-candidate-id="${escapeHtml(candidate.id)}" data-candidate-state="${escapeHtml(status)}">
        <h3>${escapeHtml(candidate.id)} ${bestMark}</h3>
        <p>parent ${escapeHtml(display(candidate.parent_id))}</p>
        <p>${badge(status, status)}</p>
        <p>records ${formatMetric(records.length)}</p>
      </article>`;
    })
    .join("");
  const edges = graph.edges
    .map((edge) => `<li>${escapeHtml(edge.from)} → ${escapeHtml(edge.to)}</li>`)
    .join("");
  return section(
    "candidates",
    "Candidates",
    `<div data-view="candidates">${cards || "<p>No candidates.</p>"}
      <h3>Version edges</h3><ul>${edges || "<li>No edges.</li>"}</ul>
    </div>`,
  );
}

export { renderCandidates };
