"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
async function check(web) {
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
    const original = { id: "local", uid: "stable", vorname: "Same", nachname: "Person", telefon: "+491711234567",
      email: "same@example.test", foto: "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==",
      geaendert: 10, vcardRoundtrip: ["REV:20260101T000000Z", "PRODID:Old"] };
    for (const changed of [false, true]) {
      w.App.init({ neu: false, daten: { kontakte: [original] } });
      const incoming = { ...original, geaendert: 99, vcardRev: 99,
        foto: "data:image/gif;base64,R0lGODlhAQABAIAAAAD/AP///ywAAAAAAQABAAACAUwAOw==",
        telefon: changed ? "+491717654321" : original.telefon,
        vcardRoundtrip: ["REV:20261006T000000Z", "PRODID:Other", "PHOTO:https://example.invalid/new.jpg"] };
      const run = w.App.importErgebnis({ kontakte: [incoming] });
      const decision = w.document.querySelector("[data-import-entscheidung]");
      assert.equal(decision.value, changed ? "" : "keep");
      const differences = w.document.querySelectorAll("[data-kontakt-unterschied]");
      assert.equal(differences.length, changed ? 1 : 0);
      if (changed) {
        assert.equal(differences[0].dataset.kontaktUnterschied, "Phone numbers");
        assert.ok(!w.document.querySelector(".kontakt-datei-pruefung").textContent.includes(original.email));
      }
      [...w.document.querySelectorAll(".kontakt-datei-pruefung button")].find(b => b.textContent === "Cancel").click();
      await run;
    }
  } finally { w.close(); }
}
(async () => { for (const web of require("./web-test-roots")) await check(web);
  console.log("CONTACT CONTENT CONFLICTS PASSED: metadata ignored and only changed phone displayed");
})().catch(error => { console.error(error); process.exitCode = 1; });
