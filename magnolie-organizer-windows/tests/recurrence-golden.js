"use strict";
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const internal = path.join(__dirname, "fixtures/recurrence-rfc-oracle.json");
const fixture = fs.existsSync(internal) ? internal :
  path.resolve(__dirname, "../../magnolie-organizer/pruefungen/fixtures/recurrence-rfc-oracle.json");
const matrix = JSON.parse(fs.readFileSync(fixture, "utf8"));
const web = path.resolve(__dirname, "../app/web");
const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"),
  { runScripts: "outside-only", url: "https://recurrence.test/", pretendToBeVisual: true });
try {
  const w = dom.window;
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
  w.App.init({ daten: {}, neu: true, regional: { language: "en", timeZone: "UTC" } });
  assert.equal(matrix.golden.cases, 448);
  assert.equal(matrix.golden.ruleSha256.length, matrix.rules.length);
  let count = 0;
  for (const [index, rule] of matrix.rules.entries()) {
    const group = [];
    for (const anchor of matrix.anchors) for (const ending of matrix.endings) {
      const text = rule + ending;
      const item = { uid: "packaged-oracle-" + count++, icsRoundtrip: [
        "DTSTART:" + anchor.replaceAll("-", "").replaceAll(":", "") + "Z",
        "DURATION:PT1H", "RRULE:" + text + (ending.includes("UNTIL=") ? "Z" : "")
      ] };
      const result = w.OrganizerTest.icsExpansion(item, Date.parse(matrix.lower + "Z"), Date.parse(matrix.upper + "Z"), false);
      assert.ok(Array.isArray(result), "Golden replay must not accept pending/partial results");
      const values = Array.from(result, value => new Date(value.icsStartUtc).toISOString().slice(0, 19));
      group.push([anchor, text, matrix.lower, matrix.upper, values]);
    }
    assert.equal(crypto.createHash("sha256").update(JSON.stringify(group), "ascii").digest("hex"),
      matrix.golden.ruleSha256[index], rule);
  }
  assert.equal(count, matrix.golden.cases);
  console.log("PACKAGED WINDOWS RECURRENCE GOLDENS PASSED (448 cases; no dateutil or Linux runtime required)");
} finally { dom.window.close(); }
