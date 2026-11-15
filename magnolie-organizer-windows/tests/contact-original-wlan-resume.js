"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
process.env.MAGNOLIE_TEST_WEB ||= path.resolve(__dirname, "../../magnolie-organizer/web");
const file = path.join(__dirname, "contact-original-source-updates.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function runWire()")[0] + "\nmodule.exports={boot,start};", file);
(async () => {
  for (const mode of ["return", "stable", "no-terminal", "held", "no-grants", "newer-edit", "pending-save", "revoked", "reloaded"]) {
    const b = await harness.exports.boot();
    try {
      assert.equal(typeof b.w.App.originalKontaktNetz, "function");
      if (mode === "no-grants") {
        b.w.App.originalKontaktNetz({ wlan: true, freigaben: 999, saved: true });
        assert.equal(b.commands("kontakt_originalquellen_update").length, 0, "Network metadata manufactured consent");
      } else {
        const original = await harness.exports.start(b);
        if (mode !== "no-terminal") b.w.App.originalKontaktErgebnis({ requestId: original.requestId,
          ok: false, code: mode === "held" ? "held" : "wlan_required", freigaben: 2 });
        if (["newer-edit", "pending-save"].includes(mode)) b.t.daten().kontakte[0].notiz = "Newer edit after WLAN loss";
        if (mode === "pending-save") b.t.speichereJetzt();
        if (mode === "revoked") b.button("Revoke").click();
        if (mode === "reloaded") b.w.App.init({ neu: false, daten: { kontakte: [{ id: "new", uid: "other-book", notiz: "Keep" }] } });
        b.w.App.originalKontaktNetz({ wlan: false });
        assert.equal(b.commands("kontakt_originalquellen_update").length, 1);
        b.w.App.originalKontaktNetz({ wlan: true });
        const resumes = ["return", "stable"].includes(mode);
        assert.equal(b.commands("kontakt_originalquellen_update").length, resumes ? 2 : 1, mode);
        if (["newer-edit", "pending-save"].includes(mode)) {
          if (mode === "newer-edit") b.t.speichereJetzt();
          assert.equal(b.commands("kontakt_originalquellen_update").length, 1, "Retry preceded newer edit SaveACK");
          b.ack();
          assert.equal(b.commands("kontakt_originalquellen_update").length, 2);
        }
        const count = b.commands("kontakt_originalquellen_update").length;
        b.w.App.originalKontaktNetz({ wlan: true }); b.w.App.originalKontaktNetz({ wlan: true });
        assert.equal(b.commands("kontakt_originalquellen_update").length, count, "Duplicate network event retried active/unknown run");
        if (mode === "stable") {
          const retry = b.commands("kontakt_originalquellen_update").at(-1);
          b.w.App.originalKontaktErgebnis({ requestId: retry.requestId, ok: true, token: "", freigaben: 2 });
          b.w.App.originalKontaktNetz({ wlan: true });
          assert.equal(b.commands("kontakt_originalquellen_update").length, 2, "Known clean completion became an idle retry loop");
        }
      }
      console.log("ORIGINAL CONTACT WLAN RESUME PASS", mode);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
