/* Gallery viewer: one folder of assets as a filterable list, one line per
   asset grouped under its facet, in the manual's order. The page reads
   facet's `/gallery.json` and nothing else; a line's `thumb` and `open` are
   the only URLs it follows. */

const FACETS = ["voice", "audio", "image", "video", "cad", "text", "presentation"];
const OTHER = "other";
const GLYPHS = {
  audio: "♪",
  cad: "◇",
  image: "▣",
  presentation: "▤",
  text: "¶",
  video: "▶",
  voice: "◉",
};
const FALLBACK_GLYPH = "•";
const MUTED = "muted mono";

const shown = new Set();

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
    const image = element("img");
    image.src = card.thumb;
    image.alt = "";
    image.loading = "lazy";
    box.append(image);
  } else {
    box.append(element("span", "kind-icon", card.kind));
  }
  return box;
}

function factsOf(card) {
  const facts = [fmtBytes(card.bytes)];
  if (card.duration_s !== null && card.duration_s !== undefined) {
    facts.push(fmtDuration(card.duration_s));
  }
  return element("span", "facts mono", facts.join(" · "));
}

function fixOf(card) {
  const hint = element("p", "fix");
  const command = typeof card.package === "string"
    ? `facet pull --package ${card.package}`
    : "no preview: the record names no package";
  hint.append(element("code", null, command));
  return hint;
}

function lineFor(card) {
  const line = document.createElement(card.open ? "a" : "article");
  line.className = "card";
  line.dataset.n = String(card.n);
  line.dataset.kind = card.kind;
  line.dataset.name = card.name;
  line.dataset.capability = card.capability;
  if (card.open) line.href = card.open;
  line.append(
    thumbnailOf(card),
    element("span", "card-name", card.name),
    element("span", `capability ${MUTED}`, card.capability),
    factsOf(card),
    element("span", `created ${MUTED}`, fmtDate(card.created)),
    element(
      "span",
      card.verified ? "pill passed" : "pill failed",
      card.verified ? "✓" : "✗ failed",
    ),
  );
  if (!card.open) line.append(fixOf(card));
  return line;
}

function groupsOf(assets) {
  const buckets = new Map(FACETS.map((facet) => [facet, []]));
  const other = [];
  for (const card of assets) {
    if (FACETS.includes(card.facet)) buckets.get(card.facet).push(card);
    else other.push(card);
  }
  const groups = FACETS
    .map((facet) => ({ facet, cards: buckets.get(facet) }))
    .filter((group) => group.cards.length > 0);
  if (other.length > 0) groups.push({ facet: OTHER, cards: other });
  return groups;
}

function groupFor(group) {
  const section = element("section", "group");
  section.append(element("h2", null, group.facet), ...group.cards.map(lineFor));
  return section;
}

function applyFilters(query) {
  const needle = query.trim().toLowerCase();
  for (const group of document.querySelectorAll("#grid .group")) {
    let visible = 0;
    for (const line of group.querySelectorAll(".card")) {
      const name = (line.dataset.name ?? "").toLowerCase();
      const capability = (line.dataset.capability ?? "").toLowerCase();
      const matches = needle === "" || name.includes(needle) || capability.includes(needle);
      line.hidden = !(matches && shown.has(line.dataset.kind));
      if (!line.hidden) visible += 1;
    }
    group.hidden = visible === 0;
  }
}

function renderFilters(assets) {
  const container = document.getElementById("filters");
  const search = document.getElementById("search");
  const kinds = [...new Set(assets.map((card) => card.kind))];
  const toggles = kinds.map((kind) => {
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
      applyFilters(search.value);
    });
    return button;
  });
  container.replaceChildren(search, ...toggles);
  search.addEventListener("input", () => applyFilters(search.value));
}

function renderGallery(gallery) {
  const assets = gallery.assets ?? [];
  document.getElementById("gal-folder").textContent = gallery.folder ?? "";
  document.getElementById("gal-count").textContent =
    `${assets.length} ${assets.length === 1 ? "asset" : "assets"}`;
  const verified = assets.filter((card) => card.verified).length;
  document.getElementById("gal-verified").textContent = `${verified} verified`;
  shown.clear();
  for (const kind of new Set(assets.map((card) => card.kind))) shown.add(kind);
  const grid = document.getElementById("grid");
  grid.replaceChildren(...groupsOf(assets).map(groupFor));
  if (assets.length === 0) grid.append(element("p", "muted", "This folder holds no assets."));
  renderFilters(assets);
  applyFilters(document.getElementById("search").value);
}

try {
  renderGallery(await loadGallery());
} catch (error) {
  const box = document.getElementById("error");
  box.hidden = false;
  box.textContent = `${error.message}\n\nRun \`facet preview <folder>\` to rebuild the gallery.`;
}
