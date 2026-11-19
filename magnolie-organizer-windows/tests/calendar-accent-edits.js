"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const plain = value => JSON.parse(JSON.stringify(value));
const watchdog = setTimeout(() => { console.error("Calendar accent edits timed out"); process.exit(1); }, 60000);
(async () => {
  const snapshots = [];
  assert.equal(harness.exports.roots.length, 2, "Both GUI sources required");
  for (const web of harness.exports.roots) {
    for (const kind of ["termine", "aufgaben"]) {
      const initial = kind === "termine" ? { id: "event", uid: "synthetic-event", datum: "2026-08-13",
        zeit: "", endDatum: "2026-08-13", endZeit: "", titel: "Synthetic event", geaendert: 100 } :
        { id: "task", uid: "synthetic-task", titel: "Synthetic task", geaendert: 100, faellig: "", prio: 2 };
      const b = await harness.exports.boot(web, { [kind]: [initial] });
      try {
        if (kind === "aufgaben") await b.t.wechsel("aufgaben");
        for (const colour of ["#112233", "#abcdef", ""]) {
          const item = b.t.daten()[kind][0], before = plain(item);
          if (kind === "termine") b.t.oeffneTerminBlatt(item, "2026-08-13");
          else {
            const row = b.w.document.querySelector("#inhalt-links li.zeile");
            assert.ok(row && row.textContent.includes(item.titel)); row.click();
          }
          const prefix = kind === "termine" ? "tb" : "aufgabe";
          const toggle = b.w.document.querySelector("#" + prefix + "-eigene-farbe");
          assert.ok(toggle && !toggle.disabled);
          toggle.checked = Boolean(colour); toggle.dispatchEvent(new b.w.Event("change", { bubbles: true }));
          const picker = b.w.document.querySelector("#" + prefix + "-farbe");
          assert.equal(picker.disabled, !colour);
          if (colour) { picker.value = colour; picker.dispatchEvent(new b.w.Event("input", { bubbles: true })); }
          if (kind === "termine") b.w.document.querySelector("#tb-fertig").click();
          else picker.closest("fieldset").querySelector(".form-knoepfe button").click();
          const after = plain(b.t.daten()[kind][0]);
          assert.equal(after.akzentFarbe, colour, "Actual form did not save the chosen colour");
          assert.equal(after.uid, before.uid); assert.equal(after.id, before.id);
          assert.deepEqual(after.icsRoundtrip, before.icsRoundtrip, "Colour edit rewrote opaque ICS");
          snapshots.push({ web: path.basename(path.dirname(web)), kind, before, after });
          b.t.speichereJetzt(); b.ack();
        }
        console.log("Actual accent form set/change/remove passed:", web, kind);
      } finally { b.close(); }
    }
  }
  if (process.env.MAGNOLIE_ACCENT_FIXTURE_OUTPUT)
    fs.writeFileSync(process.env.MAGNOLIE_ACCENT_FIXTURE_OUTPUT, JSON.stringify(snapshots, null, 2) + "\n");
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
