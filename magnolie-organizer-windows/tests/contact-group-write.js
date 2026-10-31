"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(file, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "sendeTelefonKontaktGruppen, telefonGruppenSchreibQuelle, blockFoto: () => { kontaktFotoLauf = { daten: DATEN }; }, speichereJetzt: speichereJetzt,"));');
harness._compile(source + "\nmodule.exports={boot,roots};", file);
const plain = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setImmediate(resolve));
const fingerprint = "a".repeat(64), device = "11111111-1111-4111-8111-111111111111";
const base = { deviceId: "notes:" + device, fingerprint, uid: "exact-native-uid", groups: ["Family"] };
const token = "22222222-2222-4222-8222-222222222222";
const account = { name: "synthetic@example.invalid", type: "test-provider", data_set: "" };

async function run(web, mode) {
  const retainedStand = mode.startsWith("retained-stand-save");
  const retainedSave = mode.startsWith("retained-save") || retainedStand;
  const autoSave = mode === "auto-save" || mode === "auto-save-multiple" || retainedSave;
  const saveFailed = mode === "save-failed" || mode === "retained-save-failed" || mode === "retained-stand-save-failed";
  const remoteEdit = mode === "remote-edit" || mode === "retained-save-remote" || mode === "retained-stand-save-remote";
  const multiple = mode === "auto-save-multiple";
  const localized = mode.startsWith("localized-");
  const expectedProvider = mode === "localized-existing" ? "Work" : mode === "localized-custom" ? "My own group" : localized ? "Arbeit" : "Coworkers";
  const contact = { id: "local", vorname: "Synthetic", vcardRoundtrip: ["CATEGORIES:Colleagues"],
    telefonGruppenStand: base, telefonGruppenAenderung: { version: 1, base } };
  if (mode === "no-base") delete contact.telefonGruppenAenderung.base;
  if (["explicit-source", "observed-auto"].includes(mode)) { delete contact.telefonGruppenAenderung.base; contact.telefonGruppenAenderung.beobachtet = base; }
  if (autoSave && !retainedSave) { contact.vcardRoundtrip = ["CATEGORIES:Family"]; contact.telefonGruppenAenderung = null; }
  if (retainedSave) {
    contact.telefonGruppenStand = retainedStand ? base : null;
    contact.telefonGruppenAenderung = retainedStand ? { version: 1 } : { version: 1, beobachtet: base };
  }
  if (localized) contact.vcardRoundtrip = ["CATEGORIES:" + (mode === "localized-custom" ? "My own group" : "Work")];
  const b = await harness.exports.boot(web, { kontakte: [contact], einstellungen: { adressen: { foto: false } } });
  try {
    if (localized) {
      b.w.eval(fs.readFileSync(path.join(web, "i18n/de.js"), "utf8"));
      b.w.MagnolieI18n.setLocale("de");
    }
    const peer = { device_id: device, state: "online_wifi", own_device: true, remote_own_device: true,
      contacts_read_available: true, contacts_fingerprint: fingerprint, contact_groups_write_available: mode !== "old-capability" };
    b.w.App.telefonStand({ enabled: true, peers: [peer], kdeconnect: {} });
    const local = b.t.daten().kontakte[0];
    if (mode === "duplicate") b.t.daten().kontakte.push({ ...local, id: "other" });
    let promise;
    if (mode === "photo-busy") b.t.blockFoto();
    if (mode === "auto-peer") {
      const timer = b.timers.filter(value => value.delay === 250 && !value.cancelled).at(-1); assert.ok(timer);
      promise = timer.fn();
    } else if (autoSave) {
      b.t.zustand().adressen.auswahlId = "local"; b.t.zustand().adressen.buchstabe = "S"; b.t.wechsel("adressen");
      [...b.w.document.querySelectorAll("button")].find(button => button.textContent === "Edit").click();
      const picker = b.w.document.querySelector("#kontakt-personengruppen"); assert.ok(picker);
      for (const input of retainedSave ? [] : picker.querySelectorAll('input[type="checkbox"]'))
        if (input.value && input.checked !== (input.value === "Colleagues" || multiple && input.value === "Family")) input.click();
      [...b.w.document.querySelectorAll("button")].find(button => button.textContent === "Save changes").click();
      assert.equal(b.w.document.querySelectorAll("[data-telefon-gruppen-senden]").length, 0,
        "A saved group edit must synchronize automatically without a separate Send button");
      const timer = b.timers.filter(value => value.delay === 0 && !value.cancelled).at(-1); assert.ok(timer);
      promise = timer.fn();
    } else promise = b.t.sendeTelefonKontaktGruppen(local, mode === "explicit-source");
    await tick();
    assert.equal(b.messages.filter(m => m.cmd === "telefon_kontaktgruppen").length, 0, "No request before durable local save");
    if (["no-base", "observed-auto", "old-capability", "duplicate"].includes(mode)) {
      await promise; assert.ok(local.telefonGruppenAenderung); return;
    }
    b.ack(!saveFailed); await tick();
    const seen = new Set(); let prepareCount = 0, applyCount = 0, ended = false;
    Promise.resolve(promise).finally(() => { ended = true; });
    const deadline = Date.now() + 3000;
    while (!ended) {
      assert.ok(Date.now() < deadline, "Writer must settle");
      for (const message of b.messages) {
        if (seen.has(message)) continue; seen.add(message);
        if (message.cmd === "speichern") { if (!saveFailed) b.w.App.gespeichert({ id: message.id, ok: true }); continue; }
        if (message.cmd !== "telefon_kontaktgruppen") continue;
        const prepare = message.action === "prepare";
        if (prepare) prepareCount++; else applyCount++;
        if (!prepare) assert.deepEqual([...message.groups].sort(), multiple ? ["Coworkers", "Family"] : [expectedProvider], "Reuse existing provider names; localize only new standard groups");
        if (prepare && mode === "local-edit") local.vcardRoundtrip = ["CATEGORIES:Work"];
        if (prepare && mode === "removed") b.t.daten().kontakte = [];
        if (prepare && mode === "revoked") b.w.App.telefonStand({ enabled: true, peers: [{ ...peer, contact_groups_write_available: false }], kdeconnect: {} });
        if (prepare && mode === "key-changed") b.w.App.telefonStand({ enabled: true, peers: [{ ...peer, contacts_fingerprint: "b".repeat(64) }], kdeconnect: {} });
        if (prepare && mode === "book-switch") b.w.App.init({ daten: { kontakte: [{ id: "new-book", vorname: "Preserve new book" }],
          einstellungen: { adressen: { foto: false } } }, neu: false, regional: { language: "en", timeZone: "UTC" } });
        if (mode === "timeout") {
          const timer = b.timers.find(t => t.delay === 12000 && !t.cancelled); assert.ok(timer); timer.fn(); timer.cancelled = true; continue;
        }
        b.w.App.kontaktGruppenErgebnis({ ok: true, version: mode === "old-schema" ? 16 : 17,
          requestId: message.requestId, device_id: base.deviceId,
          fingerprint: mode === "foreign-source" ? "b".repeat(64) : fingerprint,
          uid: base.uid, action: message.action, token, state: prepare ? "prepared" : "saved",
          groups: prepare ? (remoteEdit ? ["Work"] : ["Family"]) :
            (mode === "bad-readback" ? ["Family"] : multiple ? ["Family", "Coworkers"] : [expectedProvider]),
          catalog: prepare ? (mode === "ambiguous" ? ["Coworkers", "Colleagues"] : mode === "localized-existing" ? ["Family", "Work"] : ["Family", "Coworkers"]) : [],
          account: !prepare && mode === "account-changed" ? { ...account, name: "other" } : account });
      }
      await tick();
    }
    await promise;
    assert.equal(prepareCount, saveFailed ? 0 : 1, mode + ": expected native preparation; marker=" + JSON.stringify(local.telefonGruppenAenderung) + "; stand=" + JSON.stringify(local.telefonGruppenStand));
    assert.equal(applyCount, localized || ["success", "auto-save", "auto-save-multiple", "retained-save", "retained-stand-save", "auto-peer", "photo-busy", "explicit-source", "bad-readback", "account-changed"].includes(mode) ? 1 : 0);
    if (localized || ["success", "auto-save", "auto-save-multiple", "retained-save", "retained-stand-save", "auto-peer", "photo-busy", "explicit-source"].includes(mode)) {
      assert.equal(local.telefonGruppenAenderung, null);
      assert.deepEqual(plain(local.telefonGruppenStand.groups).sort(), multiple ? ["Colleagues", "Family"] : [localized ? mode === "localized-custom" ? "My own group" : "Work" : "Colleagues"]);
      assert.ok(b.saves().some(m => JSON.parse(m.text).kontakte[0].telefonGruppenAenderung === null));
    } else assert.ok(local.telefonGruppenAenderung, "Failure or concurrent changes preserve local intent");
    if (remoteEdit) assert.deepEqual(plain(local.telefonGruppenAenderung.beobachtet.groups), ["Work"]);
    if (mode === "book-switch") {
      assert.equal(b.t.daten().kontakte.length, 1);
      assert.equal(b.t.daten().kontakte[0].id, "new-book", "Late preparation must leave the newly opened book untouched");
    }
  } finally { b.close(); }
}

(async () => {
  for (const web of harness.exports.roots) {
    for (const mode of ["success", "auto-save", "auto-save-multiple", "retained-save", "retained-save-failed", "retained-save-remote", "retained-stand-save", "retained-stand-save-failed", "retained-stand-save-remote", "localized-new", "localized-existing", "localized-custom", "auto-peer", "photo-busy", "explicit-source", "observed-auto", "no-base", "old-capability", "duplicate", "save-failed", "remote-edit", "local-edit",
      "removed", "revoked", "key-changed", "book-switch", "timeout", "foreign-source", "old-schema", "bad-readback", "account-changed", "ambiguous"]) {
      try { await run(web, mode); } catch (error) { error.message = web + " / " + mode + ": " + error.message; throw error; }
    }
    console.log("PASS contact group write: " + web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
