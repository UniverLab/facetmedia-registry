/* Generic viewer: the shared header, the preview summary, the fields table
   and a link to the asset itself. */

import { renderHeader } from "/kit/header.js";
import { assetUrl, loadAsset } from "/kit/load.js";

function scalar(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "number") return String(Math.round(value * 1000) / 1000);
  return String(value);
}

function fillFields(table, fields) {
  const body = table.querySelector("tbody");
  for (const [key, value] of Object.entries(fields ?? {})) {
    const row = document.createElement("tr");
    const name = document.createElement("th");
    name.scope = "row";
    name.textContent = key;
    const cell = document.createElement("td");
    cell.className = "num";
    cell.textContent = scalar(value);
    row.append(name, cell);
    body.append(row);
  }
}

const loaded = await loadAsset();
if (loaded) {
  const { name, record, preview } = loaded;
  renderHeader(document.getElementById("header"), record);
  document.getElementById("summary").textContent = preview.summary ?? "";
  fillFields(document.getElementById("fields"), preview.fields);
  const link = document.getElementById("asset-link");
  link.href = assetUrl(name);
  link.textContent = `open ${name}`;
}
