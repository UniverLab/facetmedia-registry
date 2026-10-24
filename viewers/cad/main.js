/* CAD viewer: the preview's views (click to enlarge), the solid's
   measurements and holes, and the drawing's units, layers and audit.
   A preview with only one of the two sections hides the other. */

import { renderHeader } from "/kit/header.js";
import { assetUrl, loadAsset } from "/kit/load.js";

const loaded = await loadAsset();
if (loaded) main(loaded);

function main({ name, record, preview }) {
  renderHeader(document.getElementById("header"), record);
  document.getElementById("summary").textContent = preview.summary ?? "";
  const link = document.getElementById("asset-link");
  link.href = assetUrl(name);
  link.textContent = `open ${name}`;
  renderViews(preview.views ?? []);
  renderSolid(preview.solid);
  renderDrawing(preview.drawing);
}

function renderViews(views) {
  if (views.length === 0) return;
  const section = document.getElementById("views");
  section.hidden = false;
  const container = section.querySelector(".views");
  const dialog = document.getElementById("zoom");
  const zoomImg = document.getElementById("zoom-img");
  document.getElementById("zoom-close").addEventListener("click", () => dialog.close());
  for (const view of views) {
    const figure = document.createElement("figure");
    const image = document.createElement("img");
    image.src = assetUrl(view.file);
    image.alt = `${view.label ?? view.file} view`;
    const caption = document.createElement("figcaption");
    caption.textContent = view.label ?? view.file;
    image.addEventListener("click", () => {
      zoomImg.src = image.src;
      zoomImg.alt = image.alt;
      dialog.showModal();
    });
    figure.append(image, caption);
    container.append(figure);
  }
}

function kvRow(list, term, value) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.className = "num";
  dd.textContent = value;
  list.append(dt, dd);
}

function vector(values, suffix) {
  if (!Array.isArray(values)) return "—";
  return `${values.join(" × ")}${suffix ?? ""}`;
}

function renderSolid(solid) {
  if (!solid) return;
  const section = document.getElementById("solid");
  section.hidden = false;
  const list = document.getElementById("solid-kv");
  const pill = document.createElement("span");
  pill.className = `pill ${solid.valid ? "passed" : "failed"}`;
  pill.textContent = solid.valid ? "valid solid" : "invalid solid";
  const dt = document.createElement("dt");
  dt.textContent = "validity";
  const dd = document.createElement("dd");
  dd.append(pill);
  list.append(dt, dd);
  kvRow(list, "volume", `${solid.volume_mm3 ?? "—"} mm³`);
  kvRow(list, "bounding box", vector(solid.bbox_mm, " mm"));
  kvRow(list, "faces", String(solid.faces ?? "—"));
  kvRow(list, "solids", String(solid.solids ?? "—"));
  const body = document.querySelector("#holes tbody");
  (solid.holes ?? []).forEach((hole, index) => {
    const row = document.createElement("tr");
    const cells = [
      `#${index + 1}`,
      vector(hole.center_mm),
      String(hole.diameter_mm ?? "—"),
      vector(hole.axis),
    ];
    cells.forEach((value, cellIndex) => {
      const cell = document.createElement(cellIndex === 0 ? "th" : "td");
      if (cellIndex > 0) cell.className = "num";
      cell.textContent = value;
      if (cellIndex === 0) cell.scope = "row";
      row.append(cell);
    });
    body.append(row);
  });
  if ((solid.holes ?? []).length === 0) document.getElementById("holes").hidden = true;
}

function renderDrawing(drawing) {
  if (!drawing) return;
  const section = document.getElementById("drawing");
  section.hidden = false;
  const list = document.getElementById("drawing-kv");
  kvRow(list, "units", drawing.units ?? "—");
  kvRow(list, "entities", String(drawing.entities ?? "—"));
  const body = document.querySelector("#layers tbody");
  for (const layer of drawing.layers ?? []) {
    const row = document.createElement("tr");
    const name = document.createElement("th");
    name.scope = "row";
    name.textContent = layer.name;
    const count = document.createElement("td");
    count.className = "num";
    count.textContent = String(layer.entities);
    row.append(name, count);
    body.append(row);
  }
  const audit = drawing.audit ?? {};
  const clean = (audit.errors ?? 0) === 0 && (audit.fixes ?? 0) === 0;
  const pill = document.createElement("span");
  pill.className = `pill ${clean ? "passed" : "failed"}`;
  pill.textContent = clean ? "audit clean" : "audit reported problems";
  const text = document.createElement("span");
  text.className = "num";
  text.textContent = ` ${audit.errors ?? 0} errors, ${audit.fixes ?? 0} fixes`;
  const auditLine = document.getElementById("audit");
  auditLine.replaceChildren(pill, text);
}
