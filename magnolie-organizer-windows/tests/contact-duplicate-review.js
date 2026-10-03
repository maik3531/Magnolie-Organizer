"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const tick = () => new Promise(r => setTimeout(r, 5));
async function check(web, mode) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, messages = [];
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const m = JSON.parse(text); messages.push(m);
    if (m.cmd === "speichern") queueMicrotask(() => w.App.gespeichert({ id: m.id, ok: true }));
    if (m.cmd === "mutations_snapshot") queueMicrotask(() => {
      if (mode === "stale") w.OrganizerTest.daten().kontakte[0].notiz = "Changed meanwhile";
      w.App.mutationsSnapshot({ token: m.token, ok: mode !== "snapshot-error" });
    });
  } } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    const T = w.OrganizerTest;
    w.App.init({ neu: false, regional: { language: "en" }, daten: {
      kontakte: [{ id: "keep", uid: "keep-uid", vorname: "Same", nachname: "Person", fotoManuell: true,
        geburtstag: "1980-05-06", notiz: "Local note",
        telefon: "01597777", importHerkunfte: ["Gmail"],
        email: "same@example.test", baumKontakt: { freigabeId: "first", version: 3, partner: ["a"] } },
        { id: "remove", uid: "other-uid", vorname: "Same", nachname: "Person", firma: "Source",
          geburtstag: "1980-05-06", notiz: "Imported note",
          telefon: "016095347", importHerkunfte: ["Telefon"],
          email: "same@example.test", baumKontakt: { freigabeId: "second", version: 7, partner: ["b"] } }],
      aufgaben: [{ id: "task", titel: "Keep link", kontaktId: "remove" }],
      jahrestage: [
        { id: "birthday-keep", typ: "birthday", name: "Same Person", datum: "1980-05-06", kontaktId: "keep" },
        { id: "birthday-remove", typ: "birthday", name: "Same Person", datum: "1980-05-06", kontaktId: "remove" },
        { id: "anniversary", typ: "anniversary", name: "Individual anniversary", datum: "2005-06-07",
          kontaktId: "remove", notiz: "Keep this separate event" }
      ]
    } });
    const before = JSON.stringify(T.daten().kontakte);
    T.oeffneEinstellungen(); w.document.querySelector("#einst-tab-adressen").click();
    [...w.document.querySelectorAll("button")].find(b => b.textContent === "Merge duplicate contact cards").click();
    for (let n = 0; n < 400 && !w.document.querySelector("[data-import-entscheidung]"); n++) await tick();
    const choice = w.document.querySelector("[data-import-entscheidung]"); assert.ok(choice, "duplicate menu did not open explicit review");
    const phoneDifference = w.document.querySelector('[data-kontakt-unterschied="Phone numbers"]');
    assert.ok(phoneDifference, "individual decision lacks a concrete phone-number comparison");
    for (const value of ["Gmail", "01597777", "Telefon", "016095347"])
      assert.ok(phoneDifference.textContent.includes(value), "comparison omitted source/value: " + value);
    assert.equal(choice.closest("details").open, true, "unresolved differences are hidden by default");
    assert.equal(w.document.querySelector('[data-kontakt-unterschied="Birthday"]'), null, "equal birthday marked as different");
    if (mode === "cancel") [...w.document.querySelectorAll(".kontakt-datei-pruefung button")].find(b => b.textContent === "Cancel").click();
    else { choice.value = "merge"; choice.dispatchEvent(new w.Event("change")); w.document.querySelector("[data-import-anwenden]").click(); }
    for (let n = 0; n < 400 && mode === "merge" && T.daten().kontakte.length === 2; n++) await tick();
    await tick(); await tick();
    if (mode !== "merge") {
      assert.equal(T.daten().kontakte.length, 2);
      assert.equal(T.daten().aufgaben[0].kontaktId, "remove");
      if (mode !== "stale") assert.equal(JSON.stringify(T.daten().kontakte), before);
    } else {
      const contact = T.daten().kontakte[0]; assert.equal(T.daten().kontakte.length, 1);
      assert.equal(contact.id, "keep"); assert.equal(contact.firma, "Source"); assert.equal(contact.fotoManuell, true);
      assert.equal(contact.baumKontakt.freigabeId, "first");
      assert.equal(contact.baumKontakt.weitere.length, 1); assert.equal(contact.baumKontakt.weitere[0].freigabeId, "second");
      assert.equal(T.daten().aufgaben[0].kontaktId, "keep");
      assert.ok(contact.notiz.includes("Local note") && contact.notiz.includes("Imported note"), "merging discarded a note");
      assert.equal(T.jahrestageAm("2026-05-06", true).length, 1, "merging created duplicate birthday reminders");
      const anniversary = T.daten().jahrestage.find(j => j.id === "anniversary");
      assert.equal(anniversary.kontaktId, "keep");
      assert.equal(anniversary.notiz, "Keep this separate event");
      assert.equal(T.daten().papierkorb.length, 1); assert.equal(T.daten().geloescht.kontakte.length, 0);
      assert.ok(contact.kontaktAliase.ids.includes("remove"));
      assert.equal(T.ausDemPapierkorb(T.daten().papierkorb[0]), true);
      assert.equal(T.daten().kontakte[1].sync, false); assert.ok(!T.daten().kontakte[1].baumKontakt);
    }
  } finally { w.close(); }
}
(async () => { for (const web of require("./web-test-roots"))
    for (const mode of ["merge", "cancel", "snapshot-error", "stale"]) await check(web, mode);
  console.log("CONTACT DUPLICATE REVIEW PASSED: menu, source bindings, aliases, reference repair and guards");
})().catch(error => { console.error(error); process.exitCode = 1; });
