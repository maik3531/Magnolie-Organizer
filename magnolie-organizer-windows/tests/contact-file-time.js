"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
async function until(test) {
  for (let i = 0; i < 2000; i++) { if (test()) return; await new Promise(r => setTimeout(r, 1)); }
  throw Error("Contact time review timeout");
}
async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, messages = [], older = Date.now() - 60000, newer = older + 30000;
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
    const T = w.OrganizerTest;
    for (const mode of ["newer", "older", "generic", "equal", "future", "unknown-local", "automatic", "name-only"]) {
      w.App.init({ neu: false, daten: { kontakte: [{ id: "local", uid: "same", vorname: "Person", nachname: "Local" }],
        einstellungen: { sync: { kontaktNeuereBevorzugen: mode === "automatic" } } } });
      let local = T.daten().kontakte[0];
      if (mode !== "unknown-local") await T.merkeKontaktInhaltszeit(local, mode === "older" ? newer : older);
      const card = { uid: "same", vorname: "Person", nachname: "Remote", geaendert: Date.now(),
        vcardRev: mode === "older" || mode === "equal" ? older : mode === "future" ? Date.now() + 600000 : newer };
      if (mode === "generic") delete card.vcardRev;
      if (mode === "name-only") { delete card.uid; card.nachname = "Local"; card.notiz = "Different"; }
      const run = w.App.importErgebnis({ kontakte: [card] });
      await until(() => w.document.querySelector('.kontakt-datei-pruefung [aria-busy="false"]'));
      const choice = w.document.querySelector("[data-import-entscheidung]");
      const allowed = ["newer", "older", "automatic"].includes(mode);
      assert.equal(choice.querySelector('option[value="newer"]').disabled, !allowed, mode);
      if (allowed) {
        if (mode === "automatic") assert.equal(choice.value, "newer");
        else { choice.value = "newer"; choice.dispatchEvent(new w.Event("change")); }
        w.document.querySelector("[data-import-anwenden]").click(); await run;
        local = T.daten().kontakte[0];
        assert.equal(local.nachname, mode === "older" ? "Local" : "Remote");
        assert.equal(await T.kontaktInhaltszeit(local), newer);
        assert.equal(local.vcardRev, undefined, "unbound source timestamp persisted as a local proof");
      } else {
        [...w.document.querySelectorAll(".kontakt-datei-pruefung button")].find(b => b.textContent === "Cancel").click(); await run;
        assert.equal(local.nachname, "Local");
      }
    }
    w.App.init({ neu: false, daten: { kontakte: [{ id: "export", vorname: "Export", geaendert: Date.now() }] } });
    T.oeffneEinstellungen(); w.document.querySelector("#einst-tab-export").click();
    const exportButton = [...w.document.querySelectorAll("button")].find(b => b.textContent === "Contacts (.vcf)");
    assert.ok(exportButton); exportButton.click();
    await until(() => messages.some(m => m.cmd === "export"));
    assert.equal(messages.findLast(m => m.cmd === "export").daten[0].geaendert, 0, "export fabricated REV from storage time");
    await T.merkeKontaktInhaltszeit(T.daten().kontakte[0], older); messages.length = 0; exportButton.click();
    await until(() => messages.some(m => m.cmd === "export"));
    assert.equal(messages.findLast(m => m.cmd === "export").daten[0].geaendert, older);
    console.log("CONTACT FILE TIME PASSED:", web);
  } finally { w.close(); }
}
(async () => {
  for (const web of [path.resolve(__dirname, "../app/web"), path.resolve(__dirname, "../../magnolie-organizer/web")]) await check(web);
})().catch(error => { console.error(error); process.exitCode = 1; });
