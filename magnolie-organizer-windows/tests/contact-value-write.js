"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const plain = value => JSON.parse(JSON.stringify(value));
const source = { deviceId: "notes:22222222-2222-4222-8222-222222222222", fingerprint: "a".repeat(64), uid: "native-lookup" };
const account = { name: "synthetic@example.invalid", type: "provider", data_set: "" };
const token = "33333333-3333-4333-8333-333333333333";
const fields = { telefone: [{ art: "mobil", wert: "222" }, { art: "privat", wert: "333" }], emailEintraege: [] };
function boot(web, keepInitial = false) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://fixture.magnolie.invalid/", pretendToBeVisual: true });
  const w = dom.window, messages = [];
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test"; w.webkit = { messageHandlers: { test: { postMessage(raw) { messages.push(JSON.parse(raw)); } } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  w.App.init({ daten: { kontakte: [] }, neu: false }); if (!keepInitial) messages.length = 0;
  return { w, messages, t: w.OrganizerTest };
}
function reply(message) {
  return { ok: true, version: 19, requestId: message.requestId, request_id: message.requestId, action: message.action,
    uid: message.uid, device_id: message.device_id, fingerprint: message.fingerprint, token,
    state: message.action === "prepare" ? "prepared" : "saved", account: plain(account),
    fields: plain(message.action === "prepare" ? fields : message.fields) };
}
async function run(web, mode) {
  const b = boot(web);
  try {
    const names = ["telefone", "emailEintraege"];
    const preparation = b.t.kontaktWerteAbfragen(plain(source), "prepare", { field_names: names });
    let message = b.messages.find(value => value.cmd === "telefon_kontaktwerte"); assert.ok(message);
    const prepared = reply(message);
    if (mode === "oversize-report") {
      prepared.fields.telefone = Array.from({ length: 100 }, (_, i) => ({ art: "mobil", wert: i + "x".repeat(4000) }));
      b.w.App.kontaktWerteErgebnis(prepared); await assert.rejects(preparation); return;
    }
    b.w.App.kontaktWerteErgebnis(prepared); await preparation;
    b.messages.length = 0;
    const extra = { token, fields: plain(fields), account: plain(account) }, bound = plain(source);
    const saved = b.t.kontaktWerteAbfragen(bound, "apply", extra);
    message = b.messages.find(value => value.cmd === "telefon_kontaktwerte"); assert.ok(message);
    const result = reply(message);
    if (mode === "success") result.fields.telefone.reverse();
    else if (mode === "captured") { extra.fields.telefone[0].wert = "late local edit"; bound.uid = "late source"; }
    else if (mode === "request_id") result.request_id = "44444444-4444-4444-8444-444444444444";
    else if (mode === "device") result.device_id = "notes:other";
    else if (mode === "fingerprint") result.fingerprint = "b".repeat(64);
    else if (mode === "uid") result.uid = "foreign-native-contact";
    else if (mode === "token") result.token = "44444444-4444-4444-8444-444444444444";
    else if (mode === "account") result.account.name = "foreign@example.invalid";
    else if (mode === "mask") delete result.fields.emailEintraege;
    else if (mode === "readback") result.fields.telefone[0].wert = "old number";
    else if (mode === "state") result.state = "prepared";
    else if (mode === "extra") result.unrequested_private_field = "must not pass";
    else if (mode === "kind") result.fields.telefone[0].art = "fax";
    else if (mode === "boolean") result.fields.telefone[0].wert = true;
    else if (mode === "duplicate") result.fields.telefone.push(plain(result.fields.telefone[0]));
    b.w.App.kontaktWerteErgebnis(result);
    if (["success", "captured"].includes(mode)) assert.equal((await saved).state, "saved");
    else await assert.rejects(saved);
  } finally { b.w.close(); }
}
function metadata(web) {
  const b = boot(web);
  try {
    const contact = { id: "saved", uid: "local", telefone: [{ typen: ["CELL"], wert: "111" }], mobil: "111", telefon: "",
      emailEintraege: [{ typen: ["WORK"], wert: "old@example.test" }], emails: ["old@example.test"], email: "old@example.test",
      telefonGruppenStand: { ...plain(source), groups: ["Work"] } };
    b.t.daten().kontakte.push(contact);
    const initial = plain(b.t.kontaktWerteProjektion(contact));
    contact.telefonWerteStand = { ...plain(source), fields: plain(initial) };
    const phones = value => { contact.telefone = [{ typen: ["CELL"], wert: value }]; contact.mobil = value; };
    const emails = value => { contact.emailEintraege = [{ typen: ["WORK"], wert: value }]; contact.email = value; contact.emails = [value]; };
    phones("222"); assert.equal(b.t.merkeTelefonWerteAenderung(contact, initial), true);
    assert.deepEqual(plain(contact.telefonWerteAenderung.base.fields), { telefone: initial.telefone });
    assert.ok(!contact.telefonWerteAenderung.unbekannt, "Known native baseline became unknown");
    const old = plain(b.t.kontaktWerteProjektion(contact)); phones("333"); emails("new@example.test");
    b.t.merkeTelefonWerteAenderung(contact, old);
    assert.deepEqual(plain(contact.telefonWerteAenderung.base.fields), initial, "Offline re-edits replaced the shared base");
    const stored = plain(b.t.daten()); b.w.App.init({ daten: stored, neu: false });
    const reopened = b.t.daten().kontakte.find(value => value.id === contact.id);
    assert.deepEqual(plain(reopened.telefonWerteAenderung.base.fields), initial, "Reopen lost pending field intent");
    const beforeUndo = plain(b.t.kontaktWerteProjektion(contact)); phones("111"); emails("old@example.test");
    b.t.merkeTelefonWerteAenderung(contact, beforeUndo); assert.equal(contact.telefonWerteAenderung, null);
    delete contact.telefonWerteStand;
    phones("222"); b.t.merkeTelefonWerteAenderung(contact, initial);
    assert.deepEqual(plain(contact.telefonWerteAenderung.unbekannt), ["telefone"]);
    contact.telefonWerteAenderung.beobachtet = { ...plain(source), fields: { telefone: [{ art: "mobil", wert: "999" }] } };
    b.t.merkeTelefonWerteAenderung(contact, plain(b.t.kontaktWerteProjektion(contact)));
    assert.equal(contact.telefonWerteAenderung.base.fields.telefone[0].wert, "999", "Explicit re-save did not confirm the observed unknown base");
    assert.ok(!contact.telefonWerteAenderung.unbekannt);
    const established = plain(contact.telefonWerteAenderung.base);
    contact.telefonWerteAenderung.beobachtet.fields.telefone[0].wert = "888";
    b.t.merkeTelefonWerteAenderung(contact, plain(b.t.kontaktWerteProjektion(contact)));
    assert.deepEqual(plain(contact.telefonWerteAenderung.base), established, "Ordinary save overwrote an established conflicting base");
  } finally { b.w.close(); }
}
async function automatic(web, mode) {
  const b = boot(web, true), tick = () => new Promise(resolve => setTimeout(resolve, 5));
  try {
  const initial = { telefone: [{ art: "mobil", wert: "111" }], emailEintraege: [{ art: "arbeit", wert: "old@example.test" }] };
  const contact = { id: "automatic", uid: "local-contact", vorname: "Synthetic", nachname: "", firma: "", foto: "",
    telefone: [{ typen: ["CELL"], wert: "111" }], mobil: "111", telefon: "",
    emailEintraege: [{ typen: ["WORK"], wert: "old@example.test" }], emails: ["old@example.test"], email: "old@example.test",
    telefonWerteStand: { ...plain(source), fields: plain(initial) } };
  b.t.daten().kontakte.push(contact);
  const change = (phoneValue, emailValue = null) => b.t.wendeKontaktDatenAn(contact, {
    ...contact, ...(emailValue ? { emailEintraege: [{ typen: ["WORK"], wert: emailValue }], emails: [emailValue], email: emailValue } : {})
  }, { telefone: [{ typen: ["CELL"], wert: phoneValue }], anschriften: [], kontaktpersonen: [], sozialeMedien: [] });
  change("222", ["partial", "unrepresented"].includes(mode) ? "new@example.test" : null);
  const native = plain(initial);
  if (["remote", "partial"].includes(mode)) native.telefone[0].wert = "999";
  if (mode === "unrepresented") native.emailEintraege[0].wert = "hidden@example.invalid";
  const peer = { device_id: source.deviceId.slice(6), own_device: true, remote_own_device: true, state: "online_wifi",
    contact_values_write_available: mode !== "no-capability", contacts_fingerprint: source.fingerprint };
  if (mode === "duplicate") b.t.daten().kontakte.push({ ...plain(contact), id: "other-local" });
  b.w.App.telefonStand({ peers: [peer] });
  let applyCount = 0, prepareCount = 0, saveAcks = 0, durableClear = false, edited = false;
  const deadline = Date.now() + 3500;
    while (Date.now() < deadline) {
      const message = b.messages.shift();
      if (!message) {
        if (["no-capability", "duplicate"].includes(mode) && Date.now() > deadline - 2600) break;
        if (mode === "save-failed" && saveAcks || mode === "remote" && prepareCount && saveAcks >= 2) break;
        if (applyCount && (["partial", "unrepresented", "bad-readback"].includes(mode) || durableClear)) break;
        await tick(); continue;
      }
      if (message.cmd === "speichern") {
        const data = JSON.parse(message.text);
        if (data?.kontakte?.find(value => value.id === contact.id)?.telefonWerteAenderung === null) durableClear = true;
        b.w.App.gespeichert({ id: message.id, ok: mode !== "save-failed" }); saveAcks++; await tick(); continue;
      }
      if (message.cmd !== "telefon_kontaktwerte") continue;
      assert.ok(saveAcks, "Native field operation preceded local SaveACK");
      const result = reply(message);
      if (message.action === "prepare") {
        prepareCount++;
        result.fields = Object.fromEntries(message.field_names.map(name => [name, plain(native[name])]));
        if (mode === "edit-before-prepare" && !edited) { edited = true; change("333"); }
      } else {
        applyCount++;
        if (["late-edit", "late-undo"].includes(mode) && !edited) { edited = true; change(mode === "late-edit" ? "333" : "111"); }
        for (const name of Object.keys(message.fields)) native[name] = plain(message.fields[name]);
        result.fields = plain(message.fields);
        if (mode === "bad-readback") result.fields.telefone[0].wert = "old number";
      }
      b.w.App.kontaktWerteErgebnis(result); await tick();
    }
    if (["success", "late-edit", "late-undo", "edit-before-prepare"].includes(mode)) {
      assert.equal(contact.telefonWerteAenderung, null, mode + ": completed native readback left pending fields");
      assert.equal(native.telefone[0].wert, mode === "late-undo" ? "111" : ["late-edit", "edit-before-prepare"].includes(mode) ? "333" : "222");
      assert.ok(durableClear, mode + ": marker cleanup was not sent through durable save");
      assert.equal(applyCount, ["late-edit", "late-undo"].includes(mode) ? 2 : 1);
    } else if (mode === "partial") {
      assert.equal(applyCount, 1); assert.equal(native.telefone[0].wert, "999"); assert.equal(native.emailEintraege[0].wert, "new@example.test");
      assert.deepEqual(Object.keys(contact.telefonWerteAenderung.base.fields), ["telefone"]);
      assert.equal(contact.telefonWerteAenderung.base.fields.telefone[0].wert, "111");
    } else if (mode === "unrepresented") {
      assert.equal(applyCount, 1); assert.equal(native.telefone[0].wert, "222"); assert.equal(native.emailEintraege[0].wert, "hidden@example.invalid");
      assert.deepEqual(Object.keys(contact.telefonWerteAenderung.base.fields), ["emailEintraege"]);
    } else {
      assert.ok(contact.telefonWerteAenderung, mode + ": unsuccessful/unavailable operation cleared intent");
      assert.equal(applyCount, mode === "bad-readback" ? 1 : 0);
    }
  } finally { b.w.close(); }
}
function reverse(web) {
  const b = boot(web);
  try {
    const make = () => ({ id: "reverse", uid: "local", telefon: "", mobil: "111",
      telefone: [{ typen: ["CELL"], wert: "111", label: "Keep local label", vcardParameter: ["X-FIXTURE=preserved"] }],
      email: "old@example.test", emails: ["old@example.test"], emailEintraege: [{ typen: ["WORK"], wert: "old@example.test" }],
      telefonGruppenStand: { ...plain(source), groups: ["Work"] } });
    const contact = make(); b.t.daten().kontakte.push(contact);
    const initial = plain(b.t.kontaktWerteProjektion(contact));
    assert.equal(b.t.uebernehmeTelefonKontaktWerte(contact, initial, source), true);
    const changed = plain(initial); changed.telefone[0].wert = "222";
    b.t.uebernehmeTelefonKontaktWerte(contact, changed, source);
    assert.equal(b.t.kontaktWerteProjektion(contact).telefone[0].wert, "222", "Phone-only edit was not adopted from the common base");
    assert.equal(contact.telefone[0].label, "Keep local label");
    assert.deepEqual(plain(contact.telefone[0].vcardParameter), ["X-FIXTURE=preserved"]);
    b.t.wendeKontaktDatenAn(contact, { ...contact }, { telefone: contact.telefone.map(row => ({ ...row, wert: "333" })),
      anschriften: [], kontaktpersonen: [], sozialeMedien: [] });
    const mixed = plain(changed); mixed.emailEintraege[0].wert = "remote@example.test";
    b.t.uebernehmeTelefonKontaktWerte(contact, mixed, source);
    assert.equal(b.t.kontaktWerteProjektion(contact).telefone[0].wert, "333", "A phone read replaced an offline local number");
    assert.equal(b.t.kontaktWerteProjektion(contact).emailEintraege[0].wert, "remote@example.test", "Independent remote field was not merged");
    assert.equal(contact.telefonWerteAenderung.base.fields.telefone[0].wert, "222");
    mixed.telefone[0].wert = "444"; b.t.uebernehmeTelefonKontaktWerte(contact, mixed, source);
    assert.equal(contact.telefonWerteAenderung.base.fields.telefone[0].wert, "222", "Concurrent remote field replaced the common base");
    assert.equal(contact.telefonWerteAenderung.beobachtet.fields.telefone[0].wert, "444");
    const foreign = plain(source); foreign.fingerprint = "b".repeat(64);
    assert.equal(b.t.uebernehmeTelefonKontaktWerte(contact, mixed, foreign), false);
    mixed.telefone[0].wert = "333"; b.t.uebernehmeTelefonKontaktWerte(contact, mixed, source);
    assert.equal(contact.telefonWerteAenderung, null, "Observed native convergence did not fulfill the saved wish");
    const unbound = make(); unbound.id = "first-observation";
    b.t.daten().kontakte.push(unbound); const different = plain(initial); different.telefone[0].wert = "999";
    b.t.uebernehmeTelefonKontaktWerte(unbound, different, source);
    assert.equal(b.t.kontaktWerteProjektion(unbound).telefone[0].wert, "111", "An unestablished first read overwrote local values");
    assert.ok(!unbound.telefonWerteStand.fields.telefone, "An observed difference was declared a common baseline");
    b.t.merkeTelefonWerteAenderung(unbound, plain(b.t.kontaktWerteProjektion(unbound)));
    assert.equal(unbound.telefonWerteAenderung.base.fields.telefone[0].wert, "999", "Explicit initial save did not use the observed native source");
  } finally { b.w.close(); }
}
async function backgroundRead(web, mode) {
  const b = boot(web, true), tick = () => new Promise(resolve => setTimeout(resolve, 5));
  try {
    b.t.daten().einstellungen.adressen.foto = false;
    const contact = { id: "read-source", vorname: "Synthetic", telefon: "", mobil: "111",
      telefone: [{ typen: ["CELL"], wert: "111" }], email: "old@example.test", emails: ["old@example.test"],
      emailEintraege: [{ typen: ["WORK"], wert: "old@example.test" }],
      telefonGruppenStand: { ...plain(source), groups: ["Work"] } };
    b.t.daten().kontakte.push(contact);
    const initial = plain(b.t.kontaktWerteProjektion(contact)); contact.telefonWerteStand = { ...plain(source), fields: initial };
    if (mode === "pending") {
      b.t.wendeKontaktDatenAn(contact, { ...contact }, { telefone: [{ typen: ["CELL"], wert: "333" }],
        anschriften: [], kontaktpersonen: [], sozialeMedien: [] });
    }
    b.w.App.telefonStand({ peers: [{ device_id: source.deviceId.slice(6), own_device: true, remote_own_device: true,
      state: "online_wifi", contacts_read_available: true, contacts_fingerprint: source.fingerprint, contact_values_write_available: false }] });
    let reads = 0, saved = false;
    const deadline = Date.now() + 2500;
    while (Date.now() < deadline && !saved) {
      const message = b.messages.shift(); if (!message) { await tick(); continue; }
      if (message.cmd === "speichern") {
        const stored = JSON.parse(message.text).kontakte?.find(value => value.id === contact.id);
        if (stored?.telefonWerteBeobachtet) saved = true;
        b.w.App.gespeichert({ id: message.id, ok: true }); await tick(); continue;
      }
      assert.notEqual(message.cmd, "telefon_kontaktwerte", "A read-only peer started a value write");
      if (message.cmd !== "telefon_kontaktfotos") continue;
      reads++;
      const card = { uid: source.uid, modified_ms: 200, foto: "", telefone: [{ typen: ["CELL"], wert: "222" }], mobil: "222",
        emailEintraege: mode === "filtered" ? [] : [{ typen: ["WORK"], wert: "remote@example.test" }],
        werteVollstaendig: mode === "filtered" ? ["telefone"] : ["telefone", "emailEintraege"] };
      b.w.App.kontaktFotos({ ok: true, requestId: message.requestId, device_id: source.deviceId, fingerprint: source.fingerprint,
        contacts: message.uids ? [card] : [{ uid: source.uid, modified_ms: 200 }] });
      await tick();
    }
    assert.equal(reads, 2, "Background contact reads depended on the disabled photo display setting");
    assert.ok(saved, "Observed source metadata was not durably saved");
    assert.equal(b.t.kontaktWerteProjektion(contact).telefone[0].wert, mode === "pending" ? "333" : "222");
    assert.equal(b.t.kontaktWerteProjektion(contact).emailEintraege[0].wert, mode === "filtered" ? "old@example.test" : "remote@example.test");
    if (mode === "pending") assert.equal(contact.telefonWerteAenderung.base.fields.telefone[0].wert, "111");
  } finally { b.w.close(); }
}
(async () => {
  const windows = path.resolve(__dirname, "../app/web"), linux = path.resolve(__dirname, "../../magnolie-organizer/web");
  assert.ok(fs.existsSync(path.join(windows, "index.html")), "The packaged Windows frontend is missing");
  const roots = [windows, ...(fs.existsSync(path.join(linux, "index.html")) ? [linux] : [])];
  for (const web of roots) {
    metadata(web);
    reverse(web);
    for (const mode of ["normal", "pending", "filtered"]) await backgroundRead(web, mode);
    for (const mode of ["success", "late-edit", "late-undo", "edit-before-prepare", "remote", "partial", "unrepresented", "bad-readback", "save-failed", "no-capability", "duplicate"])
      await automatic(web, mode);
    for (const mode of ["success", "captured", "request_id", "device", "fingerprint", "uid", "token", "account", "mask", "readback", "state", "extra", "kind", "boolean", "duplicate", "oversize-report"])
      await run(web, mode);
    const b = boot(web);
    try {
      for (const field_names of [[], ["telefone", "telefone"], ["foto"]])
        await assert.rejects(b.t.kontaktWerteAbfragen(source, "prepare", { field_names }));
      await assert.rejects(b.t.kontaktWerteAbfragen(source, "apply", { token, fields, account: null }));
      const large = { telefone: Array.from({ length: 100 }, (_, i) => ({ art: "mobil", wert: i + "x".repeat(4000) })) };
      await assert.rejects(b.t.kontaktWerteAbfragen(source, "apply", { token, fields: large, account }));
      assert.ok(!b.messages.some(value => value.cmd === "telefon_kontaktwerte"), "Malformed writes reached the native bridge");
    } finally { b.w.close(); }
    console.log("PASS contact value transport/readback: " + web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
