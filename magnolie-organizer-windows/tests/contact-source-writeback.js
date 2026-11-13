"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const clone = value => JSON.parse(JSON.stringify(value)), tick = () => new Promise(resolve => setTimeout(resolve, 5));
const source = { deviceId: "notes:22222222-2222-4222-8222-222222222222", fingerprint: "a".repeat(64), uid: "native-fixture" };
const account = { name: "fixture@example.invalid", type: "provider", data_set: "" }, token = "33333333-3333-4333-8333-333333333333";
async function check(web, route, field, mode) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, messages = []; let saveAcks = 0;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const m = JSON.parse(text); messages.push(m);
    if (m.cmd === "speichern") queueMicrotask(() => { w.App.gespeichert({ id: m.id, ok: true }); saveAcks++; });
    if (m.cmd === "mutations_snapshot") queueMicrotask(() => w.App.mutationsSnapshot({ token: m.token, ok: true }));
  } } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    const T = w.OrganizerTest, provider = "thunderbird-addressbook:fixture:book";
    const card = newer => ({ id: "local", uid: "fixture", vorname: "Alex", nachname: "Fixture", sync: true,
      telefone: [{ wert: "+49305550123", label: field === "telefone" && !newer ? "HOME" : "CELL", typen: [field === "telefone" && !newer ? "HOME" : "CELL"] }],
      emailEintraege: [{ wert: "alex@example.test", label: field === "emailEintraege" && newer ? "WORK" : "HOME", typen: [field === "emailEintraege" && newer ? "WORK" : "HOME"] }] });
    const native = clone(T.kontaktWerteProjektion(card(false))), wanted = clone(T.kontaktWerteProjektion(card(true)));
    const local = card(route === "notes" || mode === "revert"); local.telefonWerteStand = { ...source, fields: clone(native) };
    if (mode === "no-baseline") delete local.telefonWerteStand;
    if (mode === "unknown" || mode === "revert") local.telefonWerteAenderung = { version: 1,
      base: { ...source, fields: { [field]: clone(native[field]) } },
      beobachtet: { ...source, fields: clone(native) }, ...(mode === "unknown" ? { unbekannt: [field] } : {}) };
    if (route === "provider") {
      local.syncQuellen = { [provider]: { id: "remote", etag: '"old"' } };
      local.syncKonflikte = { [provider]: { kontakt: card(mode !== "revert"), mapping: { id: "remote", etag: '"new"' } } };
    }
    w.App.init({ neu: false, daten: { kontakte: [local] } });
    // A second installed transport is not a second writable contact authority.
    w.App.telefonStand({ peers: [{ device_id: "kde-fixture", state: "online_wifi", provider: "kdeconnect" },
      { device_id: source.deviceId.slice(6), own_device: true, remote_own_device: true,
        state: mode === "offline" ? "offline" : "online_wifi", contact_values_write_available: true, contacts_fingerprint: source.fingerprint }] });
    if (route === "provider") {
      T.oeffneSyncKontaktKonflikt("local", provider);
      w.document.querySelector('[data-sync-kontakt-entscheidung="replace"]').click();
      for (let i = 0; i < 600 && T.daten().kontakte[0].syncKonflikte; i++) await tick();
      assert.equal(T.daten().kontakte[0].syncKonflikte, undefined);
    } else if (route === "file") {
      await T.merkeKontaktInhaltszeit(T.daten().kontakte[0], Date.now() - 20000);
      const incoming = card(true); delete incoming.id; incoming.vcardRev = Date.now() - 10000;
      const importing = w.App.importErgebnis({ kontakte: [incoming] });
      for (let i = 0; i < 600 && !w.document.querySelector('.kontakt-datei-pruefung [aria-busy="false"]'); i++) await tick();
      assert.ok(w.document.querySelector('.kontakt-datei-pruefung [aria-busy="false"]'));
      w.document.querySelector("[data-import-anwenden]").click(); await importing;
    } else {
      await T.merkeKontaktInhaltszeit(T.daten().kontakte[0], Date.now() - 10000);
      const offer = { id: "offer", von: "peer", inhalt: { art: "kontakt_sync", fassung: 3,
        freigabeId: "share", version: 1, quelle: "peer", inhaltGeaendert: Date.now() - 20000,
        kontakt: T.kontaktBaumInhalt(T.normalisiere({ kontakte: [card(false)] }).kontakte[0], 2, false).kontakt } };
      w.App.baumStand({ an: true, moeglich: true, kennung: "local", eingang: [offer], partner: [{ kennung: "peer", bestaetigt: true }] });
      assert.equal((await T.uebernehmeBaumKontakte()).konflikte, 0);
    }
    const contact = T.daten().kontakte[0];
    if (mode === "no-baseline" || mode === "revert") {
      assert.ok(!contact.telefonWerteAenderung, mode === "revert" ? "Returning to the native baseline left a stale write intent" : "Unbound source invented a Notes write authority");
      for (let i = 0; i < 70; i++) await tick();
      assert.equal(messages.some(m => m.cmd === "telefon_kontaktwerte"), false);
      return;
    }
    assert.ok(contact.telefonWerteAenderung, "Confirmed source reconciliation did not queue the older Notes source for writeback");
    if (mode === "unknown") assert.deepEqual(Array.from(contact.telefonWerteAenderung.unbekannt), [field],
      "Source reconciliation itself confirmed an unknown baseline");
    let prepares = 0, applies = 0;
    const deadline = Date.now() + (mode === "offline" || mode === "unknown" ? 400 : 2500);
    while (Date.now() < deadline) {
      const message = messages.shift();
      if (!message) { if (applies && contact.telefonWerteAenderung === null) break; await tick(); continue; }
      if (message.cmd !== "telefon_kontaktwerte") continue;
      assert.ok(saveAcks, "Source write preceded local SaveACK"); assert.equal(message.device_id, source.deviceId);
      const result = { ok: true, version: 19, requestId: message.requestId, request_id: message.requestId,
        action: message.action, uid: source.uid, device_id: source.deviceId, fingerprint: source.fingerprint,
        token, state: message.action === "prepare" ? "prepared" : "saved", account: clone(account) };
      if (message.action === "prepare") {
        prepares++; result.fields = Object.fromEntries(message.field_names.map(name => [name, clone(native[name])]));
        if (mode === "changed" || mode === "unknown") result.fields.telefone[0].wert = "+49309999999";
      } else {
        applies++; Object.assign(native, clone(message.fields)); result.fields = clone(message.fields);
      }
      w.App.kontaktWerteErgebnis(result); await tick();
      if (mode === "changed" && prepares && !applies) break;
    }
    if (mode === "success") {
      assert.equal(applies, 1); assert.deepEqual(native[field], wanted[field]);
      assert.equal(contact.telefonWerteAenderung, null, "Verified source write did not clear its pending intent");
      T.uebernehmeTelefonKontaktWerte(contact, clone(native), source);
      assert.equal(contact.telefonWerteAenderung, null, "Re-reading the updated phone source recreated the pending change");
      assert.deepEqual(clone(T.kontaktWerteProjektion(contact)[field]), wanted[field], "Phone readback reverted the canonical field");
    } else { assert.equal(applies, 0); assert.ok(contact.telefonWerteAenderung); }
    if (mode === "offline") assert.equal(prepares, 0);
    if (mode === "unknown") assert.deepEqual(Array.from(contact.telefonWerteAenderung.unbekannt), [field], "Automatic reconciliation confirmed an unknown base");
  } finally { w.close(); }
}
(async () => {
  const results = [];
  for (const web of require("./web-test-roots")) {
    const cases = [["notes", "telefone", "success"], ["notes", "emailEintraege", "success"], ["file", "telefone", "success"], ["file", "emailEintraege", "success"],
      ["notes", "telefone", "offline"], ["notes", "telefone", "changed"],
      ["notes", "telefone", "unknown"], ["notes", "telefone", "no-baseline"]];
    if (fs.readFileSync(path.join(web, "anwendung.js"), "utf8").includes("oeffneSyncKontaktKonflikt: oeffneSyncKontaktKonflikt"))
      cases.push(["provider", "telefone", "success"], ["provider", "emailEintraege", "success"], ["provider", "telefone", "revert"]);
    for (const [route, field, mode] of cases) {
      if (process.argv[2] && !process.argv[2].split(",").includes(mode)) continue;
      if (process.argv[3] && process.argv[3] !== route) continue;
      try { await check(web, route, field, mode); results.push({ web, route, field, mode, passed: true }); }
      catch (error) { results.push({ web, route, field, mode, passed: false, error: error.message }); }
    }
  }
  console.log(JSON.stringify(results, null, 2)); assert.ok(results.every(r => r.passed));
})().catch(error => { console.error(error); process.exitCode = 1; });
