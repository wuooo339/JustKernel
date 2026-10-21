const UNKNOWN = "—";

function formatMetric(value, unit = "") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return UNKNOWN;
  const number = Number(value);
  return `${Number.isFinite(number) ? number.toLocaleString() : UNKNOWN}${unit ? ` ${unit}` : ""}`;
}

function formatTimestamp(value) {
  if (value === null || value === undefined) return UNKNOWN;
  const number = Number(value);
  if (!Number.isFinite(number)) return UNKNOWN;
  return new Date(number).toISOString();
}

function formatDuration(start, end) {
  if (start === null || start === undefined || end === null || end === undefined) return UNKNOWN;
  const duration = Number(end) - Number(start);
  return Number.isFinite(duration) && duration >= 0 ? `${duration} ms` : UNKNOWN;
}

function display(value) {
  return value === null || value === undefined || value === "" ? UNKNOWN : String(value);
}

export { UNKNOWN, formatMetric, formatTimestamp, formatDuration, display };
