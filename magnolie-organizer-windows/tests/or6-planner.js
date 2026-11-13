"use strict";
// Actual native-reader output on stdin; independent original-program expectations.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const contract = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../contracts/or6-native-planner.json"), "utf8"));
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      const incoming = input.map(item => ({ ...item, icsQuelleId: "or6:independent-planner-568" }));
      assert.equal(b.t.mergeTermine(incoming).neu, 17);
      assert.equal(b.t.mergeTermine(incoming).doppelt, 17, "Native reimport duplicated planner entries");
      assert.equal(b.t.daten().termine.length, 17);
      b.t.planeSpeichern(); // The actual post-import caller also invalidates display indices here.
      const year = b.t.planerKalenderModell(2026), html = b.t.planerDruckSeite(year), ods = b.t.planerOdsNutzlast(year);
      for (const expected of contract.expected) {
        const item = b.t.daten().termine.find(item => item.titel === expected.title);
        assert.ok(item); assert.equal(item.kategorien, expected.category); assert.equal(item.akzentFarbe, expected.color);
        const day = Number(expected.date.slice(8)) - 1;
        assert.ok(year.zeilen[day][11].akzente.some(value => value.text === expected.title && value.farbe === expected.color),
          "Existing annual planner lost imported category color: " + JSON.stringify({ expected, item, cell: year.zeilen[day][11] }));
        assert.ok(html.includes("background:" + expected.color + ";color:"), "Existing planner print lost native color");
        assert.ok(ods.inhalte[day][11].eintraege.some(value => value.text === expected.title && value.farbe === expected.color),
          "Existing planner spreadsheet lost native color");
        Object.assign(b.t.zustand().kalender, { jahr: 2026, monat: 11, tag: expected.date, ansicht: "day" });
        await b.t.wechsel("planer"); await b.t.wechsel("kalender");
        assert.equal(b.w.document.querySelector(".tages-termin")?.dataset.akzentFarbe, expected.color,
          "Actual calendar view did not draw native color " + expected.title);
      }
      const first = b.t.daten().termine.find(item => item.titel === "OR6-568 A04 original");
      first.akzentFarbe = "#112233"; first.geaendert = Date.now();
      b.t.mergeTermine(incoming);
      assert.equal(first.akzentFarbe, "#112233", "Reimport overwrote a local color choice");
      assert.equal(b.t.daten().termine.length, 17);
      const saved = JSON.stringify(b.t.daten());
      const restored = b.t.normalisiere(JSON.parse(saved));
      assert.equal(restored.termine.find(item => item.titel === "OR6-568 A04 original").akzentFarbe, "#112233");
      console.log("OR6 PLANNER PASSED:", web, "17 categories/colors, actual calendar/annual planner/print/ODS/reimport/restore");
    } finally { b.w.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
