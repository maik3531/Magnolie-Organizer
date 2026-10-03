"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
async function check(web, mode) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, messages = [];
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const m = JSON.parse(text); messages.push(m);
    if (m.cmd === "speichern") queueMicrotask(() => w.App.gespeichert({ id: m.id, ok: true }));
    if (m.cmd === "mutations_snapshot") queueMicrotask(() => w.App.mutationsSnapshot({ token: m.token, ok: true }));
  } } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    const main = { id: "main", vorname: "Parent", nachname: "Example", anschriften: [
      { typen: ["HOME"], strasse: "Home 1", ort: "Berlin", land: "Deutschland" },
      { typen: ["WORK"], strasse: "Work 2", ort: "Bern", land: "Schweiz" }],
      kontaktpersonen: [{ kontaktId: "child", status: "Son" }, { name: "Manual person", status: "Care",
        anschriften: [{ typen: ["HOME"], strasse: "Care 3", ort: "Dresden" }], email: "care@example.test", notiz: "Preserve details" }] };
    const child = { id: "child", vorname: "Alex", nachname: "Example", telefon: "012345", anschriften: [
      { typen: ["HOME"], strasse: "Child home 4", ort: "Berlin" }, { typen: ["WORK"], strasse: "Child work 5", ort: "Hamburg" }],
      kontaktpersonen: [{ kontaktId: "main", status: "Parent" }] };
    if (mode === "single") { main.anschriften = main.anschriften.slice(0, 1); main.kontaktpersonen = []; }
    if (mode === "only-person") main.anschriften = [];
    if (mode === "alias") { child.kontaktAliase = { ids: ["previous-child"] }; main.kontaktpersonen[0].kontaktId = "previous-child"; }
    w.App.init({ neu: false, regional: { language: "en" }, daten: { kontakte: [main, child], einstellungen: { adressen: {
      karte: true, route: mode === "route", karten: "openstreetmap", absender: "Origin\nStart 7\n10115 Berlin", land: "Deutschland" } } } });
    const T = w.OrganizerTest, data = T.daten(), parent = data.kontakte.find(k => k.id === "main");
    if (mode === "foreign-link") {
      const imported = w.App.importErgebnis({ kontakte: [{ uid: "foreign", vorname: "Foreign", kontaktpersonen: [
        { kontaktId: "child", name: "Supplied name", status: "Contact" }] }] });
      w.document.querySelector("[data-import-anwenden]").click(); await imported;
      const foreign = data.kontakte.find(k => k.uid === "foreign");
      assert.equal(foreign.kontaktpersonen[0].kontaktId, undefined, "external data bound an existing private contact");
      assert.equal(foreign.kontaktpersonen[0].name, "Supplied name"); return;
    }
    if (mode === "alias") assert.equal(parent.kontaktpersonen[0].kontaktId, "child");
    assert.equal(parent.kontaktpersonen.length, mode === "single" ? 0 : 2, "legacy fields created a duplicate emergency contact");
    const before = JSON.stringify(data.kontakte);
    const card = T.kontaktKarte(parent); w.document.body.append(card);
    const map = [...card.querySelectorAll("button")].find(b => b.textContent === (mode === "route" ? "Route" : "Map"));
    assert.ok(map, "map action absent despite available contact-person addresses"); map.click();
    const sent = () => messages.filter(m => m.cmd === "karte");
    if (mode === "single") { assert.equal(sent().length, 1); assert.equal(sent()[0].kontakt.strasse, "Home 1"); return; }
    assert.equal(sent().length, 0, "first address was selected implicitly");
    const dialog = w.document.querySelector(".kontakt-karten-auswahl"); assert.ok(dialog);
    assert.equal(dialog.querySelectorAll("[data-karten-ziel]").length, mode === "only-person" ? 3 : 5);
    assert.ok(dialog.textContent.includes("Alex") && dialog.textContent.includes("Son") && dialog.textContent.includes("Manual person"));
    const button = dialog.querySelector('[data-karten-ziel="person:0:1"]');
    if (mode === "cancel") [...dialog.querySelectorAll("button")].find(b => b.textContent === "Cancel").click();
    else if (mode === "profile") { w.App.init({ neu: false, daten: { kontakte: [] } }); button.click(); }
    else if (mode === "lock") { T.zeigeSperrbildschirm(false); button.click(); }
    else if (mode === "stale") {
      data.kontakte.find(k => k.id === "child").anschriften[1].strasse = "Moved meanwhile"; button.click();
    } else if (mode === "own-work") dialog.querySelector('[data-karten-ziel="kontakt:1"]').click();
    else button.click();
    if (["cancel", "profile", "lock", "stale"].includes(mode)) assert.equal(sent().length, 0, web + " " + mode);
    else {
      assert.equal(sent().length, 1);
      assert.equal(sent()[0].kontakt.strasse, mode === "own-work" ? "Work 2" : "Child work 5");
      assert.equal(sent()[0].kontakt.anschriften.length, 1);
      assert.equal(sent()[0].route, mode === "route");
      assert.equal(sent()[0].dienst, "openstreetmap");
      if (mode === "own-work") assert.equal(sent()[0].land, "Schweiz");
      assert.ok(!("kontaktpersonen" in sent()[0].kontakt));
    }
    if (!["profile", "stale"].includes(mode)) assert.equal(JSON.stringify(data.kontakte), before, "map selection mutated contact data");
    assert.equal(w.document.querySelector(".kontakt-karten-auswahl"), null);
  } finally { w.close(); }
}
(async () => {
  for (const web of require("./web-test-roots"))
    for (const mode of ["single", "own-work", "linked", "alias", "foreign-link", "route", "only-person", "cancel", "profile", "lock", "stale"]) await check(web, mode);
  console.log("CONTACT ADDRESS CHOICE PASSED: own and linked addresses, route, cancellation and stale guards");
})().catch(error => { console.error(error); process.exitCode = 1; });
