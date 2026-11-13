"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const expected = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../contracts/or6-native-appointment-categories.json"), "utf8")).expected;
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
let completed = 0;
const watchdog = setTimeout(() => { console.error("Appointment category test stalled after", completed); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) for (const test of cases) {
    const b = await harness.exports.boot(web, {});
    try {
      const T = b.t, input = { ...test.item, icsQuelleId: "or6:category613" };
      assert.equal(T.mergeTermine([input]).neu, 1); assert.equal(T.mergeTermine([input]).doppelt, 1);
      const item = T.daten().termine[0]; assert.equal(item.kategorien, expected.category);
      assert.equal(item.akzentFarbe, "", "Source category was guessed into a native color");
      T.daten().einstellungen.kalender.kategorieFarben = [{ name: expected.category, farbe: "#123456" }];
      T.planeSpeichern();
      const year = T.planerKalenderModell(2026), ods = T.planerOdsNutzlast(year), print = T.planerDruckSeite(year);
      for (const date of [...expected.datesByFile[test.name], "2026-10-23", "2026-10-25", "2026-11-08"]) {
        const day = Number(date.slice(8)) - 1, month = Number(date.slice(5, 7)) - 1, present = expected.datesByFile[test.name].includes(date);
        const matches = value => value.text.endsWith(expected.title) && value.farbe === "#123456";
        assert.equal(year.zeilen[day][month].akzente.some(matches), present, "Annual category palette/date mismatch");
        assert.equal(ods.inhalte[day][month].eintraege.some(matches), present, "ODS category palette/date mismatch");
        Object.assign(T.zustand().kalender, { jahr: 2026, monat: month, tag: date, ansicht: "day" });
        await T.wechsel("planer"); await T.wechsel("kalender");
        const nodes = [...b.w.document.querySelectorAll("#inhalt-links .tages-termin")].filter(node => node.textContent.includes(expected.title));
        assert.equal(nodes.length, present ? 1 : 0, "Actual selected-day view lost or duplicated category appointment");
        if (present) assert.equal(nodes[0].dataset.akzentFarbe, "#123456");
      }
      assert.ok(print.includes("background:#123456;color:"));
      const restored = T.normalisiere(JSON.parse(JSON.stringify(T.daten())));
      assert.equal(restored.termine[0].kategorien, expected.category);
      assert.equal(restored.einstellungen.kalender.kategorieFarben[0].farbe, "#123456");
      item.kategorien = "Local category"; item.geaendert = Date.now();
      T.mergeTermine([input]); assert.equal(T.daten().termine.length, 1); assert.equal(item.kategorien, "Local category");
      console.log("OR6 APPOINTMENT CATEGORIES PASSED:", web, test.name, "calendar/palette/year/ODS/print/restore/local-edit reimport"); completed++;
    } finally { b.w.close(); }
  }
  assert.equal(completed, harness.exports.roots.length * cases.length);
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
