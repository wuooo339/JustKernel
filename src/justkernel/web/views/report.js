import { escapeHtml, section } from "../components/html.js";
import { display } from "../format.js";

function renderReport(state, clusterId) {
  const report = state.reports?.[clusterId] || null;
  if (!report) return section("report", "Report", "<p>No report.</p>");
  const failures = (report.failures || []).map((failure) => `<li>${escapeHtml(failure)}</li>`).join("");
  return section(
    "report",
    "Exploration report",
    `<div data-view="report"><p>Best: ${escapeHtml(display(report.best_candidate_id))}</p>
      <p>Decision: ${escapeHtml(display(report.decision))}</p>
      <h3>Failures</h3><ul>${failures || "<li>None.</li>"}</ul>
    </div>`,
  );
}

export { renderReport };
