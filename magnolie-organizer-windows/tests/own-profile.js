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
      assert.ok(form.classList.contains("kontakt-formular"), "Own profile must use the normal contact editor");
      const first = form.querySelector('#kontakt-vorname'); first.value = "My own name";
      first.dispatchEvent(new b.w.Event("input", { bubbles: true }));
      button(form, "Save").click();
      assert.equal(b.t.daten().eigenesProfil.kind, "own_profile");
      assert.equal(b.t.daten().eigenesProfil.data.vorname, "My own name");
      assert.equal(JSON.stringify(b.t.daten().kontakte), unchanged);
      assert.equal(b.t.normalisiere(b.t.daten()).eigenesProfil.data.vorname, "My own name");
      const card = b.w.document.querySelector(".kontakt-karte"); assert.ok(card);
      assert.ok(card.querySelector('[aria-label="Choose contact photo"]'));
      assert.equal(button(card, "Call"), undefined); assert.equal(button(card, "SMS"), undefined);
      button(card, "Edit").click();
      form = b.w.document.querySelector(".eigenes-profil");
      assert.equal(button(form, "Compare with LibreOffice"), undefined);
      assert.ok(form.querySelector(".kontakt-editor-profilkopf .kontakt-foto-wahl"));
      assert.equal(button(form, "Delete own profile"), undefined);
      assert.equal(form.querySelector(".kontakt-termin-liste"), null, "Own profile must not edit contact-bound appointments");
      for (const timer of b.timers.filter(timer => timer.delay === 0 && !timer.cancelled && !timer.ran)) { timer.ran = true; timer.fn(); }
      const request = b.messages.findLast(value => value.cmd === "eigenes_profil_office");
      assert.equal(request.operation, "read");
      b.w.App.eigenesProfilOffice({ requestId: request.requestId, ok: true, felder: { givenname: "Office name", sn: "Fallback" }, stamp: "fixture" });
      assert.equal(b.t.daten().eigenesProfil.data.vorname, "My own name", "Fallback must not overwrite existing profile fields");
      button(form, "Save").click();
      assert.equal(b.t.daten().eigenesProfil.data.vorname, "My own name");
      assert.equal(b.t.daten().eigenesProfil.data.nachname, "Fallback");
      button(b.w.document.querySelector(".kontakt-karte"), "Edit").click();
      form = b.w.document.querySelector(".eigenes-profil");
      const firstEmail = form.querySelector('.kontakt-email-adresse'); firstEmail.value = "first@example.test";
      firstEmail.dispatchEvent(new b.w.Event("input", { bubbles: true }));
      button(form, "+ Email address").click();
      const secondEmail = form.querySelectorAll('.kontakt-email-adresse')[1]; secondEmail.value = "second@example.test";
      secondEmail.dispatchEvent(new b.w.Event("input", { bubbles: true }));
      button(form, "Save").click();
      assert.equal(b.t.daten().eigenesProfil.data.emailEintraege.length, 2);
      assert.equal(JSON.stringify(b.t.daten().kontakte), unchanged);
      b.w.App.telefonStand({ peers: [{ device_id: "22222222-2222-4222-8222-222222222222", fingerprint: "test-key",
        state: "online_wifi", own_device: true, remote_own_device: true, capabilities: { items: {} },
        local_grants: { grants: {} }, grants: { grants: {} } }] });
      const numberRequest = b.messages.findLast(value => value.cmd === "telefon_status_anfordern");
      assert.ok(numberRequest);
      b.w.App.geraetStatus({ kennung: numberRequest.kennung, status: { request_id: numberRequest.requestId,
        identifiers_peer_fingerprint: "test-key", identifiers: { phone_number: { status: "available", value: "+49123456789" } } } });
      assert.equal(b.t.daten().eigenesProfil.data.mobil, "+49123456789");
      button(b.w.document.querySelector(".kontakt-karte"), "Send").click();
      const sending = b.w.document.querySelector(".eigenes-profil-senden");
      const options = [...sending.querySelectorAll('input[type="checkbox"]')];
      options.forEach((input, index) => { input.checked = index === 0; });
      button(sending, "Send").click();
      const exported = b.messages.findLast(value => value.cmd === "exportieren");
      assert.deepEqual(Object.keys(exported.daten.kontakte[0]).sort(), ["firma", "nachname", "vorname"]);
      assert.equal(exported.daten.kontakte[0].vorname, "My own name");
      assert.equal(JSON.stringify(b.t.daten().kontakte), unchanged);
      const retained = JSON.stringify(b.t.daten().eigenesProfil);
      b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-adressen").click();
      const enabled = b.w.document.querySelector("#adressen-eigenes-profil"); assert.ok(enabled.checked);
      enabled.checked = false; enabled.dispatchEvent(new b.w.Event("change"));
      assert.equal(b.t.normalisiere(b.t.daten()).einstellungen.adressen.eigenesProfilAn, false);
      assert.equal(button(b.w.document.querySelector("#kopf-links"), "Own profile"), undefined);
      assert.equal(JSON.stringify(b.t.daten().eigenesProfil), retained, "Hiding must retain the separate profile data");
      console.log("Eigenprofil getrennt, Foto oben und Office-Fallback bestanden:", web);
    } finally { b.close(); }
    const photo = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAIAAADYYG7QAAAARUlEQVR4nO3OsQEAEADAMPz/M7slI0NzQeYef1mvA7dCUkgKSSEpJIWkkBSSQlJICkkhKSSFpJAUkkJSSApJISkkhaSQHEnhAV+0eRpfAAAAAElFTkSuQmCC";
    const p = await harness.exports.boot(web, { eigenesProfil: { version: 1, kind: "own_profile", id: "self",
      data: { vorname: "Saved", nachname: "Profile" } }, kontakte: [{ id: "ordinary", vorname: "Ordinary" }],
      jahrestage: [{ id: "unlinked", typ: "birthday", datum: "2000-01-02", name: "Unrelated" }] });
    try {
      const button = (root, label) => [...root.querySelectorAll("button")].find(value => value.textContent === label);
      const peerId = "22222222-2222-4222-8222-222222222222";
      const ordinary = JSON.stringify([p.t.daten().kontakte, p.t.daten().jahrestage, p.t.daten().termine, p.t.daten().aufgaben]);
      p.w.App.telefonStand({ peers: [{ device_id: peerId, fingerprint: "own-key", state: "online_wifi", own_device: true,
        remote_own_device: true, capabilities: { items: { device_status: { versions: [5, 7] } } }, local_grants: { grants: {} }, grants: { grants: {} } }] });
      await p.t.wechsel("adressen"); button(p.w.document.querySelector("#kopf-links"), "Own profile").click();
      button(p.w.document.querySelector(".kontakt-karte"), "Edit").click();
      let form = p.w.document.querySelector(".eigenes-profil");
      p.input("#kontakt-vorname", "Manual");
      for (const timer of p.timers.filter(timer => timer.delay === 0 && !timer.cancelled && !timer.ran)) { timer.ran = true; timer.fn(); }
      const request = p.messages.findLast(value => value.cmd === "eigenes_profil_telefon"); assert.ok(request);
      const before = JSON.stringify(p.t.daten().eigenesProfil);
      p.w.App.eigenesProfilTelefon({ requestId: request.requestId, device_id: peerId, fingerprint: "own-key", ok: true,
        data: { id: "must-not-import", uid: "must-not-sync", vorname: "Phone", nachname: "Phone surname", foto: photo,
          telefone: [{ wert: "+49123456789", typen: ["CELL"] }, { wert: "+4930123456", typen: ["WORK"] }],
          emailEintraege: [{ wert: "one@example.test", typen: ["HOME"] }, { wert: "two@example.test", typen: ["WORK"] }],
          anschriften: [{ strasse: "First street", ort: "City", plz: "12345", typen: ["HOME"] },
            { strasse: "Second street", ort: "Work city", plz: "54321", typen: ["WORK"] }] } });
      assert.equal(JSON.stringify(p.t.daten().eigenesProfil), before, "Phone fallback must populate the draft, not save over the profile");
      assert.equal(form.querySelector("#kontakt-vorname").value, "Manual");
      assert.equal(form.querySelectorAll(".kontakt-telefon-nummer").length, 2);
      assert.equal(form.querySelectorAll(".kontakt-email-adresse").length, 2);
      assert.equal(form.querySelectorAll(".kontakt-anschrift-strasse").length, 2);
      assert.equal(form.querySelector(".kontakt-foto.vorschau").src, photo);
      button(form, "Save").click();
      const saved = p.t.daten().eigenesProfil.data;
      assert.equal(saved.vorname, "Manual"); assert.equal(saved.foto, photo);
      assert.equal(saved.id, undefined); assert.equal(saved.uid, undefined); assert.equal(saved.telefone.length, 2);
      assert.equal(JSON.stringify([p.t.daten().kontakte, p.t.daten().jahrestage, p.t.daten().termine, p.t.daten().aufgaben]), ordinary);
      button(p.w.document.querySelector(".kontakt-karte"), "Edit").click();
      form = p.w.document.querySelector(".eigenes-profil"); button(form, "Choose photo…").click();
      const gallery = p.w.document.querySelector(".kontakt-foto-dialog"); assert.ok(gallery);
      button(gallery, "Remove photo").click();
      assert.equal(p.t.daten().eigenesProfil.data.foto, photo, "Draft photo removal must wait for Save");
      button(form, "Save").click(); assert.equal(p.t.daten().eigenesProfil.data.foto, "");
      assert.equal(JSON.stringify(p.t.daten().kontakte), JSON.stringify(JSON.parse(ordinary)[0]));
      console.log("Normaler Eigenprofil-Editor: Mehrfachfelder, Fotoentwurf und Datentrennung bestanden:", web);
    } finally { p.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
