/* Document viewer: a paginated PDF's page rasters, page by page.

   The pages sit in a column on the left, each with its number, and the
   selected page fills the stage. ↑/↓ and PageUp/PageDown step, a number then
   Enter jumps, and the fit toggle asks for the page at its own size. The PDF
   itself is one click away, from `/asset/<name>`. */

import { renderHeader } from "/kit/header.js";
import { assetUrl, loadAsset } from "/kit/load.js";

const STEPS = {
  ArrowUp: -1,
  ArrowDown: 1,
  PageUp: -1,
  PageDown: 1,
};

const loaded = await loadAsset();
if (loaded) main(loaded);

/** The URL of one page raster: the asset's own folder plus the page path. */
function pageUrl(asset, page) {
  const folder = asset.includes("/")
    ? asset.slice(0, asset.lastIndexOf("/") + 1)
    : "";
  return `/asset/${folder}${page}`;
}

function main({ name, record, preview }) {
  renderHeader(document.getElementById("header"), record);
  document.getElementById("summary").textContent = preview.summary ?? "";
  const pages = Array.isArray(preview.pages) ? preview.pages : [];
  const asset = record.path ?? name ?? "";
  const image = document.getElementById("page");
  const thumbs = document.getElementById("thumbs");
  const numbers = [];
  let current = 0;

  const select = (index) => {
    if (pages.length === 0) return;
    current = Math.min(Math.max(index, 0), pages.length - 1);
    image.src = pageUrl(asset, pages[current]);
    image.alt = `page ${current + 1} of ${pages.length}`;
    numbers.forEach((button, position) => {
      if (position === current) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    numbers[current]?.scrollIntoView({ block: "nearest", inline: "nearest" });
  };

  for (const [index, page] of pages.entries()) {
    const button = document.createElement("button");
    button.type = "button";
    const thumb = document.createElement("img");
    thumb.src = pageUrl(asset, page);
    thumb.alt = "";
    thumb.loading = "lazy";
    const num = document.createElement("span");
    num.className = "num";
    num.textContent = String(index + 1).padStart(2, "0");
    button.append(thumb, num);
    button.addEventListener("click", () => select(index));
    thumbs.append(button);
    numbers.push(button);
  }

  select(0);
  wireKeyboard(select, () => current);
  wireFit();
  wirePdf(asset);
  renderDetails(record, preview, asset);
}

function wireKeyboard(select, currentIndex) {
  let typed = "";
  document.addEventListener("keydown", (event) => {
    const step = STEPS[event.key];
    if (step !== undefined) {
      event.preventDefault();
      typed = "";
      select(currentIndex() + step);
      return;
    }
    if (/^[0-9]$/.test(event.key)) {
      typed += event.key;
      return;
    }
    if (event.key === "Enter" && typed) {
      event.preventDefault();
      select(Number(typed) - 1);
      typed = "";
      return;
    }
    typed = "";
  });
}

function wireFit() {
  const stage = document.getElementById("stage");
  const button = document.getElementById("fit");
  button.addEventListener("click", () => {
    const fit = stage.classList.toggle("fit");
    button.textContent = fit ? "fit width" : "1:1";
  });
}

function wirePdf(asset) {
  const link = document.getElementById("pdf-link");
  link.href = assetUrl(asset);
}

function kvRow(list, term, value) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value;
  list.append(dt, dd);
}

function renderDetails(record, preview, asset) {
  const list = document.getElementById("doc-kv");
  const count = preview.page_count ?? (preview.pages ?? []).length;
  kvRow(list, "pages", String(count));
  kvRow(list, "pdf", asset || "—");
  kvRow(list, "size", `${record.bytes ?? "—"} bytes`);
}
