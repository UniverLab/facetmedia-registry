import { readFileSync, writeFileSync } from "node:fs";

const bocas = JSON.parse(readFileSync(new URL("../bocas.json", import.meta.url), "utf8"));
const template = readFileSync(new URL("index.tmpl", import.meta.url), "utf8");
writeFileSync(
  new URL("index.html", import.meta.url),
  template.replace("/* BOCAS */[]", JSON.stringify(bocas.mouthCues)),
);
