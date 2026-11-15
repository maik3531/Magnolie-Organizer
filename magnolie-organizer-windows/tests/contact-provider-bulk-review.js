"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const web = path.resolve(__dirname, "../app/web");
const tick = () => new Promise(resolve => setTimeout(resolve, 5));
async function until(test) { for (let i = 0; i < 600; i++) { if (test()) return; await tick(); } throw new Error("Provider bulk review timeout"); }
async function check(mode) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, messages = [], source = "thunderbird-addressbook:fixture:book";
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const m = JSON.parse(text); messages.push(m);
    if (m.cmd === "speichern") queueMicrotask(() => w.App.gespeichert({ id: m.id, ok: true }));
    if (m.cmd === "mutations_snapshot") queueMicrotask(() => {
      if (mode === "stale") w.OrganizerTest.daten().kontakte[1].notiz = "Concurrent change";
      w.App.mutationsSnapshot({ token: m.token, ok: mode !== "snapshot-error" });
    });
  } } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    const cards = [0, 1].map(i => ({ id: "local-" + i, uid: "uid-" + i, vorname: "Person " + i, notiz: "Local " + i, sync: true,
      syncQuellen: { [source]: { id: "remote-" + i, etag: '"old"' } },
      syncKonflikte: { [source]: { kontakt: { vorname: "Person " + i, notiz: "Remote " + i },
        mapping: { id: "remote-" + i, etag: '"new"', inhaltFormat: "windows-contact-2", inhaltSha256: "a".repeat(64) } } } }));
    w.App.init({ neu: false, daten: { kontakte: cards } }); await tick();
    const T = w.OrganizerTest, before = JSON.stringify(T.daten().kontakte);
    T.oeffneSyncKontaktKonflikt("local-0", source);
    const rest = w.document.querySelector("[data-sync-kontakt-rest]");
    assert.ok(rest, "Provider conflict dialog has no apply-to-all choice");
    rest.checked = mode !== "single";
    assert.ok(w.document.querySelector(".sync-kontakt-konflikt .kontakt-quellenvergleich"));
    if (mode === "merge") {
      const note = w.document.querySelector('[data-kontakt-feld="notiz"]');
      note.value = "incoming"; note.dispatchEvent(new w.Event("change"));
    }
    w.document.querySelector('[data-sync-kontakt-entscheidung="' + (mode === "keep" ? "keep" : mode === "merge" ? "merge" : "replace") + '"]').click();
    await until(() => messages.some(m => m.cmd === "mutations_snapshot")); await tick(); await tick();
    const saved = T.daten().kontakte;
    if (mode === "snapshot-error") assert.equal(JSON.stringify(saved), before);
    else if (mode === "stale") {
      assert.equal(saved[0].notiz, "Local 0"); assert.equal(saved[1].notiz, "Concurrent change");
      assert.ok(saved.every(k => k.syncKonflikte?.[source]));
    } else {
      assert.equal(saved[0].notiz, mode === "keep" ? "Local 0" : "Remote 0");
      assert.equal(saved[1].notiz, mode === "keep" || mode === "single" ? "Local 1" : "Remote 1");
      assert.equal(!!saved[0].syncKonflikte?.[source], false);
      assert.equal(!!saved[1].syncKonflikte?.[source], mode === "single");
      assert.equal(saved[1].syncQuellen[source].etag, mode === "single" ? '"old"' : '"new"');
    }
  } finally { w.close(); }
}
(async () => {
  const results = [];
  for (const mode of (process.argv[2] ? process.argv[2].split(",") : ["replace", "keep", "merge", "single", "stale", "snapshot-error"])) {
    try { await check(mode); results.push({ mode, passed: true }); }
    catch (error) { results.push({ mode, passed: false, error: error.message }); }
  }
  console.log(JSON.stringify(results, null, 2)); assert.ok(results.every(r => r.passed));
})().catch(error => { console.error(error); process.exitCode = 1; });
