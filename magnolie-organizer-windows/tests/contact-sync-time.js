"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const web = path.resolve(__dirname, "../app/web"), tick = () => new Promise(r => setTimeout(r, 5));
async function check(mode) {
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
    const T = w.OrganizerTest, source = "generic-dav-addressbook:fixture";
    const incoming = { vorname: "Remote", geaendert: Date.now(),
      vcardRev: mode === "older" || mode === "equal" ? older : mode === "future" ? Date.now() + 600000 : newer };
    if (mode === "missing") delete incoming.vcardRev;
    if (mode === "pinned") incoming.foto = "data:image/png;base64,BAUG";
    w.App.init({ neu: false, daten: { kontakte: [{ id: "local", uid: "stable", vorname: "Local",
      ...(mode === "pinned" ? { foto: "data:image/png;base64,AQID", fotoManuell: true } : {}),
      syncQuellen: { [source]: { id: "remote", etag: "v1" } },
      syncKonflikte: { [source]: { kontakt: incoming, mapping: { id: "remote", etag: "v2" } } } }] } });
    const local = T.daten().kontakte[0];
    await T.merkeKontaktInhaltszeit(local, mode === "older" ? newer : older);
    T.oeffneSyncKontaktKonflikt("local", source);
    const button = w.document.querySelector('[data-sync-kontakt-entscheidung="newer"]'); assert.ok(button);
    const allowed = !["missing", "equal", "future"].includes(mode);
    for (let n = 0; n < 400 && allowed && button.disabled; n++) await tick();
    assert.equal(button.disabled, !allowed, mode);
    if (allowed) button.click();
    if (!allowed || mode === "cancel-after-click")
      [...w.document.querySelectorAll(".sync-kontakt-konflikt button")].find(b => b.textContent === "Cancel").click();
    if (mode === "profile") w.App.init({ neu: false, daten: { kontakte: [{ id: "other", vorname: "Other profile" }] } });
    if (mode === "lock") T.zeigeSperrbildschirm(false);
    const aborted = ["cancel-after-click", "profile", "lock"].includes(mode);
    for (let n = 0; n < 400 && allowed && !aborted && local.syncKonflikte; n++) await tick();
    await tick();
    if (!allowed || aborted) {
      assert.equal(local.vorname, "Local"); assert.ok(local.syncKonflikte);
      assert.equal(messages.filter(m => m.cmd === "mutations_snapshot").length, 0);
      assert.equal(w.document.querySelector(".sync-kontakt-konflikt"), null, "private provider review remained visible after cancellation/lock/profile switch");
    } else {
      assert.equal(local.vorname, mode === "older" ? "Local" : "Remote");
      assert.equal(local.syncKonflikte, undefined); assert.equal(local.syncQuellen[source].etag, "v2");
      assert.equal(await T.kontaktInhaltszeit(local), newer);
      assert.equal(local.id, "local"); assert.equal(local.uid, "stable");
      if (mode === "pinned") assert.equal(local.foto, "data:image/png;base64,AQID");
    }
  } finally { w.close(); }
}
(async () => {
  for (const mode of ["newer", "older", "missing", "equal", "future", "pinned", "cancel-after-click", "profile", "lock"]) await check(mode);
  console.log("CONTACT SYNC TIME PASSED: original-time choice, unknown dates, photo pin and cancellation");
})().catch(error => { console.error(error); process.exitCode = 1; });
