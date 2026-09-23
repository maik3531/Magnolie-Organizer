"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto");
const { JSDOM } = require("jsdom");

function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/index.html", pretendToBeVisual: true
  });
  const w = dom.window;
  Object.defineProperty(w, "crypto", { value: webcrypto });
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage() {} } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  w.MagnolieI18n.setLocale("en");
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
  w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  const T = w.OrganizerTest;
  const birthday = (id, extra = {}) => ({ id, uid: "remote-" + id, name: "Mia Muster",
    datum: "1990-12-25", typ: "birthday", icsQuelleId: "provider-" + id,
    icsQuelleName: "Calendar " + id, icsSerienUid: "series-" + id,
    icsRoundtrip: ["UID:remote-" + id], syncQuellen: { ["provider-" + id]: { href: id + ".ics" } }, ...extra });
  const load = (jahrestage, kontakte = []) => w.App.init({ daten: { jahrestage, kontakte }, neu: false, regional: { language: "en" } });
  function shown(expected, date = "2026-12-25") {
    const saved = JSON.stringify(T.daten());
    assert.equal(T.jahrestageAm(date, true).length, expected, "calendar birthday count");
    assert.equal(T.druckStoff("jahrestage").liste.length, expected, "print selection birthday count");
    T.wechsel("jahrestage");
    assert.equal(w.document.querySelectorAll(".jahrestage-liste .zeile").length, expected, "anniversary list birthday count");
    assert.equal(JSON.stringify(T.daten()), saved, "display grouping must preserve source records and synchronization mappings");
  }
  try {
    load([birthday("import"), birthday("google"), birthday("microsoft")]);
    assert.equal(T.daten().jahrestage.length, 3);
    shown(1);
    load([birthday("import"), birthday("google"), birthday("microsoft")], [
      { id: "person", vorname: "Mia", nachname: "Muster", geburtstag: "1990-12-25" }
    ]);
    assert.equal(T.daten().jahrestage.length, 3, "late contact linking must retain provider records");
    shown(1);
    load([birthday("a"), birthday("b", { datum: "1991-12-25" })]); shown(2);
    load([birthday("a"), birthday("b", { notiz: "Different birthday information" })]); shown(2);
    load([birthday("a"), birthday("b", { typ: "wedding" })]); shown(2);
    load([birthday("a"), birthday("b", { name: "Mía Muster" })]); shown(2);
    load([birthday("a", { extraInformation: "first" }), birthday("b", { extraInformation: "second" })]); shown(2);
    load([birthday("a", { datum: "--12-25" }), birthday("b", { datum: "--12-25" })]); shown(1);
    load([birthday("a", { datum: "--12-25" }), birthday("b")]); shown(2);
    load([birthday("a", { datum: "--02-29" }), birthday("b", { datum: "--02-29" })]); shown(1, "2027-02-28");
    load([birthday("a", { uid: "shared" }), birthday("b", { uid: "shared", datum: "1991-12-25" })]);
    assert.equal(T.daten().jahrestage.length, 2, "normalization discarded a conflicting year"); shown(2);
    load([birthday("a", { kontaktId: "person" }), birthday("b", { kontaktId: "person", notiz: "Conflicting note" })]);
    assert.equal(T.daten().jahrestage.length, 2, "normalization discarded conflicting birthday information"); shown(2);
    const contacts = [
      { id: "a", vorname: "Mia", nachname: "Muster", geburtstag: "1990-12-25", email: "first@example.test" },
      { id: "b", vorname: "Mia", nachname: "Muster", geburtstag: "1990-12-25", email: "second@example.test" }
    ];
    load([birthday("a", { kontaktId: "a" }), birthday("b", { kontaktId: "b" })], contacts); shown(2);
    load([birthday("a", { kontaktId: "a" }), birthday("b", { kontaktId: "b" }), birthday("unknown")], contacts); shown(3);
    contacts[1].email = contacts[0].email;
    load([birthday("a", { kontaktId: "a" }), birthday("b", { kontaktId: "b" }), birthday("import")], contacts);
    assert.equal(T.daten().kontakte[0].email, "first@example.test");
    assert.equal(T.daten().kontakte[0].email, T.daten().kontakte[1].email);
    shown(1);
    console.log("BIRTHDAY DISPLAY PASSED: " + web);
  } finally { w.close(); }
}
for (const web of [path.resolve(__dirname, "../app/web"), path.resolve(__dirname, "../../magnolie-organizer/web")]) {
  if (fs.existsSync(web)) check(web);
}
