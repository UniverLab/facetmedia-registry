/* Image viewer: the still itself, click to enlarge, and the piece data the
   preview carries — name, prompt, seed and the measured pixel size. */

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
  renderStill(name, preview);
  renderDetails(preview);
}

function renderStill(name, preview) {
  const image = document.getElementById("still");
  image.src = assetUrl(name);
  image.alt = preview.name ?? name;
  const zoom = document.getElementById("zoom");
  const zoomImg = document.getElementById("zoom-img");
  document.getElementById("zoom-close").addEventListener("click", () => zoom.close());
  image.addEventListener("click", () => {
    zoomImg.src = image.src;
    zoomImg.alt = image.alt;
    zoom.showModal();
  });
}

function kvRow(list, term, value) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value;
  list.append(dt, dd);
}

function renderDetails(preview) {
  const list = document.getElementById("details");
  kvRow(list, "name", preview.name ?? "—");
  kvRow(list, "prompt", preview.prompt ?? "—");
  kvRow(list, "seed", String(preview.seed ?? "—"));
  kvRow(list, "size", `${preview.width ?? "—"} × ${preview.height ?? "—"} px`);
}
