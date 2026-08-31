/* Source hygiene checks: no leaked editing artefacts, no dangling references.

   These guard the class of defect that slipped through when web/platform.js was
   removed: the removed line was replaced by a stray ">>>>>>>" marker instead of
   being deleted. That corrupted debian/install (package file list), index.html
   (visible text in the footer) and stil.css (the ".schritte" rule was swallowed
   by the invalid selector, so every step list lost its styling) -- and every
   existing test still reported green, because none of them look at this. */
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const ROOT = path.resolve(__dirname, "..");
const WEB = process.env.MAGNOLIE_HANDBUCH_WEB || path.join(ROOT, "web");

for (const required of ["kaffee-qr.mga", "maik-walter.mga"]) {
  assert.ok(fs.existsSync(path.join(WEB, required)), `protected asset missing: ${required}`);
}
for (const forbidden of ["kaffee-qr.png", "maik-walter.jpg"]) {
  assert.ok(!fs.existsSync(path.join(WEB, forbidden)), `plaintext personal asset present: ${forbidden}`);
}

/* ---------------------------------------------------------------- helpers */

const TEXT_SUFFIXES = new Set([".js", ".css", ".html", ".py", ".po", ".pot",
  ".md", ".sh", ".txt", ".desktop", ".in", ".1"]);
const SKIP_DIRS = new Set(["i18n", "schriften", "node_modules", ".git"]);

function textFiles(dir, found = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith(".")) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name)) continue;
      textFiles(full, found);
    } else if (TEXT_SUFFIXES.has(path.extname(entry.name)) ||
               path.dirname(full).endsWith("debian") ||
               path.basename(full) === "magnolie-handbuch") {
      found.push(full);
    }
  }
  return found;
}

const relative = (file) => path.relative(ROOT, file).split(path.sep).join("/");

/* ------------------------------------------- 1) no conflict/edit markers */

const MARKERS = [/^<{7}(\s|$)/, /^={7}$/, /^>{7}(\s|$)/];
const offenders = [];

for (const file of textFiles(ROOT)) {
  let lines;
  try {
    lines = fs.readFileSync(file, "utf8").split("\n");
  } catch {
    continue;
  }
  lines.forEach((line, index) => {
    const bare = line.replace(/\r$/, "");
    if (MARKERS.some((marker) => marker.test(bare))) {
      offenders.push(`${relative(file)}:${index + 1}: ${bare.slice(0, 40)}`);
    }
  });
}

assert.deepStrictEqual(offenders, [],
  "leaked conflict/edit markers in the source tree:\n  " + offenders.join("\n  "));

/* --------------------------------- 2) every asset index.html asks for exists */

const html = fs.readFileSync(path.join(WEB, "index.html"), "utf8");
const referenced = [];
for (const match of html.matchAll(/<script[^>]+src="([^"]+)"/g)) referenced.push(match[1]);
for (const match of html.matchAll(/<link[^>]+href="([^"]+)"/g)) referenced.push(match[1]);

const missing = referenced
  .filter((reference) => !/^(https?:)?\/\//.test(reference))
  .filter((reference) => !fs.existsSync(path.join(WEB, reference)));

assert.deepStrictEqual(missing, [],
  "index.html references files that do not exist: " + missing.join(", "));

/* ------------------------- 3) every debian/install entry resolves to a file */

const GENERATED = [/^locale\//, /^web\/i18n\//];
const installLines = fs.readFileSync(path.join(ROOT, "debian", "install"), "utf8")
  .split("\n").map((line) => line.trim()).filter(Boolean);

const unresolved = [];
for (const line of installLines) {
  const source = line.split(/\s+/)[0];
  assert.ok(!/[<>=]{3}/.test(source),
    `debian/install carries a leaked marker instead of a path: ${line}`);
  if (GENERATED.some((pattern) => pattern.test(source))) continue;

  const directory = path.join(ROOT, path.dirname(source));
  const pattern = path.basename(source);
  let hit = false;
  if (pattern.includes("*")) {
    const expression = new RegExp("^" + pattern.split("*")
      .map((part) => part.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join(".*") + "$");
    hit = fs.existsSync(directory) &&
      fs.readdirSync(directory).some((name) => expression.test(name));
  } else {
    hit = fs.existsSync(path.join(ROOT, source));
  }
  if (!hit) unresolved.push(source);
}

assert.deepStrictEqual(unresolved, [],
  "debian/install lists paths that match nothing: " + unresolved.join(", "));

/* ------------------------------------ 4) the CSS rules the book relies on */

const css = fs.readFileSync(path.join(WEB, "stil.css"), "utf8");
for (const selector of [".schritte", ".merke", ".achtung", ".beispiel", ".technik"]) {
  const expression = new RegExp("(^|\\})\\s*" +
    selector.replace(".", "\\.") + "\\s*(,[^{]*)?\\{", "m");
  assert.ok(expression.test(css),
    `stil.css lost its "${selector}" rule -- check for a broken selector above it`);
}

console.log(`SOURCE HYGIENE PASSED (${installLines.length} install entries; ` +
  `${referenced.length} referenced assets)`);
