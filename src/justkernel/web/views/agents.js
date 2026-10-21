import { badge, escapeHtml, section } from "../components/html.js";
import { display } from "../format.js";
import { selectAgents } from "../state/selectors.js";

function renderAgents(state, clusterId) {
  const agents = selectAgents(state, clusterId);
  const rows = agents
    .map(
      (agent) => `<tr data-agent-id="${escapeHtml(agent.id)}">
        <td>${escapeHtml(agent.id)}</td>
        <td>${escapeHtml(display(agent.role))}</td>
        <td>${escapeHtml(display(agent.mentor_id))}</td>
        <td>${escapeHtml(display(agent.model_profile))}</td>
        <td>${badge(display(agent.state), display(agent.state))}</td>
        <td>${escapeHtml(display(agent.current_task_id))}</td>
      </tr>`,
    )
    .join("");
  return section(
    "agents",
    "Agents",
    `<table data-view="agents"><caption>Cluster agents and assigned tasks</caption>
      <thead><tr><th>ID</th><th>Role</th><th>Mentor</th><th>Model</th><th>State</th><th>Task</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="6">No agents.</td></tr>'}</tbody>
    </table>`,
  );
}

export { renderAgents };
