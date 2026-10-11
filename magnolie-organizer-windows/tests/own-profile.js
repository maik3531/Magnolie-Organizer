"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);

(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { kontakte: [{ id: "ordinary", vorname: "Same", nachname: "Person" }] });
    try {
      const button = (root, label) => [...root.querySelectorAll("button")].find(value => value.textContent === label);
      const unchanged = JSON.stringify(b.t.daten().kontakte);
      await b.t.wechsel("adressen");
      button(b.w.document.querySelector("#kopf-links"), "Own profile").click();
      await new Promise(resolve => setImmediate(resolve));
      let form = b.w.document.querySelector(".eigenes-profil"); assert.ok(form);
      const first = form.querySelector('input[type="text"]'); first.value = "My own name";
      first.dispatchEvent(new b.w.Event("input", { bubbles: true }));
      button(form, "Save").click();
      assert.equal(b.t.daten().eigenesProfil.kind, "own_profile");
      assert.equal(b.t.daten().eigenesProfil.data.vorname, "My own name");
      assert.equal(JSON.stringify(b.t.daten().kontakte), unchanged);
      assert.equal(b.t.normalisiere(b.t.daten()).eigenesProfil.data.vorname, "My own name");
      form = b.w.document.querySelector(".eigenes-profil");
      button(form, "Compare with LibreOffice").click();
      const request = b.messages.findLast(value => value.cmd === "eigenes_profil_office");
      assert.equal(request.operation, "read");
      b.w.App.eigenesProfilOffice({ requestId: request.requestId, ok: true, felder: { givenname: "Office name" }, stamp: "fixture" });
      const dialog = b.w.document.querySelector(".eingabe-dialog");
      assert.match(dialog.textContent, /My own name/); assert.match(dialog.textContent, /Office name/);
      dialog.querySelector("select").value = "import";
      button(dialog, "Apply").click();
      assert.equal(b.t.daten().eigenesProfil.data.vorname, "My own name", "Comparison must not save a profile draft implicitly");
      button(form, "Save").click();
      assert.equal(b.t.daten().eigenesProfil.data.vorname, "Office name");
      assert.equal(JSON.stringify(b.t.daten().kontakte), unchanged);
      console.log("Eigenprofil getrennt und Office-Vergleich bestanden:", web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
