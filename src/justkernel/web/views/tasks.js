import { badge, escapeHtml, section } from "../components/html.js";
import { display } from "../format.js";
import { selectTasks } from "../state/selectors.js";

function renderTasks(state, clusterId) {
  const tasks = selectTasks(state, clusterId);
  const items = tasks
    .map(
      (task) => `<li data-task-id="${escapeHtml(task.id)}">
        <strong>${escapeHtml(display(task.kind))}</strong>
        ${badge(display(task.state), display(task.state))}
        <span>worker ${escapeHtml(display(task.worker_id))}</span>
        <span>candidate ${escapeHtml(display(task.candidate_id))}</span>
      </li>`,
    )
    .join("");
  return section("tasks", "Tasks", `<ol data-view="tasks">${items || "<li>No tasks.</li>"}</ol>`);
}

export { renderTasks };
