"use strict";
// Refs #720. Drive the actual notes list in both desktop source trees.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { webcrypto } = require("node:crypto");
const { JSDOM } = require("jsdom");

const roots = process.argv[2] === "windows" ? ["../../magnolie-organizer-windows/app/web"]
  : ["../web", "../../magnolie-organizer-windows/app/web"];
const probe = fs.readFileSync(path.join(__dirname, "notes-date-search-probe.js"), "utf8");

async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://synthetic-notes.test.invalid/", pretendToBeVisual: true
  });
  const w = dom.window;
  try {
    w.setTimeout = () => 1; w.clearTimeout = () => {}; w.setInterval = () => 0;
    w.requestAnimationFrame = () => 0;
    w.HTMLElement.prototype.scrollIntoView = () => {};
    w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
    Object.defineProperty(w, "crypto", { value: webcrypto });
    w.__MAGNOLIE_BRUECKE__ = "test";
    w.webkit = { messageHandlers: { test: { postMessage: () => {} } } };
    for (const script of ["normative-timezones.js", "i18n.js", "zeichenblatt.js", "appearance.js", "anwendung.js"])
      w.eval(fs.readFileSync(path.join(web, script), "utf8"));
    await new Promise(resolve => setImmediate(resolve));
    const result = JSON.parse(w.eval(probe + "\nJSON.stringify(notesDateSearchProbe());"));
    assert.equal(result.checks, 30);
    assert.deepEqual(result.errors, [], web);
  } finally { w.close(); }
  console.log(`PASS ${path.relative(process.cwd(), web)}: actual notes search in days and notebook views`);
}

(async () => { for (const root of roots) await check(path.resolve(__dirname, root)); })().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
