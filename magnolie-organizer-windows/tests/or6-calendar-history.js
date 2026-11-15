"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const source = JSON.parse(fs.readFileSync(0, "utf8"));
const expected = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../contracts/or6-native-calendar-history.json"), "utf8")).expected;
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
let completed = 0;
const watchdog = setTimeout(() => { console.error("Calendar history stalled after", completed); process.exit(1); }, 40000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      const T = b.t, incoming = { ...source, icsQuelleId: "or6:calendar-history616" };
      assert.equal(T.mergeTermine([incoming]).neu, 1); assert.equal(T.mergeTermine([incoming]).doppelt, 1);
      const item = T.daten().termine[0];
      assert.equal(item.kategorien, expected.category); assert.equal(item.zeit, expected.startTime); assert.equal(item.endZeit, expected.endTime);
      const dates = value => Array.from(T.icsExpansion(value, Date.parse("2026-10-01T00:00:00Z"), Date.parse("2026-12-01T00:00:00Z")), x => x.datum);
      assert.deepEqual(dates(item), expected.dates);
      T.planeSpeichern();
      for (const date of [...expected.dates, "2026-10-25", "2026-11-15", "2026-11-21"]) {
        Object.assign(T.zustand().kalender, { jahr: 2026, monat: Number(date.slice(5, 7)) - 1, tag: date, ansicht: "day" });
        await T.wechsel("planer"); await T.wechsel("kalender");
        const nodes = [...b.w.document.querySelectorAll("#inhalt-links .tages-termin")];
        assert.equal(nodes.length, expected.dates.includes(date) ? 1 : 0, "History missing/duplicated/extrapolated on " + date);
        if (nodes.length) assert.ok(nodes[0].textContent.includes(expected.title));
      }
      const restored = T.normalisiere(JSON.parse(JSON.stringify(T.daten()))).termine[0];
      assert.deepEqual(dates(restored), expected.dates);
      for (const line of item.icsRoundtrip.filter(line => line.startsWith("X-MAGNOLIE-OR6-CALENDAR-TEMPLATE-"))) assert.ok(restored.icsRoundtrip.includes(line));
      item.titel = "Local history series title"; item.geaendert = Date.now();
      T.mergeTermine([incoming]); assert.equal(item.titel, "Local history series title"); assert.equal(T.daten().termine.length, 1);
      assert.deepEqual(dates(item), expected.dates);
      console.log("OR6 CALENDAR HISTORY PASSED:", web, "four exact days, neighbors, category/clocks, provenance restore and local-edit reimport"); completed++;
    } finally { b.w.close(); }
  }
  assert.equal(completed, harness.exports.roots.length);
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
