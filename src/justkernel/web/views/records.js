import { badge, escapeHtml, section } from "../components/html.js";
import { display } from "../format.js";
import { selectRecords } from "../state/selectors.js";

function renderRecords(state, candidateId) {
  const records = selectRecords(state, candidateId);
  const items = records
    .map(
      (record) => `<li data-record-id="${escapeHtml(record.id)}" data-backend="${escapeHtml(display(record.backend))}">
        <strong>${escapeHtml(display(record.kind || "TEST"))}</strong>
        ${badge(display(record.outcome), display(record.outcome))}
        <span>backend ${escapeHtml(display(record.backend))}</span>
        <span>coverage ${escapeHtml(display(record.coverage))}</span>
        <span>executed ${escapeHtml(display(record.executed))}</span>
      </li>`,
    )
    .join("");
  return section(
    `records-${candidateId}`,
    "Test records",
    `<ul data-view="records" data-candidate-id="${escapeHtml(candidateId)}">${items || "<li>No records.</li>"}</ul>`,
  );
}

export { renderRecords };
