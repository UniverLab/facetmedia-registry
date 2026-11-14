/* Generic viewer: any preview's summary and fields, plus a branch for the text
   the record says it is. Plain text keeps its lines and numbers them, JSON is
   pretty-printed, subtitles become a time-and-text list, and ASCII art keeps
   its natural width and scrolls sideways instead of wrapping. Every branch
   carries a copy button. A mime none of those cover keeps the fields table and
   the link to the file: that is the fallback, not a failure. */

import { renderHeader } from "/kit/header.js";
import { assetUrl, loadAsset, showError } from "/kit/load.js";

const SUBTITLE_MIMES = new Set(["application/x-subrip", "text/vtt", "text/srt"]);

function scalar(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "number") return String(Math.round(value * 1000) / 1000);
  return String(value);
}

function fillFields(table, fields) {
  const body = table.querySelector("tbody");
  for (const [key, value] of Object.entries(fields ?? {})) {
    const row = document.createElement("tr");
    const name = document.createElement("th");
    name.scope = "row";
    name.textContent = key;
    const cell = document.createElement("td");
    cell.className = "num";
    cell.textContent = scalar(value);
    row.append(name, cell);
    body.append(row);
  }
}

/** Which branch this record asks for, or null for the fields-only fallback.

    ASCII art is text that says how wide it is. A contact-sheet record
    (image/png, image/svg+xml) carries `columns` too, but its bytes are a
    picture: it keeps the fields table and the link. */
function branchOf(record) {
  const mime = record.mime ?? "";
  if (mime === "text/plain" && typeof record.properties?.columns === "number") {
    return "ascii";
  }
  if (SUBTITLE_MIMES.has(mime)) return "cues";
  if (mime === "application/json") return "json";
  if (mime === "text/plain") return "text";
  return null;
}

function reveal(sectionId) {
  const section = document.getElementById(sectionId);
  section.hidden = false;
  return section;
}

function fillLines(list, lines) {
  for (const line of lines) {
    const item = document.createElement("li");
    item.textContent = line;
    list.append(item);
  }
}

function wireCopy(buttonId, text) {
  const button = document.getElementById(buttonId);
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "copied";
    } catch {
      button.textContent = "copy failed";
    }
  });
}

/* ---- the four text branches ---- */

function renderText(raw) {
  reveal("text-section");
  const lines = raw.replace(/\n$/, "").split("\n");
  fillLines(document.getElementById("lines"), lines);
  wireCopy("copy-text", raw);
}

function prettyJson(raw) {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw; // not JSON after all: the bytes are still worth reading
  }
}

function renderJson(raw) {
  const pretty = prettyJson(raw);
  reveal("json-section");
  document.getElementById("json").textContent = pretty;
  wireCopy("copy-json", pretty);
}

function parseCues(raw) {
  const cues = [];
  for (const block of raw.replace(/\r\n/g, "\n").split(/\n{2,}/)) {
    const lines = block.split("\n").filter((line) => line.trim() !== "");
    const arrow = lines.findIndex((line) => line.includes("-->"));
    if (arrow === -1) continue;
    const [start, end = ""] = lines[arrow].split("-->");
    const trimmedEnd = end.trim().split(/\s+/)[0];
    cues.push({
      time: `${start.trim()} --> ${trimmedEnd}`,
      text: lines.slice(arrow + 1).join(" ").trim(),
    });
  }
  return cues;
}

function renderCues(raw) {
  const cues = parseCues(raw);
  if (cues.length === 0) {
    renderText(raw); // a subtitle file in name only: read it as text
    return;
  }
  reveal("cues-section");
  const body = document.querySelector("#cues tbody");
  for (const cue of cues) {
    const row = document.createElement("tr");
    const time = document.createElement("td");
    time.className = "num";
    time.textContent = cue.time;
    const text = document.createElement("td");
    text.textContent = cue.text;
    row.append(time, text);
    body.append(row);
  }
  wireCopy("copy-cues", raw);
}

function renderAscii(raw) {
  reveal("ascii-section");
  document.getElementById("ascii").textContent = raw.replace(/\n+$/, "");
  wireCopy("copy-ascii", raw);
}

async function loadBranch(branch, name) {
  const response = await fetch(assetUrl(name));
  if (!response.ok) {
    showError(`missing ${name} (HTTP ${response.status})`);
    return;
  }
  const raw = await response.text();
  if (branch === "ascii") renderAscii(raw);
  else if (branch === "json") renderJson(raw);
  else if (branch === "cues") renderCues(raw);
  else renderText(raw);
}

const loaded = await loadAsset();
if (loaded) {
  const { name, record, preview } = loaded;
  renderHeader(document.getElementById("header"), record);
  document.getElementById("summary").textContent = preview.summary ?? "";
  fillFields(document.getElementById("fields"), preview.fields);
  const link = document.getElementById("asset-link");
  link.href = assetUrl(name);
  link.textContent = `open ${name}`;
  const branch = branchOf(record);
  if (branch !== null) {
    loadBranch(branch, name).catch((error) => showError(`cannot read ${name}: ${error.message}`));
  }
}
