"use strict";
const assert = require("node:assert/strict"), vm = require("node:vm");
const { JSDOM } = require("jsdom");
const { pageIds } = require("./handbook-source");
const expected = ["first", "second"];
const foreign = vm.runInNewContext('[{id:"first"},{id:"second"}]');
assert.notEqual(Object.getPrototypeOf(foreign), Array.prototype);
assert.deepEqual(pageIds(foreign), expected);
const dom = new JSDOM("", { runScripts: "outside-only" });
try {
  assert.deepEqual(pageIds(dom.window.eval('[{id:"first"},{id:"second"}]')), expected);
} finally { dom.window.close(); }
for (const pages of [[{ id: "second" }, { id: "first" }], [{ id: "first" }],
  [{ id: "first" }, { id: "second" }, { id: "extra" }]]) {
  assert.throws(() => assert.deepEqual(pageIds(pages), expected), "ID order and exact page membership remain mandatory");
}
for (const pages of [[{ id: "first" }, { id: "first" }], [{ id: "" }],
  [{ id: 1 }], [null], { 0: { id: "first" }, length: 1 }]) {
  assert.throws(() => pageIds(pages), /Seiten|Seite|Liste/);
}
console.log("Handbook page-ID realm cases passed; exact order, membership, unique IDs and ID types remain mandatory.");
