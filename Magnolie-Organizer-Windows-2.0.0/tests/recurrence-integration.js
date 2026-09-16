"use strict";
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const input = JSON.parse(fs.readFileSync(0, "utf8")), result = [];
for (const web of [path.resolve(__dirname, "../../magnolie-organizer-2.0.0/web"), path.resolve(__dirname, "../app/web")]) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), { runScripts: "outside-only", url: "https://recurrence.test/", pretendToBeVisual: true });
  const w = dom.window;
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
  w.document.dispatchEvent(new w.Event("DOMContentLoaded", { bubbles: true }));
  const output = [];
  for (const test of input) {
    const task = !!test.task, field = task ? "aufgaben" : "termine";
    if (test.expectedError) {
      w.App.init({ daten: {}, neu: true, regional: { language: "en", timeZone: test.zone } });
      const items = w.OrganizerTest.normalisiere({ [field]: test.items })[field];
      assert.ok(items.length, "Unresolved input was discarded");
      assert.throws(() => { for (const item of items) w.OrganizerTest.icsExpansion(item, Date.parse(test.lower), Date.parse(test.upper), task); }, undefined, test.name);
      output.push({ name: test.name, error: true }); continue;
    }
    w.App.init({ daten: { [field]: test.items, einstellungen: { regional: { timeZone: test.zone } } }, neu: true, regional: { language: "en", timeZone: test.zone } });
    const T = w.OrganizerTest, items = Array.from(T.icsSerienAbstimmen(T.daten()[field]));
    const values = items.flatMap(item => Array.from(T.icsExpansion(item, Date.parse(test.lower), Date.parse(test.upper), task) || []));
    const formatted = values.map(v => {
      const start = (task ? v.startDatum : v.datum) + "T" + ((task ? v.startZeit : v.zeit) || "00:00").padEnd(8, ":00");
      const end = new Date((task ? v.faellig : v.endDatum) + "T" + ((task ? v.faelligZeit : v.endZeit) || "00:00") + "Z");
      if (!task && !v.zeit) end.setUTCDate(end.getUTCDate() + 1);
      return start + "/" + end.toISOString().slice(0, 19);
    }).sort();
    assert.deepEqual(formatted, test.expected, test.name + " expansion " + web);
    if (test.expectedTitles) {
      const ordered = values.slice().sort((a, b) => a.icsStartUtc - b.icsStartUtc);
      assert.deepEqual(ordered.map(v => v.titel), test.expectedTitles, test.name + " inherited summary");
      assert.deepEqual(ordered.map(v => v.ort), test.expectedLocations, test.name + " inherited location");
    }
    if (test.nextFrom) {
      const next = T.icsNaechsteAufgabe(items[0], test.nextFrom);
      assert.ok(next, test.name + " next occurrence beyond one year");
      assert.equal(next.startDatum, test.expected[0].slice(0, 10));
    }
    if (task) {
      for (const expected of test.expected) {
        const [start, end] = expected.split("/");
        const next = T.icsNaechsteAufgabe(items[0], end.slice(0, 10));
        assert.equal(next.startDatum + "T" + next.startZeit.padEnd(8, ":00"), start, "Task list source start");
        assert.equal(next.faellig + "T" + next.faelligZeit.padEnd(8, ":00"), end, "Task list independent due");
      }
    }
    if (!task && !test.oracle) {
      const shown = new Map();
      for (let day = Date.parse(test.lower); day <= Date.parse(test.upper); day += 86400000) {
        for (const v of T.termineAm(new Date(day).toISOString().slice(0, 10), true)) {
          if (v.icsStartUtc >= Date.parse(test.lower) && v.icsStartUtc <= Date.parse(test.upper)) shown.set(v.id + ":" + v.icsOccurrence, v);
        }
      }
      assert.equal(shown.size, test.expected.length, test.name + " calendar display " + web);
      if (test.overlapDate) assert.equal(T.termineAm(test.overlapDate, true).length, 1, "Long RDATE PERIOD overlap");
    }
    output.push({ name: test.name, values: formatted });
  }
  result.push(output); dom.window.close();
}
process.stdout.write(JSON.stringify(result));
