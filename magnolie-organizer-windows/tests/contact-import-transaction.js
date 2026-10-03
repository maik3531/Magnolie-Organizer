"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const tick = () => new Promise(resolve => setTimeout(resolve, 5));
async function until(test) {
  for (let n = 0; n < 600; n++) { if (test()) return; await tick(); }
  throw new Error("Import transaction timeout");
}
async function check(web, mode) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, messages = [];
  let holdSave = false;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const m = JSON.parse(text); messages.push(m);
    if (m.cmd === "speichern" && !holdSave) queueMicrotask(() => w.App.gespeichert({ id: m.id, ok: true }));
  } } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    const T = w.OrganizerTest;
    w.App.init({ neu: false, daten: { kontakte: [{ id: "existing", vorname: "Existing" }] } });
    const sources = [{ kontoName: "Test", kontoTyp: "local", dataSet: "contacts", anzahl: 1 }];
    const incoming = [
      { id: "manifest", von: "android", inhalt: { art: "kontakt_import_manifest", fassung: 1, importId: "run", anzahl: 1, herkuenfte: sources } },
      { id: "card", von: "android", inhalt: { art: "kontakt_import_karte", fassung: 1, importId: "run",
        bindung: "urn:magnolie:import:android:" + "a".repeat(64), herkuenfte: sources, kontakt: { vorname: "Incoming" } } }
    ];
    const inbox = value => w.App.baumStand({ partner: [], eingang: value });
    const acknowledged = () => messages.some(m => m.cmd === "baum_eingang_geleert" && m.ids.includes("manifest"));
    inbox(incoming);
    const button = w.document.querySelector(mode === "reject" ? ".kontakt-import-dialog .dialog-knoepfe button:last-child" : ".kontakt-import-dialog .hauptknopf");
    assert.ok(button);
    if (mode === "changed-before-confirm") T.daten().kontakte[0].notiz = "Local edit";
    button.click();
    if (mode === "changed-before-confirm") {
      assert.equal(messages.filter(m => m.cmd === "mutations_snapshot").length, 0);
    } else {
      if (mode !== "reject") {
        const review = w.document.querySelector("[data-import-anwenden]");
        assert.ok(review, "manifest import must use the shared contact review"); review.click();
      }
      await until(() => messages.some(m => m.cmd === "mutations_snapshot"));
      const snapshot = messages.find(m => m.cmd === "mutations_snapshot");
      if (mode === "changed-during-snapshot") T.daten().kontakte[0].notiz = "Local edit";
      if (mode === "profile-change") w.App.init({ neu: false, daten: { kontakte: [{ id: "other", vorname: "Other profile" }] } });
      if (mode === "replaced-inbox") {
        const changed = JSON.parse(JSON.stringify(incoming)); changed[1].inhalt.kontakt.vorname = "Replacement"; inbox(changed);
      }
      if (mode === "removed-inbox") inbox([]);
      holdSave = ["success", "reject", "removed-before-save-ack"].includes(mode);
      w.App.mutationsSnapshot({ token: snapshot.token, ok: true });
      if (holdSave) {
        await until(() => messages.some(m => m.cmd === "speichern" && (mode === "reject" ?
          JSON.parse(m.text).kontaktImportAblehnungen?.length === 1 : JSON.parse(m.text).kontakte?.length === 2)));
        assert.equal(acknowledged(), false, "import acknowledged before durable save");
        if (mode === "removed-before-save-ack") inbox([]);
        const saved = messages.findLast(m => m.cmd === "speichern");
        w.App.gespeichert({ id: saved.id, ok: true });
      }
    }
    await tick(); await tick();
    if (mode === "success" || mode === "reject") {
      assert.equal(T.daten().kontakte.length, mode === "reject" ? 1 : 2); assert.ok(acknowledged());
      if (mode === "reject") assert.equal(T.daten().kontaktImportAblehnungen.length, 1);
    } else {
      assert.equal(T.daten().kontakte.length, mode === "removed-before-save-ack" ? 2 : 1, mode);
      assert.equal(acknowledged(), false, mode + " acknowledged a stale import");
    }
  } finally { w.close(); }
}
(async () => {
  for (const web of require("./web-test-roots")) {
    for (const mode of ["success", "reject", "changed-before-confirm", "changed-during-snapshot", "profile-change", "replaced-inbox", "removed-inbox", "removed-before-save-ack"]) await check(web, mode);
    console.log("CONTACT IMPORT TRANSACTION PASSED:", web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
