/* Post viewer: what went out, where, and in what state.

   The receipt keeps only the ids and URLs; the text and the media live in the
   kind's preview. The thread is drawn in the order the preview lists its
   posts, each with its text, a link to its public URL and its media, served
   from the receipt's directory. Señal marks only a verified `published` post:
   a draft, a private or a scheduled one is written plainly, and an `unknown`
   one says the post may exist and names the network to check. */

import { renderHeader } from "/kit/header.js";
import { assetUrl, loadAsset } from "/kit/load.js";

const VIDEO_SUFFIXES = new Set(["mov", "mp4", "webm"]);
const PUBLISHED = "published";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** A served media path: a rooted one is kept, a relative one is an asset. */
function imageRef(reference) {
  const text = String(reference);
  return text.startsWith("/") ? text : assetUrl(text);
}

/** Why a media file is a player rather than a still. */
function isVideoFile(reference) {
  const name = String(reference).toLowerCase().split(/[?#]/)[0];
  return VIDEO_SUFFIXES.has(name.slice(name.lastIndexOf(".") + 1));
}

function mediaNode(item) {
  const stage = element("div", "stage");
  if (isVideoFile(item.file)) {
    const video = document.createElement("video");
    video.src = imageRef(item.file);
    video.controls = true;
    video.preload = "metadata";
    video.setAttribute("aria-label", item.alt ?? item.file);
    stage.append(video);
  } else {
    const image = document.createElement("img");
    image.src = imageRef(item.file);
    image.alt = item.alt ?? "";
    image.loading = "lazy";
    image.decoding = "async";
    stage.append(image);
  }
  const figure = document.createElement("figure");
  figure.append(stage);
  if (item.alt) figure.append(element("figcaption", null, item.alt));
  return figure;
}

function urlNode(url, index) {
  const line = element("p");
  const link = element("a", "mono", String(url));
  link.href = String(url);
  link.target = "_blank";
  link.rel = "noopener";
  link.dataset.post = String(index);
  line.append(link);
  return line;
}

function postNode(post, index) {
  const article = element("article", "post");
  article.dataset.n = String(index);
  article.append(element("p", "text", post.text ?? ""));
  article.append(urlNode(post.url, index));
  const media = Array.isArray(post.media) ? post.media : [];
  for (const item of media) article.append(mediaNode(item));
  return article;
}

function renderThread(preview) {
  const thread = document.getElementById("thread");
  const posts = Array.isArray(preview.posts) ? preview.posts : [];
  posts.forEach((post, index) => {
    if (index > 0) thread.append(element("hr", "rule"));
    thread.append(postNode(post, index + 1));
  });
}

/** `✓ published` in Señal only when the record verified a published post;
    every other state is Hueso tenue, and unknown names the network to check. */
function stateNode(preview, record) {
  const verified = record?.verification?.status === "passed" && preview.state === PUBLISHED;
  const node = element("span");
  node.id = "state";
  if (verified) {
    node.className = "verdict passed";
    node.textContent = `✓ ${PUBLISHED}`;
    return node;
  }
  node.className = "muted mono";
  node.textContent = preview.state === "unknown"
    ? `unknown · the post may exist, check ${preview.network}`
    : String(preview.state ?? "unknown");
  return node;
}

function placeRow(list, term, value) {
  list.append(element("dt", null, term), element("dd", null, value));
}

function renderPlace(preview, record) {
  const list = document.getElementById("place");
  placeRow(list, "network", preview.network ?? "—");
  placeRow(list, "account", preview.account ?? "—");
  list.append(element("dt", null, "state"));
  const value = document.createElement("dd");
  value.append(stateNode(preview, record));
  list.append(value);
}

function main({ name, record, preview }) {
  renderHeader(document.getElementById("header"), record);
  document.getElementById("summary").textContent = preview.summary ?? "";
  renderPlace(preview, record);
  renderThread(preview);
  const receipt = document.getElementById("receipt-link");
  receipt.href = assetUrl(name);
  receipt.textContent = `open ${name}`;
}

// Boot last: every declaration above is initialized before it can run.
const loaded = await loadAsset();
if (loaded) main(loaded);
