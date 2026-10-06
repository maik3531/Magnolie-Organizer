"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { JSDOM } = require("jsdom");
for (const web of require("./web-test-roots")) for (const [start, later, expected] of [
  ["2026-01-31T12:00:00Z", "2026-02-03T12:00:00Z", "2026-02-03"],
  ["2026-12-31T12:00:00Z", "2027-01-02T12:00:00Z", "2027-01-02"]]) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, RealDate = w.Date; let now = RealDate.parse(start);
  w.Date = class extends RealDate { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } };
  w.setTimeout = w.setInterval = () => 0;
  w.__MAGNOLIE_BRUECKE__ = "test"; w.webkit = { messageHandlers: { test: { postMessage() {} } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
    w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    w.App.init({ neu: false, regional: { language: "en", timeZone: "UTC" }, daten: {} });
    const calendar = w.OrganizerTest.zustand().kalender;
    calendar.ansicht = "month";
    now = RealDate.parse(later); w.dispatchEvent(new w.Event("focus"));
    assert.equal(calendar.tag, expected);
    assert.equal(calendar.jahr, Number(expected.slice(0, 4)));
    assert.equal(calendar.monat, Number(expected.slice(5, 7)) - 1);
    calendar.tag = "2020-06-15";
    w.dispatchEvent(new w.Event("focus"));
    assert.equal(calendar.tag, "2020-06-15", "Same-day focus must not override deliberate browsing");
  } finally { w.close(); }
}
console.log("TRAY CURRENT DAY PASSED: multiple days, month and year boundaries");
