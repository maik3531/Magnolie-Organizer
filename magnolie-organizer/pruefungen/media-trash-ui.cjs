"use strict";

const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), vm = require("node:vm");
const assert = require("node:assert/strict");
const harnessPath = path.resolve(__dirname, "../../magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harness = new Module(harnessPath, module);
harness.filename = harnessPath; harness.paths = Module._nodeModulePaths(path.dirname(harnessPath));
harness._compile(fs.readFileSync(harnessPath, "utf8").split("async function run(web)")[0] + "\nmodule.exports = {boot, roots};", harnessPath);
const linux = path.resolve(__dirname, "../web");
const messages = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../tools/media_trash_locales.json"), "utf8"));
for (const locale of Object.keys(messages).filter(locale => locale !== "en")) {
  let catalog;
  vm.runInNewContext(fs.readFileSync(path.join(linux, "i18n", locale + ".js"), "utf8"), {
    window: { MagnolieI18n: { registerCatalog: (_, value) => { catalog = value; } } }
  });
  messages.en.forEach((key, index) => assert.equal(catalog.messages[key], messages[locale][index], `${locale}: ${key}`));
}
const row = (index = 1) => ({ scope: "a".repeat(64), operation: index.toString(16).padStart(32, "0"), version: "b".repeat(64),
  name: index === 1 ? "<img src=x onerror=bad>.mp4" : `video-${index}.mp4`, media_type: "video", state: "trashed" });
const plain = value => JSON.parse(JSON.stringify(value));

(async () => {
  let cases = 0;
  for (const web of harness.exports.roots) for (const locale of ["en", "de"]) {
    const b = await harness.exports.boot(web, { notizen: [{ id: "keep", titel: "Keep", text: "Keep", html: "Keep" }],
      papierkorb: [{ id: "keep-trash", art: "note", name: "Existing note", geloescht: Date.now(), eintrag: { id: "old", titel: "Old", text: "Keep" } }],
      einstellungen: { papierkorb: { an: true, tage: 0 }, adressen: { kommunikation: { anruf: { telefonId: "11111111-1111-4111-8111-111111111111" } } } } });
    try {
      if (locale === "de") { b.w.eval(fs.readFileSync(path.join(web, "i18n/de.js"), "utf8")); b.w.MagnolieI18n.setLocale("de"); }
      b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-sicherheit").click();
      const d = b.w.document, root = () => d.querySelector("#medien-papierkorb");
      const calls = () => b.messages.filter(message => message.cmd === "medien_papierkorb");
      if (path.resolve(web) !== linux) {
        assert.equal(root(), null); assert.equal(calls().length, 0, "Unsupported Windows UI must not dispatch a copied native trash action"); cases++; continue;
      }
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
      assert.ok(root().hidden && calls().length === 1);
      const answer = (value, request = calls().at(-1)) => b.w.App.medienPapierkorbStand({ ok: true, supported: true,
        request_id: request.request_id, action: request.action, scopes: [row().scope], ...value });
      answer({ entries: [row()], total: 1, next_cursor: null });
      assert.ok(!root().hidden && root().textContent.includes(locale === "de" ? "Fotos und Videos" : "Photos and videos"));
      assert.equal(root().querySelector("img"), null, "Native filenames must use text, never HTML");
      const restore = () => root().querySelector("[data-media-restore]");
      assert.ok(restore()); restore().click();
      const selected = calls().at(-1);
      assert.deepEqual(Object.keys(selected).sort(), ["action", "cmd", "operation", "request_id", "scope", "version"]);
      assert.equal(selected.action, "restore"); assert.equal(selected.operation, row().operation);
      assert.ok([...root().querySelectorAll("button")].every(button => button.disabled));
      b.w.App.medienPapierkorbStand({ ok: true, supported: false, request_id: "old_unrelated_request" });
      assert.ok(!root().hidden && restore(), "An old reply must not clear the live selection");
      answer({ ok: false }); assert.ok(restore() && !restore().disabled, "A failed restore must keep its row");
      restore().click(); answer({ completed: { scope: row().scope, operation: "c".repeat(32), state: "restored" } });
      assert.ok(restore(), "A foreign completion must not remove the selected entry");
      restore().click(); answer({ completed: { scope: row().scope, operation: row().operation, state: "restored" } });
      assert.equal(restore(), null); assert.equal(calls().at(-1).action, "list", "A verified completion refreshes with a separate native read");
      answer({ entries: [], total: 0, next_cursor: null });
      assert.equal(JSON.stringify(b.t.daten()), before, "External native trash must not enter Notes/book data or its auto-purge list");
      assert.equal(b.saves().length, saves, "Native media restore must not manufacture a book save");
      cases++;

      d.querySelector("#medien-papierkorb-aktualisieren").click();
      answer({ entries: Array.from({ length: 128 }, (_, index) => row(index + 1)), total: 129, next_cursor: 128 });
      const more = root().lastElementChild;
      assert.equal(more.tagName, "BUTTON"); more.click(); assert.equal(calls().at(-1).cursor, 128);
      answer({ entries: [row(129)], total: 129, next_cursor: null });
      assert.equal(root().querySelectorAll("[data-media-restore]").length, 129);
      d.querySelector("#medien-papierkorb-aktualisieren").click();
      answer({ entries: [], total: 129, next_cursor: null });
      assert.equal(root().querySelectorAll("[data-media-restore]").length, 129, "Malformed/truncated overview must not clear cached entries");
      d.querySelector("#medien-papierkorb-aktualisieren").click();
      answer({ entries: [], total: 0, next_cursor: null, scopes: [] });
      assert.equal(root().querySelectorAll("[data-media-restore]").length, 129, "Lost known journal scope must HOLD cached entries, not claim an empty recycle bin");
      d.querySelector("#medien-papierkorb-aktualisieren").click();
      answer({ entries: [{ ...row(2), state: "purge_prepared" }], total: 1, next_cursor: null });
      assert.ok(restore(), "An interrupted expiry remains recoverable while its bytes are intact");
      assert.equal(root().querySelector("[data-media-cancel]"), null);
      const pendingRow = { ...row(2), state: "prepared" };
      d.querySelector("#medien-papierkorb-aktualisieren").click(); answer({ entries: [pendingRow], total: 1, next_cursor: null });
      assert.ok(root().querySelector("[data-media-cancel]")); root().querySelector("[data-media-cancel]").click();
      answer({ completed: { scope: pendingRow.scope, operation: pendingRow.operation, state: "canceled" } });
      answer({ entries: [], total: 0, next_cursor: null });
      d.querySelector("#medien-papierkorb-aktualisieren").click(); answer({ supported: false });
      assert.ok(root().hidden && !restore(), "Unavailable native implementation must leave no controls"); cases++;

      b.w.App.init({ daten: plain(b.t.daten()), neu: false, regional: { language: locale, timeZone: "UTC" } });
      b.t.oeffneEinstellungen(); d.querySelector("#einst-tab-sicherheit").click();
      const old = calls().at(-1);
      b.w.App.init({ gesperrt: true });
      answer({ entries: [row()], total: 1, next_cursor: null }, old);
      assert.ok(!root() || root().hidden); assert.equal(d.querySelectorAll("[data-media-restore]").length, 0,
        "Lock/book initialization must discard private native rows and stale callbacks"); cases++;
    } finally { b.close(); }
  }
  console.log(`Media recycle bin UI: ${cases} frontend/locale cases PASS; 19 catalogs checked. No installed GUI acceptance claimed.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
