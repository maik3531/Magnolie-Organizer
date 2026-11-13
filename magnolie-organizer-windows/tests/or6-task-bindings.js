"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const contract = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../contracts/or6-native-task-bindings.json"), "utf8"));
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
// Keep each edition's DOM/crypto/runtime lifecycle in its own process. Never
// accept a silently abandoned async run as successful coverage of both roots.
if (!process.env.MAGNOLIE_WEB) {
  const { spawnSync } = require("node:child_process");
  for (const web of harness.exports.roots) {
    const run = spawnSync(process.execPath, [__filename], { input: JSON.stringify(cases), encoding: "utf8",
      env: { ...process.env, MAGNOLIE_WEB: web }, timeout: 70000 });
    process.stdout.write(run.stdout || ""); process.stderr.write(run.stderr || "");
    assert.equal(run.status, 0, "Edition task bindings did not finish: " + web);
  }
  process.exit(0);
}
const from = Date.parse("2026-12-01T00:00:00Z"), through = Date.parse("2027-01-01T00:00:00Z");
let completedCases = 0;
let phase = "start";
let activeWindow = null;
const watchdog = setTimeout(() => { console.error("OR6 task bindings stalled after " + completedCases + " cases: " + phase,
  activeWindow?.document.querySelector('[role="dialog"], .schleier')?.textContent?.slice(0, 1000)); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) for (const test of cases) {
    phase = test.name + "/boot";
    const b = await harness.exports.boot(web, {});
    activeWindow = b.w;
    try {
      phase = test.name + "/import";
      const T = b.t, expected = contract.expected.find(item => item.file === test.name);
      const incoming = test.items.map(item => ({ ...item, icsQuelleId: "or6:bindings610" }));
      assert.equal(T.mergeAufgaben(incoming).neu, incoming.length);
      assert.equal(T.mergeAufgaben(incoming).doppelt, incoming.length);
      const check = (tasks, newlyCompleted = "") => {
        const found = new Map();
        for (const item of T.icsSerienAbstimmen(tasks)) for (const value of T.icsExpansion(item, from, through, true)) {
          assert.ok(!found.has(value.faellig), "Copied native index duplicated a date");
          found.set(value.faellig, { completed: item.erledigt, category: item.kategorien || "" });
        }
        assert.deepEqual([...found.keys()].sort(), expected.dates, "Stale template dates became visible tasks");
        for (const [date, value] of found) {
          assert.equal(value.completed, expected.completedDates.includes(date) || date === newlyCompleted);
          assert.equal(value.category, expected.categories[date] || "");
        }
      };
      check(T.daten().aufgaben);
      const restored = T.normalisiere(JSON.parse(JSON.stringify(T.daten())));
      check(restored.aufgaben);
      for (const source of incoming) for (const property of source.icsRoundtrip.filter(line => line.startsWith("X-MAGNOLIE-OR6-TASK-TEMPLATE-")))
        assert.ok(restored.aufgaben.some(item => item.icsRoundtrip.includes(property)), "Profile restore lost template provenance");
      phase = test.name + "/calendar";
      T.planeSpeichern(); await T.wechsel("kalender");
      phase = test.name + "/tasks"; await T.wechsel("aufgaben");
      const master = T.daten().aufgaben.find(item => !item.icsRoundtrip.some(line => line.startsWith("RECURRENCE-ID:")));
      const next = T.icsNaechsteAufgabe(master, expected.dates[0]).faellig;
      assert.equal(next, expected.dates[0]);
      let button = b.w.document.querySelector('[data-fokus="aufgabe-status:' + master.id + '"]'); assert.ok(button);
      phase = test.name + "/instance-admission";
      for (let n = 0; button.disabled && n < 100; n++) {
        // boot() intentionally stubs DOM timers; yield the real Node event loop
        // while the actual asynchronous instance-identity digest completes.
        await new Promise(resolve => setTimeout(resolve, 10));
        button = b.w.document.querySelector('[data-fokus="aufgabe-status:' + master.id + '"]'); assert.ok(button);
      }
      assert.equal(button.disabled, false); button.click();
      phase = test.name + "/completion";
      assert.equal(master.erledigt, false, "Actual UI completed the full native group");
      check(T.daten().aufgaben, next);
      T.mergeAufgaben(incoming);
      assert.equal(T.daten().aufgaben.length, incoming.length + 1);
      check(T.daten().aufgaben, next);
      console.log("OR6 TASK BINDINGS PASSED:", web, test.name, "actual dates, states/categories, template restore, single UI completion and reimport");
      completedCases++;
    } finally { b.w.close(); }
  }
  assert.equal(completedCases, harness.exports.roots.length * cases.length);
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
