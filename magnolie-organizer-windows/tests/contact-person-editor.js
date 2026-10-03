"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const tick = () => new Promise(resolve => setTimeout(resolve, 5));
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
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "kontaktFormular, starteExport, starteSync, druckKarteHtml, speichereJetzt: speichereJetzt,"));
    w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    w.App.init({ neu: false, regional: { language: "en" }, daten: { kontakte: [
      { id: "parent", vorname: "Parent", nachname: "Example", kontaktpersonen: [{ name: "Original", telefon: "0123", status: "Son" }] },
      { id: "child", vorname: "Alex", nachname: "Example", telefon: "0456", firma: "Current company",
        anschriften: [{ typen: ["WORK"], strasse: "Work 5", ort: "Hamburg" }], email: "child@example.test" }
    ] } });
    const T = w.OrganizerTest, parent = T.daten().kontakte.find(k => k.id === "parent");
    const original = JSON.stringify(T.daten().kontakte);
    let form = T.kontaktFormular(parent); w.document.body.append(form);
    let row = form.querySelector(".kontaktperson-zeile"), details = row.querySelector(".kontaktperson-erweitert");
    assert.equal(details.open, false); assert.equal(details.querySelectorAll("input").length, 0, "collapsed details eagerly mutate the draft");
    function set(root, selector, value, event = "input") {
      const f = root.querySelector(selector); assert.ok(f, selector); f.value = value; f.dispatchEvent(new w.Event(event, { bubbles: true })); return f;
    }
    if (mode === "linked" || mode === "unlink") {
      const select = row.querySelector("[data-person-verknuepfung]");
      assert.ok(![...select.options].some(o => o.value === "parent"), "self-link offered");
      set(row, "[data-person-verknuepfung]", "child", "change");
      row = form.querySelector(".kontaktperson-zeile"); details = row.querySelector(".kontaktperson-erweitert");
      assert.equal(row.querySelector(".kontaktperson-name").disabled, true);
      assert.equal(row.querySelector(".kontaktperson-telefon").value, "0456");
      assert.equal(row.querySelector(".kontaktperson-status").value, "Son");
      details.open = true; details.dispatchEvent(new w.Event("toggle"));
      assert.equal(details.querySelector(".kontaktperson-details").disabled, true);
      assert.equal(details.querySelector('[data-person-feld="strasse"]').value, "Work 5");
      if (mode === "unlink") {
        set(row, "[data-person-verknuepfung]", "", "change");
        row = form.querySelector(".kontaktperson-zeile"); assert.equal(row.querySelector(".kontaktperson-name").disabled, false);
      }
    } else {
      details.open = true; details.dispatchEvent(new w.Event("toggle"));
      set(details, '[data-person-feld="vorname"]', "Elena"); set(details, '[data-person-feld="nachname"]', "Care");
      set(details, '[data-person-feld="firma"]', "Care company"); set(details, '[data-person-feld="notiz"]', "Extra notes");
      set(details, '[data-person-feld="geburtstag"]', "06.07.");
      for (const key of ["anschriften", "emailEintraege", "telefone"]) {
        const block = details.querySelector(`[data-person-liste="${key}"]`);
        [...block.querySelectorAll("button")].find(b => b.textContent === "Add").click();
      }
      const addresses = details.querySelector('[data-person-liste="anschriften"]');
      set(addresses, '[data-person-feld="art"]', "Work"); set(addresses, '[data-person-feld="strasse"]', "Care street 7");
      set(addresses, '[data-person-feld="plz"]', "12345"); set(addresses, '[data-person-feld="ort"]', "Example town");
      set(details.querySelector('[data-person-liste="emailEintraege"]'), '[data-person-feld="wert"]', "care@example.test");
      const phones = details.querySelectorAll('[data-person-liste="telefone"] [data-person-feld="wert"]');
      phones[1].value = "0789"; phones[1].dispatchEvent(new w.Event("input", { bubbles: true }));
    }
    assert.equal(JSON.stringify(T.daten().kontakte), original, "editing wrote through to stored contacts");
    if (mode === "cancel") [...form.querySelectorAll("button")].find(b => b.textContent === "Cancel").click();
    else [...form.querySelectorAll("button")].find(b => ["Save", "Save changes"].includes(b.textContent)).click();
    await tick(); await tick();
    if (mode === "cancel") { assert.equal(JSON.stringify(T.daten().kontakte), original); return; }
    const saved = T.daten().kontakte.find(k => k.id === "parent").kontaktpersonen;
    assert.equal(saved.length, 1);
    assert.equal(saved[0].status, "Son");
    if (mode === "linked") {
      assert.equal(saved[0].kontaktId, "child");
      const child = T.daten().kontakte.find(k => k.id === "child"); child.telefon = "0999"; child.telefone = [];
      child.anschriften[0].strasse = "New workplace 8";
      const card = T.kontaktKarte(T.daten().kontakte.find(k => k.id === "parent"));
      assert.ok(card.textContent.includes("0999") && card.textContent.includes("New workplace 8"));
      const print = T.druckKarteHtml(T.daten().kontakte.find(k => k.id === "parent"));
      assert.ok(print.includes("0999") && print.includes("New workplace 8"));
      await T.starteExport("vcf-adressen");
      const exported = messages.filter(m => m.cmd === "export").at(-1).daten.find(k => k.id === "parent").kontaktpersonen[0];
      assert.equal(exported.kontaktId, undefined); assert.equal(exported.telefon, "0999");
      assert.equal(exported.anschriften[0].strasse, "New workplace 8");
      assert.equal(saved[0].kontaktId, "child", "export detached the stored link");
      T.daten().einstellungen.sync.adressbuchUid = "owned-book";
      T.starteSync(false);
      for (let i = 0; i < 400 && !messages.some(m => m.cmd === "sync"); i++) await tick();
      const sync = messages.findLast(m => m.cmd === "sync"); assert.ok(sync, "native sync was not dispatched");
      const linked = sync.daten.kontakte.find(k => k.id === "parent").kontaktpersonen[0];
      assert.equal(linked.kontaktId, "child"); assert.equal(linked.telefon, "0999");
      assert.equal(linked.anschriften[0].strasse, "New workplace 8", "provider received an outdated linked address");
    } else if (mode === "unlink") {
      assert.equal(saved[0].kontaktId, undefined); assert.equal(saved[0].anschriften[0].strasse, "Work 5");
    } else {
      assert.equal(saved[0].name, "Elena Care"); assert.equal(saved[0].firma, "Care company");
      assert.equal(saved[0].notiz, "Extra notes"); assert.equal(saved[0].geburtstag, "--07-06");
      assert.equal(saved[0].anschriften[0].strasse, "Care street 7"); assert.equal(saved[0].anschriften[0].typen[0], "WORK");
      assert.ok(saved[0].telefone.some(p => p.wert === "0789"));
      assert.equal(saved[0].emailEintraege[0].wert, "care@example.test");
    }
    const persisted = JSON.parse(JSON.stringify(T.daten()));
    w.App.init({ neu: false, daten: persisted });
    const reloaded = T.daten().kontakte.find(k => k.id === "parent").kontaktpersonen;
    if (mode === "linked") {
      assert.equal(reloaded.length, 1); assert.equal(reloaded[0].kontaktId, "child");
      assert.equal(reloaded[0].telefon, "0999"); assert.equal(reloaded[0].anschriften[0].strasse, "New workplace 8");
    } else assert.deepEqual(JSON.parse(JSON.stringify(reloaded)), JSON.parse(JSON.stringify(saved)));
    const normalized = JSON.stringify(T.daten().kontakte);
    w.App.init({ neu: false, daten: JSON.parse(JSON.stringify(T.daten())) });
    assert.equal(JSON.stringify(T.daten().kontakte), normalized, "reloading regenerated linked copies or modification times");
  } finally { w.close(); }
}
(async () => {
  for (const web of require("./web-test-roots"))
    for (const mode of ["manual", "linked", "unlink", "cancel"]) await check(web, mode);
  console.log("CONTACT PERSON EDITOR PASSED: collapsed fields, rich manual contacts, live links, unlink and reload");
})().catch(error => { console.error(error); process.exitCode = 1; });
