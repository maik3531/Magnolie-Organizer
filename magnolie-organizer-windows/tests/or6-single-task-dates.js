"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const incoming = JSON.parse(fs.readFileSync(0, "utf8"));
const expected = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../contracts/or6-native-fixtures.json"), "utf8")).expected.task;
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
let completed = 0;
const watchdog = setTimeout(() => { console.error("Ordinary task date test stalled after", completed); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      const T = b.t, source = { ...incoming, icsQuelleId: "or6:single612" };
      assert.equal(T.mergeAufgaben([source]).neu, 1); assert.equal(T.mergeAufgaben([source]).doppelt, 1);
      const task = T.daten().aufgaben[0];
      for (const key of ["startDatum", "startZeit", "faellig", "faelligZeit", "prio", "erledigt"]) assert.equal(task[key], expected[key]);
      assert.equal(task.icsImportUid, incoming.uid);
      T.planeSpeichern(); await T.wechsel("kalender"); await T.wechsel("aufgaben");
      b.w.document.querySelector('[data-fokus="aufgabe:' + task.id + '"]').click();
      assert.equal(T.datumswert(b.w.document.querySelector("#aufgabe-startdatum")), expected.startDatum);
      assert.equal(T.datumswert(b.w.document.querySelector('#aufgabe-faellig-zeile input')), expected.faellig);
      assert.deepEqual([...b.w.document.querySelectorAll('#aufgabe-zeitfenster-zeile .zeitfeld')].map(node => node.value), [expected.startZeit, expected.faelligZeit]);
      const restored = T.normalisiere(JSON.parse(JSON.stringify(T.daten()))).aufgaben[0];
      for (const key of ["startDatum", "startZeit", "faellig", "faelligZeit", "prio", "erledigt"]) assert.equal(restored[key], expected[key]);
      task.startZeit = "09:00"; task.geaendert = Date.now();
      T.mergeAufgaben([source]); assert.equal(task.startZeit, "09:00", "Reimport overwrote user's time edit");
      assert.equal(T.daten().aufgaben.length, 1);
      console.log("OR6 SINGLE TASK DATES PASSED:", web, "start/due clocks, actual editor, restore, duplicate and local-edit reimport"); completed++;
    } finally { b.w.close(); }
  }
  assert.equal(completed, harness.exports.roots.length);
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
