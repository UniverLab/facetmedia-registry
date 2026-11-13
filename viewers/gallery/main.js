/* Gallery viewer: one folder of assets as a filterable grid of cards.
   The page reads facet's `/gallery.json` and nothing else; a card's `thumb`
   and `open` are the only URLs it follows. */

const GLYPHS = { audio: "♪", cad: "◇", image: "▣", text: "¶", video: "▶" };
const FALLBACK_GLYPH = "•";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function loadGallery() {
  const response = await fetch("/gallery.json");
  if (!response.ok) throw new Error(`/gallery.json answered ${response.status}`);
  return response.json();
}

function fmtBytes(bytes) {
  if (typeof bytes !== "number" || !Number.isFinite(bytes)) return "—";
  const units = ["B", "kB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unit]}`;
}

function fmtDuration(seconds) {
  return `${Number(seconds).toFixed(1)} s`;
}

function fmtDate(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? String(iso) : date.toISOString().slice(0, 10);
}

function thumbnailOf(card) {
  const box = element("div", "thumb");
  if (card.thumb) {
    const image = element("img", "thumb-img");
    image.src = card.thumb;
    image.alt = "";
    image.loading = "lazy";
    box.append(image);
  } else {
    box.append(element("span", "kind-icon", GLYPHS[card.kind] ?? FALLBACK_GLYPH));
  }
  return box;
}

function factsOf(card) {
  const facts = element("p", "facts mono", fmtBytes(card.bytes));
  if (card.duration_s !== null && card.duration_s !== undefined) {
    facts.textContent += ` · ${fmtDuration(card.duration_s)}`;
  }
  return facts;
}

function bodyOf(card) {
  const body = element("div", "card-body");
  body.append(element("h3", "card-name", card.name));
  body.append(element("p", "muted", `${card.kind} · ${card.capability}`));
  body.append(element("p", "muted", `created ${fmtDate(card.created)}`));
  body.append(factsOf(card));
  body.append(
    element(
      "p",
      card.verified ? "pill passed" : "pill failed",
      card.verified ? "verified" : "failed",
    ),
  );
  if (card.open) {
    body.append(element("p", "open-hint", "open in this tab →"));
  } else {
    const fix = element("p", "fix");
    fix.append(
      element("span", null, "no preview yet: "),
      element("code", null, `facet preview ${card.asset}`),
    );
    body.append(fix);
  }
  return body;
}

function cardFor(card) {
  const shell = document.createElement(card.open ? "a" : "article");
  shell.className = "card";
  shell.dataset.kind = card.kind;
  shell.dataset.n = String(card.n);
  if (card.open) shell.href = card.open;
  shell.append(thumbnailOf(card), bodyOf(card));
  return shell;
}

function renderFilters(assets, grid) {
  const kinds = [...new Set(assets.map((card) => card.kind))];
  const shown = new Set(kinds);
  const buttons = kinds.map((kind) => {
    const button = element("button", "filter");
    button.type = "button";
    button.dataset.kind = kind;
    button.setAttribute("aria-pressed", "true");
    button.append(
      element("span", "glyph", GLYPHS[kind] ?? FALLBACK_GLYPH),
      element("span", null, kind),
    );
    button.addEventListener("click", () => {
      if (shown.has(kind)) shown.delete(kind);
      else shown.add(kind);
      button.setAttribute("aria-pressed", String(shown.has(kind)));
      for (const card of grid.children) {
        card.hidden = !shown.has(card.dataset.kind);
      }
    });
    return button;
  });
  document.getElementById("filters").replaceChildren(...buttons);
}

function renderGallery(gallery) {
  const assets = gallery.assets ?? [];
  document.getElementById("gal-folder").textContent = gallery.folder ?? "";
  document.getElementById("gal-count").textContent =
    `${assets.length} ${assets.length === 1 ? "asset" : "assets"}`;
  const grid = document.getElementById("grid");
  grid.replaceChildren(...assets.map(cardFor));
  if (assets.length === 0) grid.append(element("p", "muted", "This folder holds no assets."));
  renderFilters(assets, grid);
}

try {
  renderGallery(await loadGallery());
} catch (error) {
  const box = document.getElementById("error");
  box.hidden = false;
  box.textContent = `${error.message}\n\nRun \`facet preview <folder>\` to rebuild the gallery.`;
}
