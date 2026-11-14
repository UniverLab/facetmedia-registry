#!/usr/bin/env node
/* Open every viewer example in light and dark at 1280x800 and 390x844, one
   case at a time, with the system Chrome: fail on any page error, console
   error, failed request or HTTP >= 400, exercise the interaction the viewer
   exists for (audio click-to-seek, the CAD view dialog, the document's page
   step and jump with its PDF link, the image enlargement, the gallery's filter
   and its open link and back button), and save a screenshot of each case under
   viewers/_examples/<kind>/screens/
   (gitignored).

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
  : ["generic", "audio", "cad", "document", "image", "video", "gallery"];
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

/** Clicking a view must open the enlargement dialog (and close it again). */
async function checkCadZoom(page, label, failures) {
  const view = page.locator(".views img").first();
  if ((await view.count()) === 0) {
    failures.push(`${label}: no view image`);
    return;
  }
  await view.click();
  const open = await page.evaluate(() => document.getElementById("zoom").open);
  if (!open) failures.push(`${label}: clicking a view did not open the enlargement`);
  await page.evaluate(() => document.getElementById("zoom").close());
}

/** Clicking the still must open the enlargement dialog (and close it again). */
async function checkImageZoom(page, label, failures) {
  const still = page.locator("#still");
  if ((await still.count()) === 0) {
    failures.push(`${label}: no still image`);
    return;
  }
  await still.click();
  const open = await page.evaluate(() => document.getElementById("zoom").open);
  if (!open) failures.push(`${label}: clicking the still did not open the enlargement`);
  await page.evaluate(() => document.getElementById("zoom").close());
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

async function runCase(browser, url, kind, testCase, failures) {
  const { scheme, width, height } = testCase;
  const label = `${kind} ${scheme} ${width}x${height}`;
  const context = await browser.newContext({
    viewport: { width, height },
    colorScheme: scheme,
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  watchPage(page, label, failures);
  await page.goto(url, { waitUntil: "load" });
  await page.waitForTimeout(600); // canvases draw, images and fonts settle
  if (kind === "audio") await checkAudioSeek(page, label, failures);
  if (kind === "cad") await checkCadZoom(page, label, failures);
  if (kind === "document") await checkDocument(page, label, failures);
  if (kind === "image") await checkImageZoom(page, label, failures);
  if (kind === "gallery") await checkGallery(page, label, failures);
  const dir = path.join(ROOT, "viewers", "_examples", kind, "screens");
  mkdirSync(dir, { recursive: true });
  await page.screenshot({
    path: path.join(dir, `${scheme}-${width}x${height}.png`),
    fullPage: true,
  });
  await context.close();
  console.log(`ok  ${label}`);
}

async function main() {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const failures = [];
  try {
    for (const kind of KINDS) {
      const { child, url } = await startServer(kind);
      try {
        for (const testCase of CASES) {
          await runCase(browser, url, kind, testCase, failures);
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
