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
      assert.equal(button(form, "Compare with LibreOffice"), undefined);
      assert.ok(form.firstElementChild.classList.contains("eigenes-profil-kopf"));
      const request = b.messages.findLast(value => value.cmd === "eigenes_profil_office");
      assert.equal(request.operation, "read");
      b.w.App.eigenesProfilOffice({ requestId: request.requestId, ok: true, felder: { givenname: "Office name", sn: "Fallback" }, stamp: "fixture" });
      assert.equal(b.t.daten().eigenesProfil.data.vorname, "My own name", "Fallback must not overwrite existing profile fields");
      button(form, "Save").click();
      assert.equal(b.t.daten().eigenesProfil.data.vorname, "My own name");
      assert.equal(b.t.daten().eigenesProfil.data.nachname, "Fallback");
      b.w.App.telefonStand({ peers: [{ device_id: "22222222-2222-4222-8222-222222222222", fingerprint: "test-key",
        state: "online_wifi", own_device: true, remote_own_device: true, capabilities: { items: {} },
        local_grants: { grants: {} }, grants: { grants: {} } }] });
      const numberRequest = b.messages.findLast(value => value.cmd === "telefon_status_anfordern");
      assert.ok(numberRequest);
      b.w.App.geraetStatus({ kennung: numberRequest.kennung, status: { request_id: numberRequest.requestId,
        identifiers_peer_fingerprint: "test-key", identifiers: { phone_number: { status: "available", value: "+49123456789" } } } });
      button(b.w.document.querySelector(".eigenes-profil"), "Save").click();
      assert.equal(b.t.daten().eigenesProfil.data.mobil, "+49123456789");
      assert.equal(JSON.stringify(b.t.daten().kontakte), unchanged);
      console.log("Eigenprofil getrennt, Foto oben und Office-Fallback bestanden:", web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
