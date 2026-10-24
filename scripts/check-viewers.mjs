#!/usr/bin/env node
/* Open every viewer example in light and dark at 1280x800 and 390x844, one
   case at a time, with the system Chrome: fail on any page error, console
   error, failed request or HTTP >= 400, exercise the interaction the viewer
   exists for (audio click-to-seek, the CAD view dialog), and save a
   screenshot of each case under viewers/_examples/<kind>/screens/
   (gitignored).

   Run by hand:  node scripts/check-viewers.mjs [kind ...]
   Needs playwright-core resolvable (npm i --prefix /tmp/opencode/pw
   playwright-core, then NODE_PATH=/tmp/opencode/pw/node_modules). */

import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CHROME = process.env.CHROME_PATH || "/usr/bin/google-chrome";
const KINDS = process.argv.slice(2).length > 0 ? process.argv.slice(2) : ["generic", "audio", "cad"];
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
