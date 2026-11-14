/* Slides viewer: a deck's preview is its presentation player.

   The URL parameter `role` picks the view: no role is the facet surface
   (the kit header, the current slide large, a thumbnail strip, the present
   and open-PDF actions); `role=audience` is one slide at a time from the
   page PNGs, letterboxed on the slide black and centred, with no header, no
   grain and nothing else on screen; `role=presenter` is the current slide
   large, the next slide smaller, the current slide's notes, a counter and a
   clock. The presenter takes the audience's keys plus buttons for previous,
   next, black and audience full screen.

   The windows sync through a BroadcastChannel named `facet-slides-<name>`:
   slide index, black screen and clock start travel in every update, any
   window drives the others, and a window that opens joins the running state
   without moving the others. The present flow carries the current slide in
   the hash, so the audience and the presenter open where the deck was.

   A page PNG asset shares the deck.slides capability, so this viewer also
   serves those: their preview is the image kind with no pages, and every
   role then shows a fallback instead of a slide.
*/

import { renderHeader } from "/kit/header.js";
import { assetUrl, loadAsset, showError } from "/kit/load.js";

const STEPS = {
  ArrowRight: 1,
  ArrowLeft: -1,
  PageDown: 1,
  PageUp: -1,
  " ": 1,
};
const FALLBACK_NOTES = "no speaker notes — add notes to the slides piece";
const NO_PAGES = "This preview lists no pages: preview the deck PDF, not a page PNG.";
const FULLSCREEN_HINT = "press F for full screen";

const loaded = await loadAsset();
if (loaded) main(loaded);

/** The view from `?role=`: audience, presenter, or the default surface. */
function roleOf() {
  const role = new URLSearchParams(window.location.search).get("role") ?? "";
  return role === "audience" || role === "presenter" ? role : "default";
}

/** The 1-based `#n` hash is the present flow's opening slide; else slide one. */
function initialIndex(total) {
  const hash = Number(window.location.hash.replace("#", ""));
  if (!Number.isInteger(hash) || hash < 1) return 0;
  return Math.min(hash - 1, Math.max(0, total - 1));
}

/** The URL of one page raster: the asset's own folder plus the page path. */
function pageUrl(asset, page) {
  const folder = asset.includes("/")
    ? asset.slice(0, asset.lastIndexOf("/") + 1)
    : "";
  return `/asset/${folder}${page}`;
}

/** The note for the current slide, or the fallback when the deck has none. */
function noteFor(notes, index) {
  const found = notes.find((note) => note.page === index + 1);
  return found ? found.text : FALLBACK_NOTES;
}

function padTime(value) {
  return String(value).padStart(2, "0");
}

/** The clock reads `mm:ss` from the first advance; `00:00` before that. */
function clockText(clockStart) {
  if (clockStart === null || clockStart === undefined) return "00:00";
  const seconds = Math.max(0, Math.floor((Date.now() - clockStart) / 1000));
  return `${padTime(Math.floor(seconds / 60))}:${padTime(seconds % 60)}`;
}

/** Which main is visible: the header only belongs to the default surface. */
function showRole(view) {
  document.body.dataset.role = view;
  document.getElementById("view-default").hidden = view !== "default";
  document.getElementById("view-audience").hidden = view !== "audience";
  document.getElementById("view-presenter").hidden = view !== "presenter";
  document.getElementById("header").hidden = view !== "default";
}

function openChannel(name) {
  try {
    return new BroadcastChannel(`facet-slides-${name}`);
  } catch {
    return null;
  }
}

/** One thumbnail per page; the current one carries `aria-current`. */
function buildThumbs(pages, asset, select) {
  const thumbs = document.getElementById("thumbs");
  const numbers = [];
  for (const [position, page] of pages.entries()) {
    const button = document.createElement("button");
    button.type = "button";
    const thumb = document.createElement("img");
    thumb.src = pageUrl(asset, page);
    thumb.alt = "";
    thumb.loading = "lazy";
    const num = document.createElement("span");
    num.className = "num";
    num.textContent = String(position + 1).padStart(2, "0");
    button.append(thumb, num);
    button.addEventListener("click", () => select(position));
    thumbs.append(button);
    numbers.push(button);
  }
  return numbers;
}

/** Paint every role from the state; only the visible one matters. */
function renderRole(deck) {
  const { state, pages, notes, asset, total, thumbs } = deck;
  const current = pageUrl(asset, pages[state.index]);
  const alt = `slide ${state.index + 1} of ${total}`;
  const stage = document.getElementById("slide");
  stage.src = current;
  stage.alt = alt;
  const aud = document.getElementById("aud-img");
  aud.src = current;
  aud.alt = alt;
  document.getElementById("aud-black").hidden = !state.black;
  const pres = document.getElementById("pres-current");
  pres.src = current;
  pres.alt = alt;
  renderNext(deck);
  document.getElementById("pres-count").textContent = `${state.index + 1} / ${total}`;
  document.getElementById("pres-clock").textContent = clockText(state.clockStart);
  document.getElementById("pres-notes").textContent = noteFor(notes, state.index);
  document.getElementById("pres-black").hidden = !state.black;
  for (const [position, button] of thumbs.entries()) {
    if (position === state.index) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
}

/** The next slide, or the end of the deck on the last one. */
function renderNext({ state, pages, asset, total }) {
  const next = document.getElementById("pres-next");
  const end = document.getElementById("pres-next-end");
  if (state.index + 1 >= total) {
    next.hidden = true;
    end.hidden = false;
    return;
  }
  next.hidden = false;
  end.hidden = true;
  next.src = pageUrl(asset, pages[state.index + 1]);
  next.alt = `slide ${state.index + 2} of ${total}`;
}

function hideAudHint() {
  document.getElementById("aud-hint").hidden = true;
}

/** Flash why full screen did not happen: the window needs a key press. */
function showAudHint() {
  const hint = document.getElementById("aud-hint");
  hint.textContent = FULLSCREEN_HINT;
  hint.hidden = false;
  window.setTimeout(hideAudHint, 3000);
}

/** Full screen the element, resolving false instead of rejecting. */
function requestFull(element) {
  try {
    const done = element.requestFullscreen?.();
    if (done && typeof done.catch === "function") {
      return done.then(() => true, () => false);
    }
    return Promise.resolve(true);
  } catch {
    return Promise.resolve(false);
  }
}

/** Clamp onto the deck; the first advance starts the clock. */
function go(deck, index) {
  const next = Math.min(Math.max(index, 0), deck.total - 1);
  if (next !== deck.state.index && deck.state.clockStart === null) {
    deck.state.clockStart = Date.now();
  }
  deck.state.index = next;
  deck.settled = true;
  renderRole(deck);
  deck.post("update", { state: { ...deck.state } });
}

function toggleBlack(deck) {
  deck.state.black = !deck.state.black;
  deck.settled = true;
  renderRole(deck);
  deck.post("update", { state: { ...deck.state } });
}

/** R resets the clock to now, on every window. */
function resetClock(deck) {
  deck.state.clockStart = Date.now();
  deck.settled = true;
  renderRole(deck);
  deck.post("update", { state: { ...deck.state } });
}

function onRemote(deck, event) {
  const message = event.data ?? {};
  if (message.type === "update" && message.state) {
    Object.assign(deck.state, message.state);
    renderRole(deck);
  } else if (message.type === "request") {
    deck.post("state", { state: { ...deck.state } });
  } else if (message.type === "state" && !deck.settled && message.state) {
    deck.settled = true;
    Object.assign(deck.state, message.state);
    renderRole(deck);
  } else if (message.type === "aud-full" && deck.view === "audience") {
    requestFull(document.getElementById("aud-frame")).then((done) => {
      if (!done) showAudHint();
    });
  }
}

/** Ask the running windows for their state; a late reply never moves us. */
function requestState(deck) {
  if (deck.settled || !deck.channel) return;
  deck.post("request", {});
  for (const delay of [400, 1200]) {
    window.setTimeout(() => {
      if (!deck.settled) deck.post("request", {});
    }, delay);
  }
}

/** Open the audience where the deck is; this tab becomes the presenter. */
function wirePresent(deck) {
  document.getElementById("present").addEventListener("click", () => {
    const hash = `#${deck.state.index + 1}`;
    const base = `${window.location.pathname}?asset=${encodeURIComponent(deck.name)}`;
    deck.audienceHandle = window.open(
      `${base}&role=audience${hash}`,
      `facet-slides-${deck.name}`,
    );
    history.pushState({}, "", `${base}&role=presenter${hash}`);
    deck.view = "presenter";
    showRole(deck.view);
    renderRole(deck);
  });
}

function wirePresenterButtons(deck) {
  document.getElementById("btn-prev").addEventListener("click", () => {
    go(deck, deck.state.index - 1);
  });
  document.getElementById("btn-next").addEventListener("click", () => {
    go(deck, deck.state.index + 1);
  });
  document.getElementById("btn-black").addEventListener("click", () => toggleBlack(deck));
  document.getElementById("btn-audience").addEventListener("click", () => fullscreenAudience(deck));
}

/** The audience full screen: the stored handle first, else open and ask. */
async function fullscreenAudience(deck) {
  const live = deck.audienceHandle && !deck.audienceHandle.closed
    ? deck.audienceHandle
    : null;
  if (!live) {
    // A fresh presenter load has no handle yet: open the audience first.
    const base = `${window.location.pathname}?asset=${encodeURIComponent(deck.name)}`;
    deck.audienceHandle = window.open(
      `${base}&role=audience#${deck.state.index + 1}`,
      `facet-slides-${deck.name}`,
    );
    return;
  }
  const frame = live.document.getElementById("aud-frame") ?? live.document.documentElement;
  if (await requestFull(frame)) return;
  deck.post("aud-full", {});
}

/** F full screens the audience frame, or this tab from the presenter. */
function toggleViewFull(deck) {
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
    return;
  }
  const target = deck.view === "audience"
    ? document.getElementById("aud-frame")
    : document.documentElement;
  requestFull(target).then((done) => {
    if (!done && deck.view === "audience") showAudHint();
  });
}

function wireKeys(deck) {
  document.addEventListener("keydown", (event) => {
    const tag = event.target instanceof HTMLElement ? event.target.tagName : "";
    if ((tag === "BUTTON" || tag === "A") && event.key === " ") return;
    if (deck.view === "default") {
      if (event.key === "ArrowRight") go(deck, deck.state.index + 1);
      else if (event.key === "ArrowLeft") go(deck, deck.state.index - 1);
      return;
    }
    stepKeys(deck, event);
  });
}

/** The audience and presenter share every key; the presenter adds buttons. */
function stepKeys(deck, event) {
  const step = STEPS[event.key];
  if (step !== undefined) {
    event.preventDefault();
    deck.typed = "";
    go(deck, deck.state.index + step);
  } else if (event.key === "Home") {
    deck.typed = "";
    go(deck, 0);
  } else if (event.key === "End") {
    deck.typed = "";
    go(deck, deck.total - 1);
  } else if (/^[0-9]$/.test(event.key)) {
    deck.typed += event.key;
  } else if (event.key === "Enter" && deck.typed) {
    event.preventDefault();
    go(deck, Number(deck.typed) - 1);
    deck.typed = "";
  } else if (event.key === "f" || event.key === "F") {
    toggleViewFull(deck);
  } else if (event.key === "b" || event.key === "B") {
    toggleBlack(deck);
  } else if (event.key === "r" || event.key === "R") {
    resetClock(deck);
  } else {
    deck.typed = "";
  }
}

function main({ name, record, preview }) {
  const deck = {
    name,
    view: roleOf(),
    state: { index: 0, black: false, clockStart: null },
    channel: openChannel(name),
    pages: Array.isArray(preview.pages) ? preview.pages : [],
    notes: Array.isArray(preview.notes) ? preview.notes : [],
    asset: record.path ?? name ?? "",
    total: 0,
    thumbs: [],
    typed: "",
    audienceHandle: null,
    // A window carrying `#n` opens where the deck was; any other window
    // joins the running state on its first reply, until it drives itself.
    settled: window.location.hash.replace("#", "") !== "",
    post: (type, extra) => deck.channel?.postMessage({ type, ...extra }),
  };
  deck.total = deck.pages.length;
  deck.state.index = initialIndex(deck.total);

  if (deck.view === "default") renderHeader(document.getElementById("header"), record);
  document.getElementById("summary").textContent = preview.summary ?? "";
  showRole(deck.view);
  if (deck.total === 0) {
    showError(NO_PAGES);
    return;
  }
  deck.thumbs = buildThumbs(deck.pages, deck.asset, (index) => go(deck, index));
  document.getElementById("pdf-link").href = assetUrl(deck.asset);
  wirePresent(deck);
  wirePresenterButtons(deck);
  wireKeys(deck);
  document.getElementById("view-audience").addEventListener("click", () => {
    if (deck.view === "audience") go(deck, deck.state.index + 1);
  });
  window.addEventListener("popstate", () => {
    deck.view = roleOf();
    showRole(deck.view);
    renderRole(deck);
  });
  if (deck.channel) deck.channel.onmessage = (event) => onRemote(deck, event);
  renderRole(deck);
  requestState(deck);
  window.setInterval(() => {
    if (deck.view === "presenter") {
      document.getElementById("pres-clock").textContent = clockText(deck.state.clockStart);
    }
  }, 500);
}
