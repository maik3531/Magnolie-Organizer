"use strict";
// Actual reader output; independently preselected original-program expectations.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const contract = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../contracts/or6-native-task-scopes.json"), "utf8"));
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const from = Date.parse("2026-12-01T00:00:00Z"), through = Date.parse("2027-01-01T00:00:00Z");
(async () => {
  for (const web of harness.exports.roots) for (const test of cases) {
    const b = await harness.exports.boot(web, {});
    try {
      const T = b.t, incoming = test.items.map(item => ({ ...item, icsQuelleId: "or6:scoped567" }));
      assert.equal(T.mergeAufgaben(incoming).neu, 3);
      assert.equal(T.mergeAufgaben(incoming).doppelt, 3);
      const check = tasks => {
        const dates = new Map();
        for (const item of T.icsSerienAbstimmen(tasks)) for (const value of T.icsExpansion(item, from, through, true)) {
          assert.ok(!dates.has(value.faellig), "Reused native index duplicated an occurrence");
          dates.set(value.faellig, { completed: item.erledigt, category: item.kategorien || "" });
        }
        assert.deepEqual([...dates.keys()].sort(), contract.expected.datesByFile[test.name]);
        for (const [date, value] of dates) {
          assert.equal(value.completed, date === "2026-12-01");
          assert.equal(value.category, contract.expected.categoryByDate[date]);
        }
      };
      check(T.daten().aufgaben);
      check(T.normalisiere(JSON.parse(JSON.stringify(T.daten()))).aufgaben);
      T.planeSpeichern(); await T.wechsel("kalender"); await T.wechsel("aufgaben");
      const category = T.daten().aufgaben.find(item => item.kategorien === "OR6-567 Alpha");
      assert.ok(category && !category.erledigt && category.faellig === "2026-12-08");
      const row = b.w.document.querySelector('[data-fokus="aufgabe:' + category.id + '"]')?.closest(".zeile");
      assert.ok(row, "Actual task list lost the single-category occurrence");
      row.querySelector(".haupt").click();
      assert.equal(b.w.document.querySelector("#aufgabe-kategorien")?.value, "OR6-567 Alpha", "Task editor lost original per-occurrence category");
      const button = b.w.document.querySelector('[data-fokus="aufgabe-status:' + category.id + '"]'); assert.ok(button);
      for (let n = 0; button.disabled && n < 100; n++) await new Promise(resolve => b.w.setTimeout(resolve, 10));
      assert.equal(button.disabled, false); button.click();
      assert.equal(category.erledigt, true, "Actual category-exception completion did not persist");
      const master = T.daten().aufgaben.find(item => !(item.icsRoundtrip || []).some(line => line.startsWith("RECURRENCE-ID:")));
      assert.equal(master.erledigt, false, "Completing the category exception completed its parent series");
      const remaining = () => Array.from(T.icsExpansion(master, from, through, true), value => value.faellig);
      assert.deepEqual(remaining(), contract.expected.datesByFile[test.name].filter(date => date >= "2026-12-15"));
      T.mergeAufgaben(incoming);
      assert.equal(T.daten().aufgaben.length, 3); assert.equal(category.erledigt, true);
      assert.deepEqual(remaining(), contract.expected.datesByFile[test.name].filter(date => date >= "2026-12-15"));
      console.log("OR6 TASK SCOPES PASSED:", web, test.name, "exact dates/categories/status, restore, UI completion and reimport");
    } finally { b.w.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
