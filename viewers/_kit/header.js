/* renderHeader(el, record): the header every viewer shares, one line deep —
   `facetMedia · capability · asset` in Sometype Mono on the left, the
   verification verdict on the right, a thin rule below — then the metrics
   against their thresholds, the licences with a visible non-commercial badge,
   and the provenance collapsed in a <details>.

   Señal marks only what is verified: the verdict when it passed, and a metric
   value that passed its threshold. A failure is a word with a ✗ in Hueso
   tenue, never a red. */

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

/** `facetMedia · <capability id> · <asset name>`, the brand in Hueso. */
function markOf(record) {
  const mark = document.createElement("h1");
  mark.className = "mark";
  const brand = document.createElement("span");
  brand.className = "brand";
  brand.textContent = "facetMedia";
  const capability = provenanceOf(record).capability ?? "unknown capability";
  const name = record.name ?? "asset";
  mark.append(brand, ` · ${text(capability)} · ${text(name)}`);
  return mark;
}

/** `✓ passed` in Señal, everything else `✗ <status>` in Hueso tenue. */
function verdictOf(status) {
  const verdict = document.createElement("span");
  verdict.className = `verdict ${status}`;
  verdict.textContent = status === "passed" ? "✓ passed" : `✗ ${status}`;
  return verdict;
}

function headOf(record) {
  const head = document.createElement("div");
  head.className = "head";
  head.append(markOf(record), verdictOf(statusOf(record)));
  return head;
}

function ruleOf() {
  const rule = document.createElement("hr");
  rule.className = "rule";
  return rule;
}

function metricRow(key, record, metrics, thresholds) {
  const row = document.createElement("tr");
  const name = document.createElement("th");
  name.scope = "row";
  name.textContent = key;
  const measured = document.createElement("td");
  measured.className = "num";
  measured.textContent = text(metrics[key]);
  const threshold = document.createElement("td");
  threshold.className = "num";
  threshold.textContent = text(thresholds[key]);
  // Only a metric with a threshold, inside a passing verification, is verified.
  const verified = statusOf(record) === "passed"
    && thresholds[key] !== undefined
    && metrics[key] !== undefined;
  if (verified) measured.classList.add("verified");
  row.append(name, measured, threshold);
  return row;
}

function metricsBlock(record) {
  const block = document.createElement("div");
  block.className = "verify";
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
  for (const key of keys) body.append(metricRow(key, record, metrics, thresholds));
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
  el.append(
    headOf(record),
    ruleOf(),
    metricsBlock(record),
    licenceBlock(record),
    provenanceBlock(record),
  );
}
