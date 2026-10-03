"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const tick = () => new Promise(resolve => setTimeout(resolve, 5));
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
    w.App.init({ neu: false, regional: { language: "en" }, daten: { kontakte: [{ id: "local", uid: "stable",
      vorname: "Anna", nachname: "Old", importHerkunfte: ["Gmail"], telefon: "01597777", email: "old@example.test",
      anschriften: [{ typen: ["HOME"], strasse: "Private 1", ort: "Berlin" }, { typen: ["WORK"], strasse: "Old work 2", ort: "Berlin" }] }] } });
    const T = w.OrganizerTest, before = JSON.stringify(T.daten().kontakte);
    const run = w.App.importErgebnis({ kontakte: [{ uid: "stable", vorname: "Anna", nachname: "New", importHerkunfte: ["Telefon"],
      telefon: "016095347", email: "new@example.test", anschriften: [{ typen: ["WORK"], strasse: "New work 3", ort: "Hamburg" }] }] });
    function choose(selector, value) {
      const field = w.document.querySelector(selector); assert.ok(field, selector); assert.equal(field.disabled, false, selector + " disabled");
      field.value = value; field.dispatchEvent(new w.Event("change"));
    }
    choose("[data-import-entscheidung]", "merge");
    w.document.querySelector("[data-import-anwenden]").click(); await tick();
    assert.equal(JSON.stringify(T.daten().kontakte), before, "move was silently appended without an address decision");
    assert.ok(w.document.querySelector(".kontakt-datei-pruefung"));
    choose('[data-import-feld="nachname"]', "incoming");
    const birthName = w.document.querySelector("[data-import-geburtsname]");
    assert.ok(birthName); assert.equal(birthName.disabled, false); assert.equal(birthName.checked, false);
    assert.ok(birthName.parentElement.textContent.includes("Birth name: Old"));
    if (["birth-name", "cancel"].includes(mode)) { birthName.checked = true; birthName.dispatchEvent(new w.Event("change")); }
    choose('[data-import-liste="telefone"]', mode === "replace-phone" ? "replace:0" : "add");
    choose('[data-import-liste="emailEintraege"]', mode === "keep-email" ? "keep" : "add");
    const address = w.document.querySelector('[data-import-liste="anschriften"]');
    assert.ok([...address.options].some(o => o.textContent.includes("Home address") && o.textContent.includes("Private 1")));
    assert.ok([...address.options].some(o => o.textContent.includes("Work address") && o.textContent.includes("Old work 2")));
    choose('[data-import-liste="anschriften"]', "replace:1");
    if (mode === "cancel") [...w.document.querySelectorAll(".kontakt-datei-pruefung button")].find(b => b.textContent === "Cancel").click();
    else w.document.querySelector("[data-import-anwenden]").click();
    await run;
    if (mode === "cancel") assert.equal(JSON.stringify(T.daten().kontakte), before);
    else {
      const k = T.daten().kontakte[0];
      assert.equal(k.nachname, "New");
      assert.equal(k.notiz.includes("Birth name: Old"), mode === "birth-name", "birth name was not explicitly opted in");
      assert.deepEqual(Array.from(k.anschriften, a => a.strasse), ["Private 1", "New work 3"]);
      assert.equal(k.anschriften[0].typen[0], "HOME"); assert.equal(k.anschriften[1].typen[0], "WORK");
      assert.ok(k.telefone.some(p => p.wert === "016095347"));
      assert.equal(k.telefone.some(p => p.wert === "01597777"), mode !== "replace-phone");
      assert.ok(k.emails.includes("old@example.test"));
      assert.equal(k.emails.includes("new@example.test"), mode !== "keep-email");
    }
  } finally { w.close(); }
}
(async () => {
  for (const web of require("./web-test-roots"))
    for (const mode of ["add", "replace-phone", "keep-email", "birth-name", "cancel"]) await check(web, mode);
  console.log("CONTACT FIELD REVIEW PASSED: explicit names, additive values, replacement address and cancellation");
})().catch(error => { console.error(error); process.exitCode = 1; });
