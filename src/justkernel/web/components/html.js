function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function badge(label, state, extra = "") {
  return `<span class="badge badge-${escapeHtml(state)}" data-state="${escapeHtml(state)}" ${extra}>${escapeHtml(label)}</span>`;
}

function empty(message) {
  return `<p class="empty" role="status">${escapeHtml(message)}</p>`;
}

function section(id, title, content, extra = "") {
  return `<section aria-labelledby="${escapeHtml(id)}" ${extra}><h2 id="${escapeHtml(id)}">${escapeHtml(title)}</h2>${content}</section>`;
}

export { escapeHtml, badge, empty, section };
