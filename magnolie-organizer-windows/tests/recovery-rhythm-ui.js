"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web);
     try {
       assert.equal(b.t.normalisiere({}).einstellungen.allgemein.wiederherstellungsmodus, "weekly");
       b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-sicherheit").click();
      const mode = b.w.document.querySelector("#journal-modus");
      assert.deepEqual(Array.from(mode.options, option => option.value), ["change", "daily", "weekly", "startup", "interval"]);
      for (const value of ["daily", "weekly", "startup", "change", "interval"]) {
        mode.value = value; mode.dispatchEvent(new b.w.Event("change"));
        assert.equal(b.t.daten().einstellungen.allgemein.wiederherstellungsmodus, value);
        assert.equal(b.t.normalisiere(b.t.daten()).einstellungen.allgemein.wiederherstellungsmodus, value);
        const interval = b.w.document.querySelector("#journal-zeitabstand");
        assert.equal(interval.closest(".formzeile").hidden, value !== "interval");
      }
      const number = b.w.document.querySelector("#journal-zeitabstand"), unit = b.w.document.querySelector("#journal-zeitabstand-einheit");
      unit.value = "hours"; unit.dispatchEvent(new b.w.Event("change"));
      assert.equal(number.value, "0.5");
      number.value = "2"; number.dispatchEvent(new b.w.Event("change"));
      assert.equal(b.t.daten().einstellungen.allgemein.wiederherstellungsminuten, 120);
      unit.value = "minutes"; unit.dispatchEvent(new b.w.Event("change")); assert.equal(number.value, "120");
      assert.ok(b.w.document.querySelector("#einst-seite-sicherheit").textContent.includes("Unchanged contents"));
    } finally { b.close(); }
  }
  console.log("Recovery rhythm and hours/minutes: both desktop sources PASS");
})().catch(error => { console.error(error); process.exitCode = 1; });
