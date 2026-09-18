"use strict";
// Pure source functions and stdin fixtures, no DOM/bridge/transport.
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const assert = require("node:assert/strict");
const vectors = JSON.parse(fs.readFileSync(0, "utf8"));
for (const web of [path.resolve(__dirname, "../app/web"), path.resolve(__dirname, "../../magnolie-organizer/web")]) {
  const source = fs.readFileSync(path.join(web, "anwendung.js"), "utf8");
  const start = source.indexOf("  // BEGIN GENERATED PHONE METADATA");
  const end = source.indexOf("\n  }", source.indexOf("  function telefonSchluessel(", start)) + 4;
  const c = vm.createContext({});
  vm.runInContext(source.slice(start, end), c);
  for (const { country, number, expected } of vectors)
    assert.equal(c.telefonSchluessel(number, country), expected, country + " " + number);
  console.log("PASS " + vectors.length + " libphonenumber vectors " + web);
}
