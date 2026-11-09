"use strict";
// Refs #446: declaration parity only; native engine checks remain separate.
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const CSSOM = require("rrweb-cssom");
const root = path.resolve(__dirname, "../..");
let reference;
for (const relative of ["magnolie-organizer/web/stil.css", "magnolie-organizer-windows/app/web/stil.css"]) {
  const source = fs.readFileSync(path.join(root, relative), "utf8");
  const sheet = CSSOM.parse(source), selected = [];
  function visit(rules) {
    for (const rule of rules) {
      if (rule.cssRules) visit(rule.cssRules);
      if (!rule.style || !rule.style.getPropertyValue("user-select")) continue;
      const value = rule.style.getPropertyValue("user-select");
      assert.equal(rule.style.getPropertyValue("-webkit-user-select"), value, rule.selectorText);
      const keys = Array.from({ length: rule.style.length }, (_, index) => rule.style[index]);
      assert.ok(keys.indexOf("-webkit-user-select") < keys.indexOf("user-select"), rule.selectorText);
      assert.ok(!/(^|,)\s*(?:\*|input|textarea|body|html)\s*(?:,|$)/.test(rule.selectorText), "No new global editor selection suppression");
      selected.push([rule.selectorText, value]);
    }
  }
  visit(sheet.cssRules);
  assert.equal(selected.length, 9, "All existing explicit selection policies covered");
  assert.equal(selected.filter(([, value]) => value === "text").length, 2);
  if (reference) assert.deepEqual(selected, reference);
  reference = selected;
  const fallbackSheet = CSSOM.parse(source.replace(/background:\s*color-mix\([^;]+;/g, ""));
  const find = (parsed, selector) => parsed.cssRules.find(rule => rule.selectorText === selector).style;
  for (const selector of [".zyklus-schnellknopf", ".schicht-marke", ".muell-marke", ".pm-anlass"]) {
    const expected = selector === ".pm-anlass" ? "white" : "var(--papier)";
    const rule = source.match(new RegExp(selector.replace(".", "\\.") + "\\s*\\{([^}]+)\\}"))[1];
    assert.ok(rule.indexOf("background: " + expected + ";") < rule.indexOf("background: color-mix("));
    assert.match(find(sheet, selector).getPropertyValue("background"), /^color-mix\(/, "Modern color remains authoritative");
    assert.equal(find(fallbackSheet, selector).getPropertyValue("background"), expected);
  }
  for (const selector of [".zyklus-schnellknopf.aktiv", ".pm-feiertag", ".pm-ferien", ".pm-urlaub"]) {
    assert.equal(find(sheet, selector).cssText, find(fallbackSheet, selector).cssText, "Active/semantic markers unchanged");
  }
  console.log("PASS parsed selection declaration parity:", relative);
}
