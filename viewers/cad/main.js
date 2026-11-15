/* CAD viewer: every view the preview lists (click to enlarge), the solid's
   measurements against the expectations its parameters carry, and the
   drawing's units, layers and audit. A preview with only one of the two
   sections hides the other. */

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
  renderSolid(preview.solid, record.provenance?.params ?? {});
  renderDrawing(preview.drawing);
}

function renderViews(views) {
  if (views.length === 0) return;
  const section = document.getElementById("views");
  section.hidden = false;
  const container = section.querySelector(".views");
  // Every view is a panel of its own: a preview may list one or a dozen.
  container.classList.add("panels");
  const dialog = document.getElementById("zoom");
  const zoomImg = document.getElementById("zoom-img");
  const close = document.getElementById("zoom-close");
  let opener = null;
  /** Open the enlargement on `image`, from a click or a key. */
  const zoom = (image) => {
    opener = image;
    zoomImg.src = image.src;
    zoomImg.alt = image.alt;
    dialog.showModal();
    close.focus();
  };
  close.addEventListener("click", () => dialog.close());
  // Closing gives the focus back to the view that opened it.
  dialog.addEventListener("close", () => opener?.focus());
  for (const view of views) {
    const figure = document.createElement("figure");
    const image = document.createElement("img");
    image.src = assetUrl(view.file);
    image.alt = `${view.label ?? view.file} view`;
    const caption = document.createElement("figcaption");
    caption.textContent = view.label ?? view.file;
    // A view is a button: it opens from the keyboard too.
    image.tabIndex = 0;
    image.setAttribute("role", "button");
    image.setAttribute("aria-label", `enlarge ${image.alt}`);
    image.addEventListener("click", () => zoom(image));
    image.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      zoom(image);
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

/** `expect-bbox-mm` as three numbers: the core delivers `[{x, y, z}]`, but a
    flat `[x, y, z]` reads the same to a person, so both are accepted. */
function bboxParam(value) {
  if (!Array.isArray(value) || value.length === 0) return null;
  const first = value[0];
  if (first !== null && typeof first === "object") {
    const sides = [first.x, first.y, first.z];
    return sides.every((side) => typeof side === "number") ? sides : null;
  }
  const flat = value.every((side) => typeof side === "number");
  return flat && value.length === 3 ? value : null;
}

/** Each measured size beside the one the piece expected, when its parameters
    say so: volume first, then the bounding box. */
function expectationRows(solid, params) {
  const rows = [];
  const volume = params["expect-volume-mm3"];
  if (typeof volume === "number") rows.push(["expected volume", `${volume} mm³`]);
  const bbox = bboxParam(params["expect-bbox-mm"]);
  if (bbox !== null) rows.push(["expected bounding box", vector(bbox, " mm")]);
  if (rows.length === 0) return rows;
  return [
    ["measured volume", `${solid.volume_mm3 ?? "—"} mm³`],
    ...rows,
    ["measured bounding box", vector(solid.bbox_mm, " mm")],
  ];
}

function renderSolid(solid, params) {
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
  for (const [term, value] of expectationRows(solid, params)) kvRow(list, term, value);
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
