"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(file, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "kdeZustand: () => ({ editor: !!aktiverEditor, syncLaeuft, kontaktImportDialogOffen, gesperrt, foto: !!kontaktFotoLauf, quelle: telefonStand?.kdeconnect }), kdePlan: kdeKontaktPlan, kdeEntwurf: kdeKontaktEntwurf, kdeStart: starteKdeKontaktImport, speichereJetzt: speichereJetzt,"));');
harness._compile(source + "\nmodule.exports={boot,roots};", file);
const plain = value => JSON.parse(JSON.stringify(value));
const binding = "urn:magnolie:import:kde:" + "a".repeat(64);
const card = values => ({ bindung: binding, hash: "b".repeat(64), kontakt: values });

async function preview(web, data, mode = "apply") {
  const b = await harness.exports.boot(web, { ...data, einstellungen: { adressen: { foto: false } } });
  const device = "paired", fingerprint = "a".repeat(64), uid = "remote-one";
  const remote = { uid, bindung: "urn:magnolie:import:kde:" + createHash("sha256").update(
    "kde-contact-v1\0" + device + "\0" + fingerprint + "\0" + uid).digest("hex"),
    kontakt: { vorname: "Remote", email: "one@example.org", firma: "Company" } };
  try {
    b.t.daten().einstellungen.adressen.foto = false;
    b.w.App.telefonStand({ peers: [], kdeconnect: { contacts_available: true, contacts_device_id: device } });
    const before = plain(b.t.daten().kontakte), done = new Set();
    let clicked = false, completed = false, indexRequests = 0;
    b.t.kdeStart().then(() => { completed = true; });
    const deadline = Date.now() + 6000;
    while (Date.now() < deadline) {
      await new Promise(resolve => setImmediate(resolve));
      for (const message of b.messages) {
        if (done.has(message)) continue;
        done.add(message);
        if (message.cmd === "speichern") b.w.App.gespeichert({ id: message.id, ok: true });
        if (message.cmd === "mutations_snapshot") b.w.App.mutationsSnapshot({ token: message.token, ok: mode !== "snapshot-error" });
        if (message.cmd !== "telefon_kontakte") continue;
        if (!message.uids) indexRequests++;
        if (message.uids && mode === "locked") {
          b.w.App.init({ gesperrt: true });
          assert.equal(b.w.document.querySelector(".kontakt-import-dialog"), null, "locking removes the sensitive preview");
          b.w.App.telefonKontakte({ ok: true, requestId: message.requestId, device_id: device, fingerprint, contacts: [remote] });
          assert.equal(b.t.daten().kontakte.length, 0, "late reply cannot cross the lock boundary");
          return plain(b.t.daten());
        }
        if (message.uids && mode === "timeout") {
          const timer = b.timers.find(timer => timer.delay === 12000 && !timer.cancelled);
          assert.ok(timer); timer.fn(); timer.cancelled = true;
        }
        b.w.App.telefonKontakte({ ok: true, requestId: message.requestId, device_id: device,
          native_cache: mode === "native-cache-refresh",
          fingerprint: message.uids && mode === "source-changed" || !message.uids && indexRequests > 1 && mode === "repaired" ? "b".repeat(64) : fingerprint,
          contacts: message.uids ? mode === "incomplete" ? [] : [remote] :
            [{ uid, modified_ms: indexRequests > 1 && ["index-changed", "native-cache-refresh"].includes(mode) ? 2 : 1 }] });
      }
      const dialog = b.w.document.querySelector(".kontakt-import-dialog");
      if (completed && !clicked) {
        assert.ok(dialog, JSON.stringify(b.t.kdeZustand()));
        assert.deepEqual(plain(b.t.daten().kontakte), before, "retrieval and preview never mutate contacts");
        if (["incomplete", "source-changed", "timeout"].includes(mode)) {
          assert.equal(dialog.querySelector(".hauptknopf").disabled, true); return before;
        }
        assert.ok(dialog.querySelector("details"), dialog.textContent);
        clicked = true;
        if (mode === "device-changed") {
          b.w.App.telefonStand({ peers: [], kdeconnect: { contacts_available: true, contacts_device_id: "other-phone" } });
          assert.equal(b.w.document.querySelector(".kontakt-import-dialog"), null);
          assert.deepEqual(plain(b.t.daten().kontakte), before);
          return plain(b.t.daten());
        }
        if (mode === "local-edit") b.t.daten().kontakte.push({ id: "local-edit", vorname: "Local edit" });
        if (mode === "cancel") {
          [...dialog.querySelectorAll("button")].find(button => button.textContent === "Cancel").click();
        } else dialog.querySelector(".hauptknopf").click();
      }
      if (clicked && ["repaired", "index-changed", "local-edit"].includes(mode) && dialog?.querySelector(".einst-hinweis").textContent === "Conflict") {
        assert.equal(b.messages.some(m => m.cmd === "mutations_snapshot"), false, "changed source/local data prevents import before snapshot");
        if (mode === "local-edit") assert.equal(b.t.daten().kontakte[0].id, "local-edit");
        else assert.deepEqual(plain(b.t.daten().kontakte), before);
        return plain(b.t.daten());
      }
      if (clicked && mode === "snapshot-error" && b.messages.some(m => m.cmd === "mutations_snapshot" && done.has(m))) {
        assert.deepEqual(plain(b.t.daten().kontakte), before, "failed snapshot prevents mutation");
        assert.equal([...dialog.querySelectorAll("button")].find(button => button.textContent === "Cancel").disabled, false);
        return before;
      }
      if (clicked && !b.w.document.querySelector(".kontakt-import-dialog")) {
        const result = plain(b.t.daten());
        if (mode === "cancel") assert.deepEqual(result.kontakte, before);
        else {
          assert.equal(result.kontakte.length, 1);
          assert.equal(b.messages.some(m => m.cmd === "mutations_snapshot"), before.length === 0,
            "unchanged replay must not create another recovery snapshot");
          assert.equal(result.kontakte[0].firma, "Company");
          assert.ok(b.saves().some(m => JSON.parse(m.text).kontakte[0]?.firma === "Company"));
        }
        assert.ok(!b.messages.some(m => m.cmd === "telefon_kontaktfotos"), "contact import works with photos disabled");
        return result;
      }
    }
    throw new Error("Kontaktvorschau nicht abgeschlossen: " + b.w.document.querySelector(".kontakt-import-dialog")?.textContent);
  } finally { b.close(); }
}

(async () => {
  for (const web of harness.exports.roots.filter(root => !process.argv.includes("--linux-only") || !root.includes("windows"))) {
    const b = await harness.exports.boot(web, { kontakte: [
      { id: "one", uid: "local-identity", vorname: "Local", email: "one@example.org", fotoManuell: true, foto: "" },
      { id: "two", vorname: "Other", email: "shared@example.org" },
      { id: "three", vorname: "Third", email: "shared@example.org" }
    ] });
    try {
      const original = plain(b.t.daten().kontakte);
      const first = card({ vorname: "Remote", anzeigename: "Remote", email: "one@example.org", firma: "Company", notiz: "New note" });
      const plan = b.t.kdePlan(first, b.t.daten().kontakte);
      assert.equal(plan.modus, "merge"); assert.equal(plan.zielId, "one");
      const merged = b.t.kdeEntwurf(plan, b.t.daten().kontakte[0]);
      assert.equal(merged.vorname, "Local", "conflicting local scalar stays until explicitly chosen");
      assert.notEqual(merged.anzeigename, "Remote", "incoming FN may not override the retained derived local name");
      assert.equal(merged.firma, "Company"); assert.equal(merged.notiz, "New note");
      assert.equal(merged.uid, "local-identity"); assert.equal(merged.foto, ""); assert.equal(merged.fotoManuell, true);
      assert.deepEqual(plain(b.t.daten().kontakte), original, "preview may not mutate contacts");
      plan.auswahl.vorname = "incoming";
      assert.equal(b.t.kdeEntwurf(plan, b.t.daten().kontakte[0]).vorname, "Remote");
      assert.equal(b.t.kdePlan(card({ email: "shared@example.org" }), b.t.daten().kontakte).modus, "skip",
        "ambiguous targets require a decision");
      const bound = b.t.kdePlan(card({ email: "changed@example.org" }), [merged]);
      assert.equal(bound.zielId, "one", "source binding survives changed phone fields");
      const differentSource = { ...first, bindung: "urn:magnolie:import:kde:" + "c".repeat(64), kontakt: { vorname: "Remote" } };
      assert.equal(b.t.kdePlan(differentSource, [merged]).modus, "new", "a name is not a source identity");
      b.w.App.init({ daten: { kontakte: [merged] }, neu: false });
      assert.deepEqual(plain(b.t.daten().kontakte[0].importBindungen), [binding], "binding survives reload");
      assert.equal(b.t.daten().kontakte[0].kdeImportStaende[binding], first.hash, "accepted source version survives reload");
      const again = b.t.kdePlan(first, b.t.daten().kontakte);
      assert.equal(again.modus, "merge"); assert.equal(again.zielId, "one");
      const newPlan = b.t.kdePlan(differentSource, []), created = b.t.kdeEntwurf(newPlan, null);
      assert.ok(created.id && created.uid); assert.deepEqual(plain(created.importBindungen), [differentSource.bindung]);
      console.log("OK KDE-Kontaktvorschau und Quellbindung:", web);
    } finally { b.close(); }
    const imported = await preview(web, {});
    imported.kontakte[0].vorname = "Local edit";
    const repeated = await preview(web, imported);
    assert.equal(repeated.kontakte[0].id, imported.kontakte[0].id);
    assert.equal(repeated.kontakte[0].vorname, "Local edit", "unchanged phone version does not overwrite local edits");
    for (const mode of ["cancel", "incomplete", "source-changed", "snapshot-error", "timeout", "locked", "device-changed", "repaired", "index-changed", "local-edit", "native-cache-refresh"])
      await preview(web, {}, mode);
    console.log("OK KDE-Abruf, Vorschau, Snapshot, Speicherung, Wiederholung und Fehlerfälle:", web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
