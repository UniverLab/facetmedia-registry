/* renderHeader(el, record): the header every viewer shares — name and kind,
   verification (status, metrics against thresholds), licences with a visible
   non-commercial badge, and provenance collapsed in a <details>. */

function text(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return String(Math.round(value * 1000) / 1000);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function provenanceOf(record) {
  const source = record.provenance ?? record;
  return {
    facet: source.facet,
    capability: source.capability,
    package: source.package ?? {},
    registry: source.registry ?? record.registry ?? {},
    models: source.models ?? [],
    params: source.params ?? {},
  };
}

function statusOf(record) {
  const verification = record.verification;
  if (!verification || typeof verification !== "object") return "skipped";
  const status = verification.status;
  return ["passed", "failed", "skipped"].includes(status) ? status : "skipped";
}

function verificationBlock(record) {
  const block = document.createElement("p");
  block.className = "verify";
  const status = statusOf(record);
  const pill = document.createElement("span");
  pill.className = `pill ${status}`;
  pill.textContent = `verification ${status}`;
  block.append(pill);
  const verification = record.verification;
  if (!verification || typeof verification !== "object") return block;
  const metrics = verification.metrics ?? {};
  const thresholds = verification.thresholds ?? {};
  const keys = [...new Set([...Object.keys(metrics), ...Object.keys(thresholds)])];
  if (keys.length === 0) return block;
  const table = document.createElement("table");
  table.innerHTML = "<thead><tr><th>metric</th><th class='num'>measured</th>"
    + "<th class='num'>threshold</th></tr></thead>";
  const body = document.createElement("tbody");
  for (const key of keys) {
    const row = document.createElement("tr");
    const cells = [key, text(metrics[key]), text(thresholds[key])];
    cells.forEach((value, index) => {
      const cell = document.createElement(index === 0 ? "th" : "td");
      if (index > 0) cell.className = "num";
      cell.textContent = value;
      if (index === 0) cell.scope = "row";
      row.append(cell);
    });
    body.append(row);
  }
  table.append(body);
  block.append(table);
  return block;
}

function licenceBlock(record) {
  const block = document.createElement("p");
  block.className = "licences";
  const license = record.license ?? {};
  const entries = [...(license.tools ?? []), ...(license.models ?? [])];
  const names = entries
    .map((entry) => entry.spdx ?? entry.name ?? null)
    .filter((entry) => entry !== null);
  const label = document.createElement("span");
  label.className = "muted";
  label.textContent = names.length > 0 ? `licence: ${names.join(", ")}` : "licence: none declared";
  block.append(label);
  const restricted =
    license.commercial_use === false
    || (license.models ?? []).some((model) => model.commercial_use === false);
  if (restricted) {
    const badge = document.createElement("span");
    badge.className = "badge-nc";
    badge.textContent = "non-commercial";
    badge.title = "This asset may not be used commercially (license.commercial_use is false).";
    block.append(badge);
  }
  return block;
}

function provenanceBlock(record) {
  const prov = provenanceOf(record);
  const details = document.createElement("details");
  details.className = "provenance";
  const summary = document.createElement("summary");
  summary.textContent = "provenance";
  const list = document.createElement("dl");
  list.className = "kv";
  const pkg = prov.package ?? {};
  const rows = [
    ["capability", prov.capability],
    ["package", pkg.name ? `${pkg.name} ${pkg.version ?? ""}`.trim() : text(pkg)],
    ["registry", prov.registry.commit ?? text(prov.registry)],
    ["models", (prov.models ?? []).map((model) => model.id ?? text(model)).join(", ")],
    ["params", text(prov.params)],
  ];
  for (const [term, value] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value ? text(value) : "—";
    list.append(dt, dd);
  }
  details.append(summary, list);
  return details;
}

/** Render the shared header into `el` from the asset's record. */
export function renderHeader(el, record) {
  el.replaceChildren();
  const head = document.createElement("div");
  head.className = "asset-head";
  const name = document.createElement("h1");
  name.textContent = record.name ?? "asset";
  const kind = document.createElement("span");
  kind.className = "kind-chip";
  kind.textContent = record.kind ?? "unknown kind";
  head.append(name, kind);
  el.append(head, verificationBlock(record), licenceBlock(record), provenanceBlock(record));
}
