#!/usr/bin/env node
/* Open every viewer example in light and dark at 1280x800 and 390x844, one
   case at a time, with the system Chrome: fail on any page error, console
   error, failed request or HTTP >= 400, exercise the interaction the viewer
   exists for (audio play, pause, seek by click, drag and arrow and its metric
   lines, the CAD views from a click and from the keyboard and the measures
   beside their expectations, the document's page step and jump with its PDF
   link, the image fit/1:1 toggle, its pan and the checkerboard over a
   transparent cut-out, the video clip's play, scrub, frame step and full
   screen, the GIF line and the generic text, JSON, subtitle (SRT and VTT),
   ASCII and copy branches, the fields fallback an image record keeps, the
   gallery's filter and its open link and back button, the slides viewer in its
   default, audience and presenter roles), and
   save a screenshot of each case under viewers/_examples/<kind>/screens/
   (gitignored).

   A kind with more than one example asset is opened once per asset, its name
   swapped in the URL.

   Run by hand:  node scripts/check-viewers.mjs [kind ...]
   Needs playwright-core resolvable (npm i --prefix /tmp/opencode/pw
   playwright-core, then NODE_PATH=/tmp/opencode/pw/node_modules). */

import { spawn } from "node:child_process";
import { mkdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CHROME = process.env.CHROME_PATH || "/usr/bin/google-chrome";
const KINDS = process.argv.slice(2).length > 0
  ? process.argv.slice(2)
  : ["generic", "audio", "cad", "document", "image", "video", "gallery", "slides"];
/*: The slides viewer renders three roles: the default surface plus
   `&role=audience` and `&role=presenter`, each with its own interaction. */
const ROLE_SUFFIXES = {
  slides: ["", "&role=audience", "&role=presenter"],
};

function suffixesFor(kind) {
  return ROLE_SUFFIXES[kind] ?? [""];
}

function roleTag(suffix) {
  return suffix.startsWith("&role=") ? `-${suffix.slice("&role=".length)}` : "";
}

/*: The assets each kind is opened with, when its folder has more than one.
   The server's own default (`null`) is the first example on disk. */
const ASSETS = {
  video: ["bosque-niebla.mp4", "loop.gif"],
  generic: ["hello.txt", "notes.srt", "notes.vtt", "pieza.json", "sheet.txt", "plate.svg"],
  image: ["foto-producto.png", "recorte.png"],
};

function assetsFor(kind) {
  return ASSETS[kind] ?? [null];
}

/** The server's URL with `asset` swapped, so one server serves every asset. */
function assetUrlFor(url, asset) {
  if (asset === null) return url;
  const target = new URL(url);
  target.searchParams.set("asset", asset);
  return target.toString();
}

/** A tag from the whole file name, so `notes.srt` and `notes.vtt` never share
    a label or a screenshot. */
function assetTag(kind, asset) {
  if (asset === null || assetsFor(kind).length < 2) return "";
  return `-${asset.replace(/[^0-9a-zA-Z]+/g, "-").replace(/-$/, "")}`;
}

/** The preview beside the asset the page opened. */
async function fetchPreview(page) {
  return page.evaluate(async () => {
    const name = new URLSearchParams(window.location.search).get("asset") ?? "";
    const response = await fetch(`/asset/${encodeURIComponent(name)}.preview.json`);
    return response.json();
  });
}
//: The gallery example: the page must render every card this file describes.
const GALLERY = JSON.parse(
  readFileSync(path.join(ROOT, "viewers", "_examples", "gallery.json"), "utf8"),
);
const CASES = [
  { scheme: "light", width: 1280, height: 800 },
  { scheme: "dark", width: 1280, height: 800 },
  { scheme: "light", width: 390, height: 844 },
  { scheme: "dark", width: 390, height: 844 },
];

const require = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require("playwright-core"));
} catch (error) {
  console.error(`check-viewers: playwright-core not resolvable (${error.message}).`);
  console.error("Install it outside the repo and point NODE_PATH at it, e.g.:");
  console.error("  npm i --prefix /tmp/opencode/pw playwright-core");
  console.error("  NODE_PATH=/tmp/opencode/pw/node_modules node scripts/check-viewers.mjs");
  process.exit(2);
}

function startServer(kind) {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", ["scripts/serve-example.py", kind, "--port", "0"], {
      cwd: ROOT,
      stdio: ["ignore", "pipe", "inherit"],
    });
    let stdout = "";
    const timer = setTimeout(() => reject(new Error(`${kind}: server printed no URL`)), 15000);
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
      const url = stdout.split("\n")[0].trim();
      if (url.startsWith("http://")) {
        clearTimeout(timer);
        resolve({ child, url });
      }
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`${kind}: server exited with ${code}`));
    });
  });
}

function watchPage(page, label, failures) {
  page.on("pageerror", (error) => failures.push(`${label}: pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") failures.push(`${label}: console error: ${message.text()}`);
  });
  page.on("requestfailed", (request) => {
    const reason = request.failure()?.errorText ?? "unknown";
    if (reason !== "net::ERR_ABORTED" && !request.url().endsWith("/favicon.ico")) {
      failures.push(`${label}: request failed: ${request.url()} (${reason})`);
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 400 && !response.url().endsWith("/favicon.ico")) {
      failures.push(`${label}: HTTP ${response.status()}: ${response.url()}`);
    }
  });
}

/** Click at 60% of the waveform: the player must seek there (a server that
    sends no byte ranges leaves it at 0 s and the playhead never moves). */
async function checkAudioSeek(page, label, failures) {
  const wave = page.locator("#wave");
  const box = await wave.boundingBox();
  if (!box) {
    failures.push(`${label}: no waveform canvas`);
    return;
  }
  await wave.click({ position: { x: 46 + (box.width - 56) * 0.6, y: box.height / 2 } });
  await page.waitForTimeout(400);
  const [time, duration] = await page.evaluate(() => {
    const player = document.getElementById("player");
    return [player.currentTime, player.duration];
  });
  if (!(Number.isFinite(duration) && duration > 0)) {
    failures.push(`${label}: the player reported no duration`);
  } else if (Math.abs(time - 0.6 * duration) > 0.25) {
    failures.push(`${label}: click-to-seek left the player at ${time}s of ${duration}s`);
  }
}

/** Space plays and pauses, the arrows seek a second, a drag scrubs, and the
    metric lines the audio viewer exists for are all there. */
async function checkAudioTransport(page, label, failures) {
  const time = await page.locator("#time").innerText();
  if (!/^\d\d:\d\d\.\d \/ \d\d:\d\d\.\d$/.test(time)) {
    failures.push(`${label}: the time reads ${JSON.stringify(time)}`);
  }
  await page.keyboard.press("Space");
  await page.waitForTimeout(400);
  if (await page.evaluate(() => document.getElementById("player").paused)) {
    failures.push(`${label}: space did not start playback`);
  }
  const button = await page.locator("#play").innerText();
  if (button !== "pause") failures.push(`${label}: the button reads ${JSON.stringify(button)}`);
  await page.keyboard.press("Space");
  if (!(await page.evaluate(() => document.getElementById("player").paused))) {
    failures.push(`${label}: the second space did not pause`);
  }
  const before = await page.evaluate(() => document.getElementById("player").currentTime);
  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(200);
  const after = await page.evaluate(() => document.getElementById("player").currentTime);
  if (Math.abs(after - before - 1) > 0.25) {
    failures.push(`${label}: ArrowRight moved ${before}s -> ${after}s, not one second`);
  }
  const wave = page.locator("#wave");
  const box = await wave.boundingBox();
  if (!box) {
    failures.push(`${label}: no waveform canvas`);
    return;
  }
  const y = box.height / 2;
  const xAt = (fraction) => box.x + 46 + (box.width - 56) * fraction;
  await page.mouse.move(xAt(0.2), box.y + y);
  await page.mouse.down();
  await page.mouse.move(xAt(0.75), box.y + y, { steps: 6 });
  await page.mouse.up();
  await page.waitForTimeout(300);
  const [dragged, duration] = await page.evaluate(() => {
    const player = document.getElementById("player");
    return [player.currentTime, player.duration];
  });
  if (!(Number.isFinite(duration) && duration > 0)) {
    failures.push(`${label}: the player reported no duration`);
  } else if (Math.abs(dragged - 0.75 * duration) > 0.3) {
    failures.push(`${label}: dragging left the player at ${dragged}s of ${duration}s`);
  }
  const stats = await page.locator("#stats").innerText();
  for (const row of ["integrated loudness", "true peak", "sample rate", "duration", "peak limited"]) {
    if (!stats.includes(row)) failures.push(`${label}: no "${row}" metric line`);
  }
}

/** A view opens its enlargement from a click and from the keyboard, and
    Escape gives the focus back to the view that opened it. */
async function checkCadZoom(page, label, failures) {
  const view = page.locator(".views img").first();
  if ((await view.count()) === 0) {
    failures.push(`${label}: no view image`);
    return;
  }
  const open = () => page.evaluate(() => document.getElementById("zoom").open);
  await view.click();
  if (!(await open())) failures.push(`${label}: clicking a view did not open the enlargement`);
  await page.evaluate(() => document.getElementById("zoom").close());
  const focusable = await page.evaluate(() => {
    const image = document.querySelector(".views img");
    return image.tabIndex === 0 && image.getAttribute("role") === "button";
  });
  if (!focusable) failures.push(`${label}: a view is not a keyboard button`);
  for (const key of ["Enter", " "]) {
    await view.focus();
    await page.keyboard.press(key === " " ? "Space" : key);
    if (!(await open())) {
      failures.push(`${label}: ${JSON.stringify(key)} on a view did not open the enlargement`);
      continue;
    }
    await page.keyboard.press("Escape");
    await page.waitForTimeout(100);
    const back = await page.evaluate(() => document.activeElement?.tagName === "IMG");
    if (!back) failures.push(`${label}: closing the enlargement did not return the focus`);
  }
}

/** The image viewer: fitted at load, Z and a click toggle 1:1, a 1:1 drag pans,
    the background toggles to a painted checkerboard, and the metrics name the
    pixels and the file's size. On the cut-out sample the checkerboard has
    transparent pixels to show through. */
async function checkImage(page, label, failures, asset) {
  const fitted = () => page.evaluate(() => document.getElementById("stage").classList.contains("fit"));
  if ((await page.locator("#still").count()) === 0) {
    failures.push(`${label}: no still image`);
    return;
  }
  if (!(await fitted())) failures.push(`${label}: the still is not fitted at load`);
  await page.keyboard.press("z");
  if (await fitted()) failures.push(`${label}: Z did not show the still at 1:1`);
  await page.keyboard.press("z");
  if (!(await fitted())) failures.push(`${label}: the second Z did not fit it again`);
  await page.locator("#still").click();
  if (await fitted()) failures.push(`${label}: a click did not show the still at 1:1`);
  const stage = page.locator("#stage");
  const box = await stage.boundingBox();
  const scrolled = await page.evaluate(() => document.getElementById("stage").scrollLeft);
  if (box) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 - 60, box.y + box.height / 2, { steps: 4 });
    await page.mouse.up();
  }
  await page.waitForTimeout(200);
  const panned = await page.evaluate(() => document.getElementById("stage").scrollLeft);
  // A small still fits the stage even at 1:1: there is nothing to pan.
  const overflows = await page.evaluate(() => {
    const stage = document.getElementById("stage");
    return stage.scrollWidth > stage.clientWidth;
  });
  if (overflows && panned === scrolled) {
    failures.push(`${label}: dragging at 1:1 did not pan the still`);
  }
  await page.click("#bg");
  const checker = await page.evaluate(() => {
    const stage = document.getElementById("stage");
    const style = getComputedStyle(stage);
    return {
      classed: stage.classList.contains("checker"),
      image: style.backgroundImage,
      size: style.backgroundSize,
    };
  });
  if (!checker.classed) failures.push(`${label}: the background toggle drew no checkerboard`);
  if (!checker.image.includes("gradient") || !checker.size.startsWith("24px")) {
    failures.push(`${label}: the checkerboard paints ${JSON.stringify(checker)}`);
  }
  if (asset === "recorte.png") await checkTransparency(page, label, failures);
  const stats = await page.locator("#stats").innerText();
  for (const row of ["pixels", "file size"]) {
    if (!stats.includes(row)) failures.push(`${label}: no "${row}" metric line`);
  }
}

/** The cut-out sample really carries alpha: at least one pixel is see-through,
    so the checkerboard behind it has something to show. */
async function checkTransparency(page, label, failures) {
  const alpha = await page.evaluate(async () => {
    const still = document.getElementById("still");
    await still.decode().catch(() => {});
    const canvas = document.createElement("canvas");
    canvas.width = still.naturalWidth;
    canvas.height = still.naturalHeight;
    const context = canvas.getContext("2d");
    context.drawImage(still, 0, 0);
    const { data } = context.getImageData(0, 0, canvas.width, canvas.height);
    let clear = 0;
    for (let index = 3; index < data.length; index += 4) {
      if (data[index] === 0) clear += 1;
    }
    return { total: data.length / 4, clear };
  });
  if (alpha.clear === 0) {
    failures.push(`${label}: the cut-out is opaque (${JSON.stringify(alpha)})`);
  }
}

/** The CAD viewer: one panel per view the preview lists, and the measures
    beside the expectations the piece carries. */
async function checkCad(page, label, failures) {
  const preview = await fetchPreview(page);
  const views = await page.locator(".views img").count();
  if (views !== preview.views.length) {
    failures.push(`${label}: ${views} views, expected ${preview.views.length}`);
  }
  await checkCadZoom(page, label, failures);
  if (preview.solid) {
    const list = await page.locator("#solid-kv").innerText();
    for (const row of ["expected volume", "expected bounding box"]) {
      if (!list.includes(row)) failures.push(`${label}: no "${row}" measure`);
    }
  }
}

/** The video viewer on a playable clip: play, scrub, frame step, the metrics. */
async function checkVideoClip(page, label, failures) {
  const preview = await fetchPreview(page);
  const clip = page.locator("#clip");
  if (!(await clip.isVisible())) {
    failures.push(`${label}: the clip element is hidden`);
    return;
  }
  await page.waitForFunction(() => document.getElementById("clip").readyState >= 1, null, {
    timeout: 10000,
  }).catch(() => failures.push(`${label}: the clip never loaded metadata`));
  const frame = await page.locator("#frame").innerText();
  if (frame !== `frame 1 / ${preview.length}`) {
    failures.push(`${label}: the frame reads ${JSON.stringify(frame)}`);
  }
  await page.keyboard.press("Space");
  await page.waitForTimeout(400);
  if (await page.evaluate(() => document.getElementById("clip").paused)) {
    failures.push(`${label}: space did not play the clip`);
  }
  await page.keyboard.press("Space");
  if (!(await page.evaluate(() => document.getElementById("clip").paused))) {
    failures.push(`${label}: the second space did not pause the clip`);
  }
  await page.locator("#scrub").fill("1");
  await page.waitForTimeout(300);
  const scrubbed = await page.evaluate(() => document.getElementById("clip").currentTime);
  if (Math.abs(scrubbed - 1) > 0.25) {
    failures.push(`${label}: the scrub bar left the clip at ${scrubbed}s`);
  }
  const before = await page.evaluate(() => document.getElementById("clip").currentTime);
  await page.keyboard.press(".");
  await page.waitForTimeout(200);
  const after = await page.evaluate(() => document.getElementById("clip").currentTime);
  const step = 1 / preview.fps;
  if (Math.abs(after - before - step) > step / 2) {
    failures.push(`${label}: "." moved ${before}s -> ${after}s, not one frame`);
  }
  const stats = await page.locator("#stats").innerText();
  for (const row of ["resolution", "fps", "frames", "duration"]) {
    if (!stats.includes(row)) failures.push(`${label}: no "${row}" metric line`);
  }
  if (!/^\d\d:\d\d\.\d \/ \d\d:\d\d\.\d$/.test(await page.locator("#time").innerText())) {
    failures.push(`${label}: the time reads ${JSON.stringify(await page.locator("#time").innerText())}`);
  }
}

/** The video viewer on a GIF: the line, the image, no scrub bar, and F. */
async function checkVideoGif(page, label, failures) {
  const line = await page.locator("#gif-line").innerText();
  if (!/^GIF · loops · \d+ frames · \d+ fps$/.test(line)) {
    failures.push(`${label}: the GIF line reads ${JSON.stringify(line)}`);
  }
  if (!(await page.locator("#gif").isVisible())) {
    failures.push(`${label}: the GIF image is hidden`);
  }
  if (await page.locator("#clip-controls").isVisible()) {
    failures.push(`${label}: a GIF shows a scrub bar`);
  }
  await page.keyboard.press("f");
  await page.waitForTimeout(400);
  // A headless window may refuse full screen; either way F must not throw,
  // which the console watcher above would have caught.
}

/** The generic viewer's text branches: numbered lines, pretty JSON, cues from
    SRT and VTT, ASCII, and the copy button each one carries. */
async function checkGeneric(page, label, failures, asset) {
  if (asset === "hello.txt") {
    const lines = await page.locator("#lines li").count();
    if (lines !== 1) failures.push(`${label}: ${lines} numbered lines, expected 1`);
    await checkCopy(page, "#copy-text", label, failures);
  } else if (asset === "notes.srt" || asset === "notes.vtt") {
    const cues = await page.locator("#cues tbody tr").count();
    if (cues !== 2) failures.push(`${label}: ${cues} cue rows, expected 2`);
    const time = await page.locator("#cues tbody tr td").first().innerText();
    const sep = asset === "notes.vtt" ? "." : ",";
    const first = `00:00:00${sep}000 --> 00:00:02${sep}000`;
    if (time !== first) {
      failures.push(`${label}: the first cue starts ${JSON.stringify(time)}`);
    }
    await checkCopy(page, "#copy-cues", label, failures);
  } else if (asset === "pieza.json") {
    const pretty = await page.locator("#json").innerText();
    if (!pretty.startsWith("{")) failures.push(`${label}: the JSON is not an object`);
    if (!pretty.includes('\n  "pieza": "escuadra"')) {
      failures.push(`${label}: the JSON is not pretty-printed (${JSON.stringify(pretty)})`);
    }
    await checkCopy(page, "#copy-json", label, failures);
  } else if (asset === "sheet.txt") {
    const art = await page.locator("#ascii").innerText();
    if (!art.includes("ascii contact sheet")) {
      failures.push(`${label}: the ASCII sheet is not shown`);
    }
    const layout = await page.evaluate(() => {
      const style = getComputedStyle(document.getElementById("ascii"));
      return { whiteSpace: style.whiteSpace, overflowX: style.overflowX };
    });
    if (layout.whiteSpace !== "pre" || layout.overflowX !== "auto") {
      failures.push(`${label}: the ASCII sheet wraps (${JSON.stringify(layout)})`);
    }
    await checkCopy(page, "#copy-ascii", label, failures);
  } else if (asset === "plate.svg") {
    // A contact sheet is a picture that says how wide its art would be: the
    // fields table and the link are the answer, never the bytes as text.
    if (await page.locator("#ascii-section").isVisible()) {
      failures.push(`${label}: an image record was rendered as ASCII text`);
    }
    const rows = await page.locator("#fields tbody tr").count();
    if (rows === 0) failures.push(`${label}: the fallback shows no fields`);
    const link = await page.locator("#asset-link").getAttribute("href");
    if (link !== "/asset/plate.svg") {
      failures.push(`${label}: the fallback link is ${JSON.stringify(link)}`);
    }
  }
}

/** A copy button says `copied` once the text is in the clipboard. */
async function checkCopy(page, selector, label, failures) {
  const button = page.locator(selector);
  if ((await button.count()) === 0) {
    failures.push(`${label}: no copy button (${selector})`);
    return;
  }
  await button.click();
  await page.waitForTimeout(300);
  const text = await button.innerText();
  if (text !== "copied") failures.push(`${label}: the copy button reads ${JSON.stringify(text)}`);
}

/** The document viewer: one thumbnail per page, the keys and a jump step it,
    and the header action points at the PDF on the asset route. */
async function checkDocument(page, label, failures) {
  const preview = await page.evaluate(async () => {
    const name = new URLSearchParams(window.location.search).get("asset") ?? "";
    const response = await fetch(`/asset/${encodeURIComponent(name)}.preview.json`);
    return response.json();
  });
  const thumbs = await page.locator("#thumbs button").count();
  if (thumbs !== preview.page_count) {
    failures.push(`${label}: ${thumbs} thumbnails, expected ${preview.page_count}`);
  }
  const source = () => page.evaluate(() => document.getElementById("page").getAttribute("src"));
  if ((await source()) !== `/asset/${preview.pages[0]}`) {
    failures.push(`${label}: the first page is ${await source()}`);
  }
  await page.keyboard.press("ArrowDown");
  if ((await source()) !== `/asset/${preview.pages[1]}`) {
    failures.push(`${label}: ArrowDown left the page at ${await source()}`);
  }
  await page.keyboard.press("1");
  await page.keyboard.press("Enter");
  if ((await source()) !== `/asset/${preview.pages[0]}`) {
    failures.push(`${label}: "1" then Enter left the page at ${await source()}`);
  }
  const link = page.locator("#pdf-link");
  if ((await link.getAttribute("href")) !== "/asset/doc.pdf") {
    failures.push(`${label}: the PDF link is ${await link.getAttribute("href")}`);
  }
  if ((await link.getAttribute("target")) !== "_blank") {
    failures.push(`${label}: the PDF link is not a new tab`);
  }
  await page.click("#fit");
  const fitted = await page.evaluate(() => document.getElementById("stage").classList.contains("fit"));
  if (!fitted) failures.push(`${label}: the fit toggle did nothing`);
}

/** The header names the folder and counts the assets. */
async function checkGalleryHeader(page, label, failures) {
  const header = await page.locator("#gal-head").innerText();
  if (!header.includes(GALLERY.folder)) {
    failures.push(`${label}: the header does not name ${GALLERY.folder}`);
  }
  if (!header.includes(String(GALLERY.assets.length))) {
    failures.push(`${label}: the header does not count ${GALLERY.assets.length} assets`);
  }
}

/** Every card shows what gallery.json says: thumb or icon, badge, duration. */
async function checkGalleryCards(page, label, failures) {
  for (const asset of GALLERY.assets) {
    const card = page.locator(`.card[data-n="${asset.n}"]`);
    if ((await card.count()) !== 1) {
      failures.push(`${label}: no card for ${asset.asset}`);
      continue;
    }
    if (asset.thumb === null) {
      if ((await card.locator(".kind-icon").count()) === 0) {
        failures.push(`${label}: ${asset.asset} has no kind icon`);
      }
    } else if ((await card.locator(`img[src="${asset.thumb}"]`).count()) === 0) {
      failures.push(`${label}: ${asset.asset} has no thumbnail`);
    }
    const badge = asset.verified ? ".pill.passed" : ".pill.failed";
    if ((await card.locator(badge).count()) === 0) {
      failures.push(`${label}: ${asset.asset} has no ${badge.slice(6)} badge`);
    }
    if (asset.duration_s !== null) {
      const text = await card.innerText();
      if (!text.includes(`${asset.duration_s.toFixed(1)} s`)) {
        failures.push(`${label}: ${asset.asset} shows no duration`);
      }
    }
  }
}

/** One toggle per kind present, and each toggle hides and shows its cards. */
async function checkGalleryFilters(page, label, failures) {
  const buttons = page.locator("#filters button");
  const kinds = await buttons.evaluateAll((nodes) => nodes.map((node) => node.dataset.kind));
  const expected = [...new Set(GALLERY.assets.map((asset) => asset.kind))];
  if (kinds.length !== expected.length || expected.some((kind) => !kinds.includes(kind))) {
    failures.push(`${label}: toggles ${kinds.join(",")} do not match kinds ${expected.join(",")}`);
    return;
  }
  const first = buttons.first();
  const kind = kinds[0];
  const card = page.locator(`.card[data-kind="${kind}"]`).first();
  await first.click();
  if (await card.isVisible()) failures.push(`${label}: turning ${kind} off hid nothing`);
  await first.click();
  if (!(await card.isVisible())) failures.push(`${label}: turning ${kind} back on hid its cards`);
}

/** A card with `open` navigates in the same tab, and back returns here. */
async function checkGalleryOpen(page, label, failures) {
  const asset = GALLERY.assets.find((candidate) => candidate.open !== null);
  if (!asset) return;
  const link = page.locator(`a.card[href="${asset.open}"]`);
  if ((await link.count()) === 0) {
    failures.push(`${label}: no card links to ${asset.open}`);
    return;
  }
  await link.first().click();
  await page.waitForLoadState("load");
  if (new URL(page.url()).pathname !== asset.open) {
    failures.push(`${label}: a card opened ${page.url()}`);
    return;
  }
  await page.goBack({ waitUntil: "load" });
  await page.waitForSelector(".card");
  if ((await page.locator("#gal-head").count()) === 0) {
    failures.push(`${label}: the back button did not return to the gallery`);
  }
}

/** A card with no `open` is not a link and names the command that fixes it. */
async function checkGalleryFix(page, label, failures) {
  const asset = GALLERY.assets.find((candidate) => candidate.open === null);
  if (!asset) return;
  const card = page.locator(`.card[data-n="${asset.n}"]`);
  if ((await card.count()) === 0) {
    failures.push(`${label}: no card for ${asset.asset}`);
    return;
  }
  if ((await card.locator("a").count()) !== 0) {
    failures.push(`${label}: ${asset.asset} is a link without a preview`);
  }
  const command = await card.locator("code").innerText();
  if (command.trim() !== `facet preview ${asset.asset}`) {
    failures.push(`${label}: fix command is ${JSON.stringify(command)}`);
  }
}

async function checkGallery(page, label, failures) {
  const count = await page.locator(".card").count();
  if (count !== GALLERY.assets.length) {
    failures.push(`${label}: ${count} cards, expected ${GALLERY.assets.length}`);
  }
  await checkGalleryHeader(page, label, failures);
  await checkGalleryCards(page, label, failures);
  await checkGalleryFilters(page, label, failures);
  await checkGalleryOpen(page, label, failures);
  await checkGalleryFix(page, label, failures);
}

/** The slides viewer: the default surface steps with the arrows, opens the
    PDF in a new tab, and turns itself into the presenter while opening the
    audience where the deck was. */
async function checkSlidesDefault(page, context, label, failures) {
  const preview = await page.evaluate(async () => {
    const name = new URLSearchParams(window.location.search).get("asset") ?? "";
    const response = await fetch(`/asset/${encodeURIComponent(name)}.preview.json`);
    return response.json();
  });
  const thumbs = await page.locator("#thumbs button").count();
  if (thumbs !== preview.page_count) {
    failures.push(`${label}: ${thumbs} thumbnails, expected ${preview.page_count}`);
  }
  const source = () => page.evaluate(() => document.getElementById("slide").getAttribute("src"));
  if ((await source()) !== `/asset/${preview.pages[0]}`) {
    failures.push(`${label}: the first slide is ${await source()}`);
  }
  await page.keyboard.press("ArrowRight");
  if ((await source()) !== `/asset/${preview.pages[1]}`) {
    failures.push(`${label}: ArrowRight left the slide at ${await source()}`);
  }
  // The default surface steps with the arrows only (digit jumps live in the
  // audience and presenter roles), so ArrowLeft returns to the first slide.
  await page.keyboard.press("ArrowLeft");
  if ((await source()) !== `/asset/${preview.pages[0]}`) {
    failures.push(`${label}: ArrowLeft left the slide at ${await source()}`);
  }
  const link = page.locator("#pdf-link");
  if ((await link.getAttribute("href")) !== "/asset/deck.pdf") {
    failures.push(`${label}: the PDF link is ${await link.getAttribute("href")}`);
  }
  if ((await link.getAttribute("target")) !== "_blank") {
    failures.push(`${label}: the PDF link is not a new tab`);
  }
  const [popup] = await Promise.all([
    context.waitForEvent("page"),
    page.click("#present"),
  ]);
  await popup.waitForLoadState("load");
  if (!popup.url().includes("&role=audience")) {
    failures.push(`${label}: present opened ${popup.url()}`);
  }
  if (!page.url().includes("&role=presenter")) {
    failures.push(`${label}: present left this tab at ${page.url()}`);
  }
  const count = await page.locator("#pres-count").innerText();
  if (count !== `1 / ${preview.page_count}`) {
    failures.push(`${label}: the presenter counts ${JSON.stringify(count)}`);
  }
  await popup.close();
}

/** The audience: one slide on the black, keys step and jump, B blacks out. */
async function checkSlidesAudience(page, label, failures) {
  const preview = await page.evaluate(async () => {
    const name = new URLSearchParams(window.location.search).get("asset") ?? "";
    const response = await fetch(`/asset/${encodeURIComponent(name)}.preview.json`);
    return response.json();
  });
  if (!(await page.locator("#header").isHidden())) {
    failures.push(`${label}: the audience shows a header`);
  }
  const source = () => page.evaluate(() => document.getElementById("aud-img").getAttribute("src"));
  if ((await source()) !== `/asset/${preview.pages[0]}`) {
    failures.push(`${label}: the first slide is ${await source()}`);
  }
  await page.keyboard.press("ArrowRight");
  if ((await source()) !== `/asset/${preview.pages[1]}`) {
    failures.push(`${label}: ArrowRight left the slide at ${await source()}`);
  }
  await page.keyboard.press("End");
  if ((await source()) !== `/asset/${preview.pages[preview.pages.length - 1]}`) {
    failures.push(`${label}: End left the slide at ${await source()}`);
  }
  await page.keyboard.press("Home");
  if ((await source()) !== `/asset/${preview.pages[0]}`) {
    failures.push(`${label}: Home left the slide at ${await source()}`);
  }
  await page.keyboard.press("2");
  await page.keyboard.press("Enter");
  if ((await source()) !== `/asset/${preview.pages[1]}`) {
    failures.push(`${label}: "2" then Enter left the slide at ${await source()}`);
  }
  await page.keyboard.press("b");
  if (!(await page.locator("#aud-black").isVisible())) {
    failures.push(`${label}: B did not black the screen`);
  }
  await page.keyboard.press("b");
  if (await page.locator("#aud-black").isVisible()) {
    failures.push(`${label}: the second B did not lift the black screen`);
  }
  await page.locator("#aud-frame").click();
  if ((await source()) !== `/asset/${preview.pages[2]}`) {
    failures.push(`${label}: a click left the slide at ${await source()}`);
  }
  await page.keyboard.press("f");
  await page.waitForTimeout(400);
  const full = await page.evaluate(() => document.fullscreenElement !== null);
  const hinted = await page.locator("#aud-hint").isVisible();
  if (!full && !hinted) {
    failures.push(`${label}: F neither fullscreened nor explained itself`);
  }
  if (full) await page.keyboard.press("f");
}

/** The presenter: current and next, notes, counter, clock and buttons. */
async function checkSlidesPresenter(page, context, label, failures) {
  const preview = await page.evaluate(async () => {
    const name = new URLSearchParams(window.location.search).get("asset") ?? "";
    const response = await fetch(`/asset/${encodeURIComponent(name)}.preview.json`);
    return response.json();
  });
  const total = preview.page_count;
  const count = () => page.locator("#pres-count").innerText();
  if ((await count()) !== `1 / ${total}`) {
    failures.push(`${label}: the counter is ${JSON.stringify(await count())}`);
  }
  const firstNote = preview.notes[0]?.text ?? "";
  if ((await page.locator("#pres-notes").innerText()) !== firstNote) {
    failures.push(`${label}: the first note is not shown`);
  }
  await page.keyboard.press("ArrowRight");
  if ((await count()) !== `2 / ${total}`) {
    failures.push(`${label}: ArrowRight left the counter at ${JSON.stringify(await count())}`);
  }
  if ((await page.locator("#pres-notes").innerText()) !== (preview.notes[1]?.text ?? "")) {
    failures.push(`${label}: the second note is not shown`);
  }
  const clock = await page.locator("#pres-clock").innerText();
  if (!/^\d\d:\d\d$/.test(clock)) {
    failures.push(`${label}: the clock reads ${JSON.stringify(clock)}`);
  }
  await page.keyboard.press("r");
  await page.click("#btn-black");
  if (!(await page.locator("#pres-black").isVisible())) {
    failures.push(`${label}: the black button did nothing`);
  }
  await page.click("#btn-black");
  const [popup] = await Promise.all([
    context.waitForEvent("page"),
    page.click("#btn-audience"),
  ]);
  await popup.waitForLoadState("load");
  if (!popup.url().includes("&role=audience")) {
    failures.push(`${label}: the audience button opened ${popup.url()}`);
  }
  await page.click("#btn-audience");
  await page.waitForTimeout(600);
  const full = await popup.evaluate(() => document.fullscreenElement !== null);
  const hinted = await popup.locator("#aud-hint").isVisible();
  if (!full && !hinted) {
    failures.push(`${label}: audience full screen did neither fullscreen nor explain`);
  }
  // Either window drives the others: the last slide lands in the audience.
  await page.keyboard.press("End");
  try {
    await popup.waitForFunction(
      (last) => document.getElementById("aud-img").src.endsWith(last),
      preview.pages[total - 1],
      { timeout: 3000 },
    );
  } catch {
    failures.push(`${label}: the audience did not follow to the last slide`);
  }
  await popup.close();
}

async function checkSlides(page, context, label, failures, suffix) {
  if (suffix === "") await checkSlidesDefault(page, context, label, failures);
  else if (suffix === "&role=audience") await checkSlidesAudience(page, label, failures);
  else await checkSlidesPresenter(page, context, label, failures);
}

async function runCase(browser, url, kind, testCase, failures, suffix = "", asset = null) {
  const { scheme, width, height } = testCase;
  const tag = assetTag(kind, asset);
  const label = `${kind}${roleTag(suffix)}${tag} ${scheme} ${width}x${height}`;
  const context = await browser.newContext({
    viewport: { width, height },
    colorScheme: scheme,
    deviceScaleFactor: 1,
    permissions: ["clipboard-read", "clipboard-write"],
  });
  const page = await context.newPage();
  watchPage(page, label, failures);
  await page.goto(`${assetUrlFor(url, asset)}${suffix}`, { waitUntil: "load" });
  await page.waitForTimeout(600); // canvases draw, images and fonts settle
  if (kind === "audio") {
    await checkAudioSeek(page, label, failures);
    await checkAudioTransport(page, label, failures);
  }
  if (kind === "cad") await checkCad(page, label, failures);
  if (kind === "document") await checkDocument(page, label, failures);
  if (kind === "generic") await checkGeneric(page, label, failures, asset);
  if (kind === "image") await checkImage(page, label, failures, asset);
  if (kind === "video") {
    if (String(asset).endsWith(".gif")) await checkVideoGif(page, label, failures);
    else await checkVideoClip(page, label, failures);
  }
  if (kind === "gallery") await checkGallery(page, label, failures);
  if (kind === "slides") await checkSlides(page, context, label, failures, suffix);
  const dir = path.join(ROOT, "viewers", "_examples", kind, "screens");
  mkdirSync(dir, { recursive: true });
  await page.screenshot({
    path: path.join(dir, `${scheme}-${width}x${height}${roleTag(suffix)}${tag}.png`),
    fullPage: true,
  });
  await context.close();
  console.log(`ok  ${label}`);
}

async function main() {
  const browser = await chromium.launch({
    executablePath: CHROME,
    headless: true,
    args: ["--autoplay-policy=no-user-gesture-required"],
  });
  const failures = [];
  try {
    for (const kind of KINDS) {
      const { child, url } = await startServer(kind);
      try {
        for (const suffix of suffixesFor(kind)) {
          for (const asset of assetsFor(kind)) {
            for (const testCase of CASES) {
              await runCase(browser, url, kind, testCase, failures, suffix, asset);
            }
          }
        }
      } finally {
        child.kill("SIGTERM");
      }
    }
  } finally {
    await browser.close();
  }
  if (failures.length > 0) {
    console.error(`\nFAIL (${failures.length}):`);
    for (const failure of failures) console.error(`  ${failure}`);
    process.exit(1);
  }
  console.log("\nPASS: no console errors, page errors or failed requests.");
}

await main();
