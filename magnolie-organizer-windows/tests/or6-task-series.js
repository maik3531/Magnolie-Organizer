"use strict";
// Input comes from the actual OR6 reader, not hand-written destination records.
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const { webcrypto } = require("node:crypto");
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const output = [];
async function main() {
for (const web of [path.resolve(__dirname, "../../magnolie-organizer/web"), path.resolve(__dirname, "../app/web")]) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://or6-task.test/", pretendToBeVisual: true });
  try {
    const w = dom.window;
    Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
    if (w.document.readyState === "loading") await new Promise(resolve => w.document.addEventListener("DOMContentLoaded", resolve, { once: true }));
    await new Promise(resolve => w.setTimeout(resolve, 0));
    for (const test of cases) {
      w.App.init({ daten: {}, neu: true, regional: { language: "en", timeZone: "UTC" } });
      const T = w.OrganizerTest, incomingItems = (test.items || [test.item]).map(item => ({ ...item, icsQuelleId: "or6:synthetic567" }));
      const incoming = incomingItems[0], initialDone = incomingItems.filter(item => item.erledigt).length;
      assert.equal(T.mergeAufgaben(incomingItems).neu, incomingItems.length, "Original task series and its status exceptions must import once");
      const first = T.daten().aufgaben[0].uid;
      assert.equal(T.mergeAufgaben(incomingItems).doppelt, incomingItems.length, "Reimport must recognize the same source series");
      assert.equal(T.daten().aufgaben.length, incomingItems.length, "Task series was duplicated/flattened");
      assert.equal(T.daten().aufgaben[0].uid, first, "Reimport changed internal source-bound identity");
      assert.equal(T.daten().aufgaben[0].icsImportUid, incoming.uid, "Original native definition identity was lost");
      const series = Array.from(T.icsSerienAbstimmen(T.daten().aufgaben));
      assert.equal(series.length, incomingItems.length);
      const dates = Array.from(T.icsExpansion(series[0], Date.parse("2026-12-01T00:00:00Z"), Date.parse("2027-01-01T00:00:00Z"), true), value => value.faellig);
      assert.deepEqual(dates, test.dates, "Actual task display expansion lost original due dates");
      for (const date of test.dates) assert.equal(T.icsNaechsteAufgabe(series[0], date).faellig, date, "Task list next-occurrence selection lost a due date");
      await T.wechsel("kalender");
      await T.wechsel("aufgaben");
      let button = w.document.querySelector(".zeile .check");
      assert.ok(button, "Imported recurring task has no actual task-list completion control: " + JSON.stringify({ name: test.name, section: T.zustand().sektion,
        count: T.daten().aufgaben.length, text: w.document.querySelector("#seiten")?.textContent.slice(0, 500) }));
      for (let count = 0; button.disabled && count < 100; count++) {
        await new Promise(resolve => w.setTimeout(resolve, 10));
        button = w.document.querySelector(".zeile .check");
        assert.ok(button, "Task control disappeared during completion preparation");
      }
      assert.equal(button.disabled, false, "Original recurring task completion admission never became ready");
      button.click();
      const master = T.daten().aufgaben.find(item => item.uid === first);
      assert.equal(master.erledigt, false, "Completing one occurrence completed the entire series");
      assert.equal(T.daten().aufgaben.filter(item => item.erledigt).length, initialDone + 1, "Completion did not retain original and newly completed occurrences");
      assert.ok(T.daten().aufgaben.some(item => item.erledigt && item.faellig === test.dates[0]));
      const remaining = () => Array.from(T.icsExpansion(master, Date.parse("2026-12-01T00:00:00Z"), Date.parse("2027-01-01T00:00:00Z"), true), value => value.faellig);
      assert.deepEqual(remaining(), test.dates.slice(1), "Single-occurrence completion lost future tasks");
      T.mergeAufgaben(incomingItems);
      assert.equal(T.daten().aufgaben.length, incomingItems.length + 1, "Original reimport duplicated or discarded a local occurrence edit");
      assert.deepEqual(remaining(), test.dates.slice(1), "Reimport undid the user's completed occurrence");
      output.push({ web: path.relative(path.resolve(__dirname, "../.."), web), name: test.name, dates, reimport: "unchanged", completion: "one occurrence, future dates retained" });
    }
  } finally { dom.window.close(); }
}
process.stdout.write(JSON.stringify(output));
}
main().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
