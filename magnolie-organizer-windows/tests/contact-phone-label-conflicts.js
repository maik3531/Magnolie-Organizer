"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
async function check(web, mode) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const m = JSON.parse(text);
    if (m.cmd === "speichern") queueMicrotask(() => w.App.gespeichert({ id: m.id, ok: true }));
    if (m.cmd === "mutations_snapshot") queueMicrotask(() => w.App.mutationsSnapshot({ token: m.token, ok: true }));
  } } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    const local = { id: "local", vorname: "Alex", nachname: "Fixture",
      emailEintraege: [{ wert: "alex@example.test", label: "HOME" }],
      telefone: [{ wert: "+49 30 5550123", label: "CELL", typen: ["CELL"] }] };
    const address = { strasse: "Testweg 12", plz: "10115", ort: "Berlin", region: "Berlin", land: "Germany" };
    if (mode.startsWith("address")) local.anschriften = [{ ...address, label: "Privat", typen: ["HOME"] }];
    w.App.init({ neu: false, daten: { kontakte: [local] } });
    const T = w.OrganizerTest;
    const offer = { id: "offer", von: "peer", inhalt: { art: "kontakt_sync", fassung: 2,
      freigabeId: "share", version: 1, quelle: "peer", kontakt: {
        vorname: "Alex", nachname: "Fixture", anschriften: mode.startsWith("address") ?
          [{ ...address, plz: mode === "address-value" ? "10117" : address.plz, art: "Home" }] : [],
        emailEintraege: [{ wert: mode === "email-value" ? "other@example.test" : "alex@example.test",
          art: mode.startsWith("email") ? "WORK" : "HOME" }],
        telefone: [{ wert: mode === "number" ? "+49305550999" : "+49305550123", art: "HOME" }],
        notiz: mode === "note" ? "Real different information" : "" } } };
    const plan = T.baumKontaktPruefung(offer);
    const labelsOnly = ["labels", "address-labels", "email-labels"].includes(mode);
    assert.equal(plan.art, labelsOnly ? "gleich" : "konflikt",
      "Source labels alone are not value conflicts; real changes must stay visible");
    if (labelsOnly) {
      const imported = { ...local, id: undefined, telefone: [{ wert: "+49305550123", label: "HOME", typen: ["HOME"] }],
        emailEintraege: [{ wert: "alex@example.test", label: mode === "email-labels" ? "WORK" : "HOME" }] };
      if (mode === "address-labels") imported.anschriften = [{ ...address, label: "Home", typen: ["HOME"] }];
      const preview = w.App.importErgebnis({ kontakte: [imported] });
      assert.equal(w.document.querySelector('[data-import-entscheidung="0"]').value, "keep",
        "File preview presented identical values with different provider labels as a conflict");
      w.document.querySelector(".kontakt-datei-pruefung .dialog-knoepfe button:last-child").click();
      await preview;
      w.App.baumStand({ an: true, moeglich: true, kennung: "local", eingang: [offer],
        partner: [{ kennung: "peer", name: "Fixture phone", bestaetigt: true }] });
      const result = await T.uebernehmeBaumKontakte();
      assert.equal(result.konflikte, 0);
      const saved = T.daten().kontakte[0];
      assert.equal(T.daten().kontakte.length, 1);
      assert.ok(saved.telefone.some(e => e.label === "CELL"), "Existing phone metadata was discarded");
      assert.equal(saved.telefone.length, 1, "Unverified incoming label was accumulated instead of retaining the canonical local label");
      if (mode === "address-labels") {
        assert.ok(saved.anschriften.some(e => e.label === "Privat"), "Existing address label was discarded");
        assert.equal(saved.anschriften.length, 1, "Unverified incoming address label was accumulated");
        assert.ok(saved.anschriften.every(e => e.plz === "10115" && e.strasse === address.strasse));
      }
      if (mode === "email-labels") assert.equal(saved.emailEintraege[0].label, "HOME", "Existing email label was replaced");
    }
  } finally { w.close(); }
}
(async () => {
  const results = [];
  for (const web of require("./web-test-roots")) for (const mode of (process.argv[2] ? process.argv[2].split(",") :
    ["labels", "number", "note", "address-labels", "address-value", "email-labels", "email-value"])) {
    try { await check(web, mode); results.push({ web, mode, passed: true }); }
    catch (error) { results.push({ web, mode, passed: false, error: error.message }); }
  }
  console.log(JSON.stringify(results, null, 2));
  assert.ok(results.every(r => r.passed));
})().catch(error => { console.error(error); process.exitCode = 1; });
