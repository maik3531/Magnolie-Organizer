"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const plain = value => JSON.parse(JSON.stringify(value));
async function until(test) { for (let n = 0; n < 4000; n++) { if (test()) return; await new Promise(r => setTimeout(r, 1)); } throw Error("Time review timeout"); }
async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, messages = [];
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const message = JSON.parse(text); messages.push(message);
    if (message.cmd === "speichern") queueMicrotask(() => w.App.gespeichert({ id: message.id, ok: true }));
    if (message.cmd === "mutations_snapshot") queueMicrotask(() => w.App.mutationsSnapshot({ token: message.token, ok: true }));
  } } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  const T = w.OrganizerTest, now = Date.now(), older = now - 20000, newer = now - 10000;
  const person = { id: "local", vorname: "Person", nachname: "Local", geaendert: now,
    emailEintraege: [{ wert: "person@example.test", label: "HOME" }] };
  const offer = (time, version = 1, name = "Remote") => ({ id: "message-" + version, von: "peer", inhalt: {
    art: "kontakt_sync", fassung: 3, freigabeId: "share", version, quelle: "peer", geaendert: Date.now(), inhaltGeaendert: time,
    kontakt: { vorname: "Person", nachname: name, firma: "", notiz: "", geburtstag: "", anzeigename: "", jubilaeum: "", vcardName: [],
      telefone: [], emailEintraege: [{ art: "HOME", wert: "person@example.test" }], anschriften: [] } } });
  const inbox = (rows, versions = [1, 2, 3]) => w.App.baumStand({ an: true, moeglich: true, kennung: "local", name: "Local", eingang: rows,
    partner: [{ kennung: "peer", name: "Peer", bestaetigt: true, kontaktFaehigkeiten: { kontakt_sync: versions } }] });
  const reset = (people = [person], automatic = false) => {
    w.App.init({ daten: { kontakte: plain(people), einstellungen: { sync: { kontaktNeuereBevorzugen: automatic } } }, neu: false, regional: { language: "en" } });
    inbox([]); messages.length = 0; return T.daten().kontakte[0];
  };
  const receipts = () => messages.filter(m => m.cmd === "baum_eingang_geleert").flatMap(m => m.ids);
  try {
    let k = reset();
    assert.equal(await T.kontaktInhaltszeit(k), 0, "generic modification/import time became a content date");
    assert.equal(await T.merkeKontaktInhaltszeit(k, older), true);
    assert.equal(await T.kontaktInhaltszeit(k), older);
    await T.synchronisiereKontakteMit("peer");
    let sent = messages.findLast(m => m.cmd === "baum_teilen" && m.art === "kontakt_sync").inhalt;
    assert.equal(sent.fassung, 3); assert.equal(sent.inhaltGeaendert, older);
    assert.ok(sent.geaendert > sent.inhaltGeaendert);
    inbox([], [1, 2]); messages.length = 0; await T.synchronisiereKontakteMit("peer");
    sent = messages.findLast(m => m.cmd === "baum_teilen" && m.art === "kontakt_sync").inhalt;
    assert.equal(sent.fassung, 2); assert.equal(sent.inhaltGeaendert, undefined);
    k.notiz = "Untracked change";
    assert.equal(await T.kontaktInhaltszeit(k), 0, "stale hash still authorized a date");
    const pending = T.merkeKontaktInhaltszeit(k, newer); k.notiz = "Changed during hashing";
    assert.equal(await pending, false); assert.equal(await T.kontaktInhaltszeit(k), 0);

    k = reset(); await T.merkeKontaktInhaltszeit(k, older); inbox([offer(newer)]);
    T.oeffneEinstellungen(); w.document.querySelector("#einst-tab-baum").click();
    w.document.querySelector("#baum-kontakte-annehmen").click();
    await until(() => w.document.querySelector('[data-kontakt-entscheidung="newer"]')?.disabled === false);
    w.document.querySelector('[data-kontakt-entscheidung="newer"]').click();
    await until(() => receipts().length === 1);
    k = T.daten().kontakte[0]; assert.equal(k.nachname, "Remote");
    assert.equal(await T.kontaktInhaltszeit(k), newer, "adoption used synchronization time instead of the source date");

    k = reset(); await T.merkeKontaktInhaltszeit(k, older);
    T.oeffneEinstellungen(); w.document.querySelector("#einst-tab-sync").click();
    const automatic = w.document.querySelector("#sync-kontakte-neuer");
    assert.equal(automatic.checked, false); automatic.checked = true; automatic.dispatchEvent(new w.Event("change"));
    w.App.init({ daten: plain(T.daten()), neu: false, regional: { language: "en" } });
    assert.equal(T.daten().einstellungen.sync.kontaktNeuereBevorzugen, true);
    inbox([offer(newer)]); messages.length = 0;
    assert.equal((await T.uebernehmeBaumKontakte()).konflikte, 0);
    k = T.daten().kontakte[0]; assert.equal(k.nachname, "Remote");
    assert.equal(await T.kontaktInhaltszeit(k), newer);
    inbox([offer(older, 2, "Older version")]);
    assert.equal((await T.uebernehmeBaumKontakte()).konflikte, 0);
    assert.equal(T.daten().kontakte[0].nachname, "Remote");
    assert.equal(await T.kontaktInhaltszeit(T.daten().kontakte[0]), newer);

    for (const mode of ["missing-local", "missing-source", "legacy-source", "equal", "future", "name-only", "ambiguous"]) {
      const people = mode === "ambiguous" ? [person, { ...person, id: "second" }] :
        mode === "name-only" ? [{ ...person, emailEintraege: [] }] : [person];
      k = reset(people, true);
      if (mode !== "missing-local") await T.merkeKontaktInhaltszeit(k, older);
      const message = offer(mode === "missing-source" ? 0 : mode === "equal" ? older : mode === "future" ? now + 600000 : newer);
      if (mode === "legacy-source") { message.inhalt.fassung = 2; delete message.inhalt.inhaltGeaendert; }
      if (mode === "name-only") { message.inhalt.kontakt.emailEintraege = []; message.inhalt.kontakt.nachname = "Local"; message.inhalt.kontakt.notiz = "Different"; }
      inbox([message]); messages.length = 0;
      const result = await T.uebernehmeBaumKontakte();
      assert.equal(result.konflikte, 1, mode + " bypassed manual review");
      assert.equal(receipts().length, 0); assert.equal(T.daten().kontakte[0].nachname, "Local");
    }
    k = reset(); const stamp = T.merkeKontaktInhaltszeit(k, older);
    w.App.init({ daten: { kontakte: [{ id: "replacement", vorname: "Other profile" }] }, neu: false });
    assert.equal(await stamp, false); assert.equal(T.daten().kontakte[0].kontaktZeit, undefined);
    reset([]);
    assert.equal(T.uebernehmeBaumAngebot({ id: "legacy-private-fields", von: "peer", inhalt: {
      art: "kontakt", vorname: "Incoming", syncQuellen: { source: { id: "foreign", etag: "v1" } },
      syncKonflikte: { source: { kontakt: { vorname: "Injected" } } },
      kontaktProviderKonflikte: { source: { entfernt: true, mapping: { id: "foreign" } } },
      baumKontakt: { freigabeId: "injected" }, kontaktZeit: { zeit: newer, hash: "a".repeat(64) },
      vcardRev: newer, fotoManuell: true, importBindungen: ["urn:magnolie:import:android:" + "a".repeat(64)]
    } }), true);
    const imported = T.daten().kontakte[0];
    assert.equal(Object.keys(imported.syncQuellen || {}).length, 0);
    assert.equal(imported.syncKonflikte, undefined); assert.equal(imported.kontaktProviderKonflikte, undefined);
    assert.ok(!imported.baumKontakt); assert.equal(imported.kontaktZeit, undefined);
    assert.equal(imported.vcardRev, undefined); assert.equal(imported.fotoManuell, false);
    assert.equal(imported.importBindungen.length, 0);
    console.log("BAUM CONTENT TIME REVIEW PASSED: " + web);
  } finally { w.close(); }
}
(async () => { for (const web of [path.resolve(__dirname, "../app/web"), path.resolve(__dirname, "../../magnolie-organizer/web")]) await check(web); })()
  .catch(error => { console.error(error); process.exitCode = 1; });
