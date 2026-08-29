"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function hasFiles(directory, files) {
  return files.every((file) => fs.existsSync(path.join(directory, file)));
}

function sourceFiles(directory, relative = "") {
  return fs.readdirSync(path.join(directory, relative), { withFileTypes: true })
    .flatMap((entry) => {
      const name = path.join(relative, entry.name);
      return entry.isDirectory() ? sourceFiles(directory, name) : [name];
    });
}

function selectHandbookWeb(root, requiredFiles) {
  const configured = process.env.MAGNOLIE_HANDBOOK_WEB;
  const canonical = path.resolve(root, "..", "magnolie-handbuch-stamm", "web");
  const bundled = path.join(root, "shared", "magnolie-handbuch-stamm", "web");
  if (configured) {
    const selected = path.resolve(configured);
    assert.ok(hasFiles(selected, requiredFiles),
      `MAGNOLIE_HANDBOOK_WEB ist unvollständig: ${selected}`);
    return { directory: selected, label: `configured ${selected}` };
  }
  if (hasFiles(canonical, requiredFiles)) return { directory: canonical, label: `canonical ${canonical}` };

  assert.ok(hasFiles(bundled, requiredFiles), `Gebündelte Handbuchquelle fehlt: ${bundled}`);
  if (hasFiles(canonical, ["index.html", "inhalt.js"])) {
    for (const relative of sourceFiles(canonical)) {
      const bundledFile = path.join(bundled, relative);
      assert.ok(fs.existsSync(bundledFile), `Gebündelte Handbuchquelle ist unvollständig: ${relative}`);
      assert.deepStrictEqual(fs.readFileSync(bundledFile), fs.readFileSync(path.join(canonical, relative)),
        `Gebündelte Handbuchquelle ist gegenüber der kanonischen Quelle veraltet: ${relative}`);
    }
    return { directory: bundled, label: `bundled canonical sync ${bundled}` };
  }
  return { directory: bundled, label: `bundled standalone ${bundled}` };
}

function canonicalPageIds(directory) {
  const i18n = { registerBook() {}, locale: () => "en" };
  const context = { window: { MagnolieI18n: i18n }, MagnolieI18n: i18n };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(directory, "inhalt.js"), "utf8"), context);
  const ids = context.window.HANDBUCH_SEITEN.map((page) => page.id);
  assert.strictEqual(new Set(ids).size, ids.length, "Kanonische Seiten-IDs sind nicht eindeutig");
  return ids;
}

module.exports = { canonicalPageIds, selectHandbookWeb };
