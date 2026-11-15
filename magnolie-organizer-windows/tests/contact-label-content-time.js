"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const tick = () => new Promise(resolve => setTimeout(resolve, 2));
async function until(test) { for (let i = 0; i < 1000; i++) { if (test()) return; await tick(); } throw new Error("Label content time timeout"); }
async function check(web, field, order, route) {
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
    const local = { id: "local", uid: "fixture", vorname: "Alex", nachname: "Fixture",
      emailEintraege: [{ wert: "alex@example.test", label: "HOME" }] };
    if (field === "telefone") local.telefone = [{ wert: "+49305550123", label: "CELL", typen: ["CELL"] }];
    if (field === "anschriften") local.anschriften = [{ strasse: "Testweg 12", plz: "10115", ort: "Berlin", label: "Privat" }];
    const incoming = JSON.parse(JSON.stringify(local)); delete incoming.id;
    const oldLabel = local[field][0].label, newLabel = field === "emailEintraege" ? "WORK" : "HOME";
    incoming[field][0].label = newLabel; incoming[field][0].typen = [];
    w.App.init({ neu: false, daten: { kontakte: [local] } });
    const T = w.OrganizerTest, now = Date.now(), localTime = now - 20000;
    await T.merkeKontaktInhaltszeit(T.daten().kontakte[0], localTime);
    const remoteTime = order === "unknown" ? 0 : localTime + (order === "newer" ? 10000 : -10000);
    if (route === "file") {
      incoming.vcardRev = remoteTime; incoming.geaendert = now;
      const running = w.App.importErgebnis({ kontakte: [incoming] });
      await until(() => w.document.querySelector('.kontakt-datei-pruefung [aria-busy="false"]'));
      assert.notEqual(w.document.querySelector('[data-import-entscheidung="0"]').value, "", "Label-only input required a conflict choice");
      w.document.querySelector("[data-import-anwenden]").click(); await running;
    } else {
      const wire = T.kontaktBaumInhalt(T.normalisiere({ kontakte: [incoming] }).kontakte[0], 2, false).kontakt;
      const offer = { id: "offer", von: "peer", inhalt: { art: "kontakt_sync", fassung: 3, freigabeId: "share",
        version: 1, quelle: "peer", geaendert: now, inhaltGeaendert: remoteTime, kontakt: wire } };
      w.App.baumStand({ an: true, moeglich: true, kennung: "local", eingang: [offer],
        partner: [{ kennung: "peer", name: "Phone", bestaetigt: true }] });
      assert.equal((await T.uebernehmeBaumKontakte()).konflikte, 0);
      const repeated = JSON.parse(JSON.stringify(offer)); repeated.id = "offer-repeated"; repeated.inhalt.version = 2;
      w.App.baumStand({ an: true, moeglich: true, kennung: "local", eingang: [repeated],
        partner: [{ kennung: "peer", name: "Phone", bestaetigt: true }] });
      assert.equal((await T.uebernehmeBaumKontakte()).konflikte, 0, "Unchanged source labels reopened a value conflict");
    }
    const saved = T.daten().kontakte[0], labels = Array.from(saved[field], row => row.label || "");
    assert.deepEqual(labels, [order === "newer" ? newLabel : oldLabel],
      "Canonical label must follow proven content time, not receipt time or a label union");
    assert.equal(T.daten().kontakte.length, 1);
    assert.equal(T.kontaktBaumInhalt(saved, 3, false).kontakt[field][0].art, order === "newer" ? newLabel : oldLabel,
      "The outbound phone representation did not use the canonical label");
    assert.equal(await T.kontaktInhaltszeit(saved), order === "newer" ? remoteTime : localTime,
      "Receipt/label handling changed the provenance-bound content timestamp");
  } finally { w.close(); }
}
(async () => {
  const results = [];
  for (const web of require("./web-test-roots")) for (const field of ["telefone", "emailEintraege", "anschriften"])
    for (const order of ["newer", "older", "unknown"]) for (const route of ["file", "notes"]) {
      try { await check(web, field, order, route); results.push({ web, field, order, route, passed: true }); }
      catch (error) { results.push({ web, field, order, route, passed: false, error: error.message }); }
    }
  console.log(JSON.stringify({ total: results.length, passed: results.filter(r => r.passed).length, failures: results.filter(r => !r.passed) }, null, 2));
  assert.ok(results.every(r => r.passed));
})().catch(error => { console.error(error); process.exitCode = 1; });
