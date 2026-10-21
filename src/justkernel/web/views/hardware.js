import { badge, escapeHtml, section } from "../components/html.js";
import { display } from "../format.js";

function renderHardware(state) {
  const hardware = state.hardware || { devices: [], queued: [], leased: [] };
  const queued = (hardware.queued || [])
    .map((item) => `<li>${escapeHtml(display(item.device_id))} ${escapeHtml(display(item.job_id))}</li>`)
    .join("");
  const leased = (hardware.leased || [])
    .map((item) => `<li>${escapeHtml(display(item.device_id))} ${badge("LEASED", "leased")} ${escapeHtml(display(item.lease_id))}</li>`)
    .join("");
  return section(
    "hardware",
    "Hardware queue",
    `<div data-view="hardware"><h3>Queued</h3><ul>${queued || "<li>None.</li>"}</ul>
      <h3>Leased</h3><ul>${leased || "<li>None.</li>"}</ul>
    </div>`,
  );
}

export { renderHardware };
