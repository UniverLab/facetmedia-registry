import { readFileSync, writeFileSync } from "node:fs";

const template = readFileSync(new URL("index.tmpl", import.meta.url), "utf8");
writeFileSync(new URL("index.html", import.meta.url), template);
