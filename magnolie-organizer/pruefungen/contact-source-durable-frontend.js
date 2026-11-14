"use strict";
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { createHash, webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const web = path.resolve(__dirname, "../web");
const sha = text => createHash("sha256").update(text).digest("hex");
const tick = () => new Promise(resolve => setImmediate(resolve));
async function boot() {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://durable-source.test.invalid/", pretendToBeVisual: true });
  const w = dom.window, messages = [];
  w.setTimeout = () => 1; w.clearTimeout = () => {}; w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {}; w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage: raw => messages.push(JSON.parse(raw)) } } };
  for (const name of ["i18n.js", "zeichenblatt.js", "appearance.js", "anwendung.js"]) w.eval(fs.readFileSync(path.join(web, name), "utf8"));
  await tick();
  w.App.init({ neu: false, regional: { language: "en", timeZone: "UTC" }, daten: {
    kontakte: [{ id: "local-person", uid: "canonical-person", sync: true, notiz: "Synthetic original" }],
    einstellungen: { sync: { automatisch: true, kontaktOriginalQuellen: ["not-a-grant"] } }, sourceAdmissions: ["not-a-grant"] } });
  const commands = cmd => messages.filter(value => value.cmd === cmd), t = w.OrganizerTest;
  function save(extra = {}) {
    t.speichereJetzt(); const saved = commands("speichern").at(-1); assert.ok(saved);
    w.App.gespeichert({ id: saved.id, ok: true, committed: true, repairPending: false,
      standSha256: sha(saved.text), kontaktQuellenDauerhaft: true, ...extra });
    return saved;
  }
  function notice(saved, extra = {}) {
    w.App.originalKontaktDauerfreigabe({ id: saved.id, standSha256: sha(saved.text), ok: true, freigaben: 1, ...extra });
  }
  return { w, t, commands, save, notice, close: () => w.close() };
}
async function run() {
  let count = 0;
  for (const mode of ["success", "unsolicited", "missing-marker", "wrong-id", "wrong-hash", "repair-pending", "uncommitted",
    "pending-save", "newer-edit", "native-revoked", "explicit-revoked", "reloaded", "account-wait-resume", "result-save-no-loop", "locked", "initial-setup-account-wait", "setup-stored-but-waiting"]) {
    const b = await boot();
    try {
      const extra = ["missing-marker", "initial-setup-account-wait", "setup-stored-but-waiting"].includes(mode) ? { kontaktQuellenDauerhaft: false } : mode === "repair-pending" ? { repairPending: true } :
        mode === "uncommitted" ? { committed: false } : {};
      let saved;
      if (mode === "unsolicited") saved = { id: 123, text: JSON.stringify(b.t.daten()) };
      else saved = b.save(extra);
      assert.equal(b.commands("kontakt_originalquellen_update").length, 0, "Marker/import fields became permission before native correlated notice");
      if (mode === "pending-save") { b.t.daten().kontakte[0].notiz = "Pending edit"; b.t.speichereJetzt(); }
      if (mode === "newer-edit") b.t.daten().kontakte[0].notiz = "Unsaved edit";
      if (mode === "native-revoked") b.w.App.originalKontaktFreigabe({ ok: true, freigaben: 0 });
      if (mode === "explicit-revoked") {
        b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-sync").click();
        b.w.App.edsStatus({ verfuegbar: true, buchOk: true, kalender: [], adressbuecher: [],
          originalKontaktUpdates: { verfuegbar: true, freigaben: 0 } });
        [...b.w.document.querySelectorAll("#sync-wahl button")].find(button => button.textContent === "Revoke").click();
        assert.equal(b.commands("kontakt_originalquellen_widerrufen").at(-1).dauerhaft, true);
      }
      if (mode === "reloaded") b.w.App.init({ neu: false, daten: { kontakte: [{ id: "other-book", uid: "other" }] } });
      if (mode === "locked") b.t.zeigeSperrbildschirm();
      if (mode === "account-wait-resume") {
        b.notice(saved, { ok: false, freigaben: 0 });
        assert.equal(b.commands("kontakt_originalquellen_update").length, 0);
      }
      if (["initial-setup-account-wait", "setup-stored-but-waiting"].includes(mode)) {
        b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-sync").click();
        b.w.App.edsStatus({ verfuegbar: true, buchOk: true, kalender: [], adressbuecher: [],
          originalKontaktUpdates: { verfuegbar: true, freigaben: 0 } });
        [...b.w.document.querySelectorAll("#sync-wahl button")].find(button => button.textContent === "Original contact sources").click();
        const request = b.commands("kontakt_originalquellen_freigabe").at(-1); assert.ok(request);
        b.w.App.originalKontaktFreigabe({ requestId: request.requestId, ok: true, changed: true,
          freigaben: mode === "setup-stored-but-waiting" ? 0 : 1, wartet: mode === "setup-stored-but-waiting",
          dauerhaft: true, id: saved.id, standSha256: sha(saved.text) });
        if (mode !== "setup-stored-but-waiting") {
          const update = b.commands("kontakt_originalquellen_update").at(-1); assert.ok(update);
          b.w.App.originalKontaktErgebnis({ requestId: update.requestId, ok: false, code: "account_access_wait", freigaben: 0 });
        } else assert.equal(b.commands("kontakt_originalquellen_update").length, 0);
      }
      b.notice(saved, mode === "wrong-id" ? { id: saved.id + 1 } : mode === "wrong-hash" ? { standSha256: "0".repeat(64) } : {});
      const allowed = ["success", "account-wait-resume", "result-save-no-loop", "setup-stored-but-waiting"].includes(mode);
      assert.equal(b.commands("kontakt_originalquellen_update").length, mode === "initial-setup-account-wait" ? 2 : allowed ? 1 : 0, mode);
      if (mode === "result-save-no-loop") {
        const update = b.commands("kontakt_originalquellen_update").at(-1), contacts = JSON.parse(JSON.stringify(b.t.daten().kontakte));
        contacts[0].syncQuellen = { native: { etag: '"v2"' } };
        const token = "b".repeat(64);
        b.w.App.originalKontaktErgebnis({ requestId: update.requestId, ok: true, freigaben: 1, token,
          originalSha256: update.standSha256, kontakte: contacts, fehlerQuellen: 0 });
        saved = b.commands("speichern").at(-1); assert.equal(saved.kontaktOriginalLauf, token);
        b.w.App.gespeichert({ id: saved.id, ok: true, committed: true, repairPending: false,
          standSha256: sha(saved.text), kontaktQuellenDauerhaft: true, kontaktOriginalGespeichert: token });
        b.notice(saved); b.w.App.originalKontaktNetz({ wlan: true });
        assert.equal(b.commands("kontakt_originalquellen_update").length, 1, "Result SaveACK or topology caused a clean retry loop");
        b.t.daten().kontakte[0].notiz = "Next real edit"; saved = b.save();
        assert.equal(b.commands("kontakt_originalquellen_update").length, 1);
        b.notice(saved); assert.equal(b.commands("kontakt_originalquellen_update").length, 2);
      }
      count++; console.log("DURABLE CONTACT FRONTEND PASS", mode);
    } finally { b.close(); }
  }
  assert.equal(count, 17);
}
run().catch(error => { console.error(error); process.exitCode = 1; });
