/* loadAsset(): the asset name from the URL plus the record and preview files.
   A missing file shows the visible #error box and resolves to null. */

const ASSET_KEY = "asset";

/** The raw ?asset= value, or "" when the page was opened without one. */
export function assetName() {
  return new URLSearchParams(window.location.search).get(ASSET_KEY) ?? "";
}

/** Show a message in the page's #error box (created when absent). */
export function showError(message) {
  let box = document.getElementById("error");
  if (!box) {
    box = document.createElement("div");
    box.id = "error";
    box.className = "error-box";
    box.setAttribute("role", "alert");
    document.body.prepend(box);
  }
  box.textContent = message;
  box.hidden = false;
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    return { ok: false, status: response.status, data: null };
  }
  try {
    return { ok: true, status: response.status, data: await response.json() };
  } catch {
    return { ok: true, status: response.status, data: null, corrupt: true };
  }
}

/**
 * Load `<name>.facet.json` and `<name>.preview.json` for ?asset=<name>.
 *
 * @returns {Promise<{name: string, record: object, preview: object} | null>}
 *   null when the name is absent or either file is missing/unreadable; in
 *   that case the #error box already says which one.
 */
export async function loadAsset() {
  const name = assetName().trim();
  if (!name) {
    showError("No asset in the URL: expected /viewer/index.html?asset=<name>");
    return null;
  }
  const base = `/asset/${encodeURIComponent(name)}`;
  const [record, preview] = await Promise.all([
    fetchJson(`${base}.facet.json`),
    fetchJson(`${base}.preview.json`),
  ]);
  const problems = [];
  if (!record.ok) problems.push(`missing ${name}.facet.json (HTTP ${record.status})`);
  else if (record.data === null) problems.push(`${name}.facet.json is not readable JSON`);
  if (!preview.ok) problems.push(`missing ${name}.preview.json (HTTP ${preview.status})`);
  else if (preview.data === null) problems.push(`${name}.preview.json is not readable JSON`);
  if (problems.length > 0) {
    showError(problems.join("\n"));
    return null;
  }
  return { name, record: record.data, preview: preview.data };
}

/** `/asset/<name>` for the record's asset, for links in the page. */
export function assetUrl(name) {
  return `/asset/${encodeURIComponent(name)}`;
}
