"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
async function check(web) {
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
    const local = [{ id: "weak", uid: "weak", vorname: "Only", nachname: "Name" },
      ...Array.from({ length: 500 }, (_, i) => ({ id: "local-" + i, uid: "uid-" + i, vorname: "Local", nachname: "Person " + i }))];
    w.App.init({ neu: false, daten: { kontakte: local } });
    const T = w.OrganizerTest, before = JSON.stringify(T.daten().kontakte);
    const run = w.App.importErgebnis({ kontaktQuelle: "datei:" + "a".repeat(64), kontakte: [
      { vorname: "Only", nachname: "Name", notiz: "Name is not proof of identity" },
      ...Array.from({ length: 500 }, (_, i) => ({ uid: "uid-" + i, vorname: "Remote", nachname: "Person " + i }))
    ] });
    const rest = w.document.querySelector("[data-import-rest]");
    for (let n = 0; n < 2000 && rest.disabled; n++) await new Promise(r => setTimeout(r, 1));
    assert.equal(rest.disabled, false);
    assert.equal(w.document.querySelectorAll("[data-import-entscheidung]").length, 25, "preview must stay paginated");
    const choose = (index, value) => {
      const field = w.document.querySelector('[data-import-entscheidung="' + index + '"]');
      field.value = value; field.dispatchEvent(new w.Event("change"));
    };
    choose(2, "keep"); rest.checked = true; choose(1, "replace");
    assert.equal(w.document.querySelector('[data-import-entscheidung="0"]').value, "", "batch rule crossed a name-only match");
    assert.equal(w.document.querySelector('[data-import-entscheidung="2"]').value, "keep", "batch rule discarded an explicit decision");
    w.document.querySelector("[data-import-anwenden]").click();
    assert.equal(JSON.stringify(T.daten().kontakte), before, "unresolved batch mutated existing contacts");
    choose(0, "skip"); w.document.querySelector("[data-import-anwenden]").click(); await run;
    assert.equal(T.daten().kontakte.length, 501);
    assert.equal(T.daten().kontakte.filter(k => k.vorname === "Remote").length, 499);
    assert.equal(T.daten().kontakte.find(k => k.id === "local-1").vorname, "Local");
    assert.equal(T.daten().kontakte.find(k => k.id === "local-499").vorname, "Remote", "off-screen conflicts were not included");
    assert.equal(T.daten().kontakte[0].notiz, "");
    assert.equal(messages.filter(m => m.cmd === "mutations_snapshot").length, 1);
    w.App.init({ neu: false, daten: {} });
    const first = { uid: "fragment", vorname: "Fragment", nachname: "Person", geburtstag: "--02-29",
      telefone: [{ wert: "+49305550111", typen: ["HOME"] }] };
    const fragments = w.App.importErgebnis({ kontakte: [first, JSON.parse(JSON.stringify(first)),
      { ...first, telefone: [{ wert: "+49305550222", typen: ["WORK"] }] }] });
    assert.equal(w.document.querySelector('[data-import-entscheidung="1"]').value, "keep", "identical cards in one file were not recognized");
    assert.equal(w.document.querySelector('[data-import-entscheidung="2"]').value, "", "different fragments must be reviewed");
    choose(2, "merge"); w.document.querySelector("[data-import-anwenden]").click(); await fragments;
    assert.equal(T.daten().kontakte.length, 1, "fragmented source cards created duplicate people");
    assert.equal(T.daten().kontakte[0].telefone.length, 2);
    assert.equal(T.daten().jahrestage.length, 1);
    assert.equal(T.daten().jahrestage[0].kontaktId, T.daten().kontakte[0].id, "virtual preview identity leaked into the saved graph");
    console.log("CONTACT FILE BATCH PASSED: 500 conflicts, explicit choice and name-only guard:", web);
  } finally { w.close(); }
}
(async () => {
  for (const web of require("./web-test-roots")) await check(web);
})().catch(error => { console.error(error); process.exitCode = 1; });
