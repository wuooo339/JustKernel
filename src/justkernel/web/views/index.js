import { renderAgents } from "./agents.js";
import { renderBoard } from "./board.js";
import { renderCandidates } from "./candidates.js";
import { renderCluster } from "./cluster.js";
import { renderHardware } from "./hardware.js";
import { renderRecords } from "./records.js";
import { renderReport } from "./report.js";
import { renderTasks } from "./tasks.js";

function renderClusterPage(state, clusterId) {
  return [
    renderCluster(state, clusterId),
    renderAgents(state, clusterId),
    renderBoard(state, "mentor"),
    renderTasks(state, clusterId),
    renderCandidates(state, clusterId),
    renderHardware(state),
    renderReport(state, clusterId),
  ].join("\n");
}

export {
  renderClusterPage,
  renderCluster,
  renderAgents,
  renderBoard,
  renderTasks,
  renderCandidates,
  renderRecords,
  renderHardware,
  renderReport,
};
