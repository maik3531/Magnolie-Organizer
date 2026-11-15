"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
let completed = 0;
const watchdog = setTimeout(() => { console.error("Calendar override test stalled after", completed); process.exit(1); }, 45000);
(async () => {
  for (const web of harness.exports.roots) for (const test of cases) {
    const b = await harness.exports.boot(web, {});
    try {
      const T = b.t, incoming = test.items.map(item => ({ ...item, icsQuelleId: "or6:overrides614" }));
      assert.equal(T.mergeTermine(incoming).neu, incoming.length);
      assert.equal(T.mergeTermine(incoming).doppelt, incoming.length);
      const moved = T.daten().termine.find(item => item.icsRoundtrip.includes("RECURRENCE-ID:20261031T101500"));
      assert.ok(moved); assert.equal(moved.datum, "2026-11-01"); assert.equal(moved.zeit, "14:30");
      assert.ok(moved.icsRoundtrip.includes("X-MAGNOLIE-OR6-OBJECT-UID:or6:0001b137:00000411"));
      const checks = [
        ["2026-10-24", "APPT-OR6-212 Besprechung"], ["2026-10-31", ""],
        ["2026-11-01", "APPT-OR6-212 Besprechung"],
        ["2026-11-07", test.name.includes("clock-content") ? "OR6-614 Changed" : "APPT-OR6-212 Besprechung"],
        ["2026-11-08", ""]
      ];
      T.planeSpeichern();
      for (const [date, title] of checks) {
        Object.assign(T.zustand().kalender, { jahr: 2026, monat: Number(date.slice(5, 7)) - 1, tag: date, ansicht: "day" });
        await T.wechsel("planer"); await T.wechsel("kalender");
        const nodes = [...b.w.document.querySelectorAll("#inhalt-links .tages-termin")];
        assert.equal(nodes.length, title ? 1 : 0, "Original/moved day duplicated or omitted: " + date);
        if (title) assert.ok(nodes[0].textContent.includes(title));
      }
      const restored = T.normalisiere(JSON.parse(JSON.stringify(T.daten())));
      const copy = restored.termine.find(item => item.icsRoundtrip.includes("RECURRENCE-ID:20261031T101500"));
      assert.equal(copy.datum, "2026-11-01"); assert.equal(copy.zeit, "14:30");
      assert.ok(copy.icsRoundtrip.includes("X-MAGNOLIE-OR6-OBJECT-UID:or6:0001b137:00000411"));
      const changed = restored.termine.find(item => item.icsRoundtrip.includes("RECURRENCE-ID:20261107T101500"));
      if (test.name.includes("clock-content")) {
        assert.equal(changed.titel, "OR6-614 Changed"); assert.equal(changed.kategorien, "OR6-614 Other");
      }
      Object.assign(T.zustand().kalender, { jahr: 2026, monat: 10, tag: "2026-11-01", ansicht: "day" });
      await T.wechsel("planer"); await T.wechsel("kalender");
      b.w.document.querySelector("#inhalt-links .tages-termin").click();
      assert.equal(T.datumswert(b.w.document.querySelector("#tb-datum-von")), "2026-11-01");
      assert.equal(b.w.document.querySelector("#tb-zeit").value, "14:30");
      assert.equal(b.w.document.querySelector("#tb-endzeit").value, "16:00");
      const titleInput = b.w.document.querySelector("#tb-titel");
      titleInput.value = "Local moved exception"; titleInput.dispatchEvent(new b.w.Event("input", { bubbles: true }));
      b.w.document.querySelector("#tb-fertig").click();
      for (let n = 0; moved.titel !== "Local moved exception" && n < 100; n++) await new Promise(resolve => setTimeout(resolve, 10));
      assert.equal(moved.titel, "Local moved exception", "Actual exception editor failed to save");
      T.mergeTermine(incoming);
      assert.equal(T.daten().termine.length, incoming.length); assert.equal(moved.titel, "Local moved exception");
      assert.equal(moved.datum, "2026-11-01");
      console.log("OR6 APPOINTMENT OVERRIDES PASSED:", web, test.name, "original/moved days, content, native identity, restore and local-edit reimport"); completed++;
    } finally { b.w.close(); }
  }
  assert.equal(completed, harness.exports.roots.length * cases.length);
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
