/* Video viewer: the clip itself in a player, and the piece data the preview
   carries — name, motion prompt, seed, measured size, frame count and rate. */

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
  renderClip(name, preview);
  renderDetails(preview);
}

function renderClip(name, preview) {
  const clip = document.getElementById("clip");
  clip.src = assetUrl(name);
  clip.setAttribute("aria-label", preview.name ?? name);
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
  kvRow(list, "length", `${preview.length ?? "—"} frames`);
  kvRow(list, "rate", `${preview.fps ?? "—"} fps`);
}
