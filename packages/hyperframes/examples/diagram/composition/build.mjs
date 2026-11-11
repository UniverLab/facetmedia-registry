import { readFileSync, writeFileSync } from "node:fs";

// Mermaid writes ">" as "&gt;" inside <style>; browsers decode it, the
// HyperFrames CSS parser does not. Fix it there, then inline the SVG without
// its xmlns declarations (HTML5 does not need them, and the composition must
// hold no remote URL).
const svg = readFileSync(new URL("../diagram.svg", import.meta.url), "utf8")
  .replace(/<style>[\s\S]*?<\/style>/g, (style) => style.replaceAll("&gt;", ">"))
  .replace(/ xmlns(:[a-z]+)?="[^"]*"/g, "");
const template = readFileSync(new URL("index.tmpl", import.meta.url), "utf8");
writeFileSync(new URL("index.html", import.meta.url), template.replace("<!-- DIAGRAM -->", svg));
