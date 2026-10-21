import { escapeHtml, section } from "../components/html.js";
import { display } from "../format.js";

function renderBoard(state, board = "mentor") {
  const posts = state.board.filter((post) => post.board === board);
  const list = posts
    .map(
      (post) => `<article data-post-id="${escapeHtml(post.id)}" data-board="${escapeHtml(post.board)}">
        <h3>${escapeHtml(display(post.topic))}</h3>
        <p>${escapeHtml(display(post.author_agent_id))}</p>
        <pre>${escapeHtml(JSON.stringify(post.payload, null, 2))}</pre>
      </article>`,
    )
    .join("");
  return section(
    `board-${board}`,
    `${board === "mentor" ? "Mentor" : "Consultant"} board (read-only)`,
    `<div data-view="board" aria-readonly="true">${list || "<p>No board posts.</p>"}</div>`,
  );
}

export { renderBoard };
