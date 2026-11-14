"use strict";
// Common actual frontend init -> normalized contact -> actual save message.
// This is passive metadata preservation, never a native source/SaveACK grant.
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const web = process.env.MAGNOLIE_TEST_WEB ? path.resolve(process.env.MAGNOLIE_TEST_WEB) : path.resolve(__dirname, "../web");
const basis = { fassung: 1, share_id: "native-canonical-share", basis: "d".repeat(64),
  native_revision: "1152921504606846977", request_id: "11111111-1111-4111-8111-111111111111",
  request_sha256: "a".repeat(64), target_sha256: "b".repeat(64), receipt_id: "22222222-2222-4222-8222-222222222222" };
async function run() {
  for (const mode of ["native-saved", "max-long", "import-is-not-permission"]) {
    const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
      runScripts: "outside-only", url: "https://notes-basis.test.invalid/", pretendToBeVisual: true });
    const w = dom.window, messages = [];
    try {
      w.setTimeout = () => 1; w.clearTimeout = () => {}; w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
      w.HTMLElement.prototype.scrollIntoView = () => {}; w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
      Object.defineProperty(w, "crypto", { value: webcrypto }); w.__MAGNOLIE_BRUECKE__ = "test";
      w.webkit = { messageHandlers: { test: { postMessage: raw => messages.push(JSON.parse(raw)) } } };
      for (const name of ["i18n.js", "zeichenblatt.js", "appearance.js", "anwendung.js"]) w.eval(fs.readFileSync(path.join(web, name), "utf8"));
      await new Promise(resolve => setImmediate(resolve));
      const metadata = structuredClone(basis);
      if (mode === "max-long") metadata.native_revision = "9223372036854775807";
      if (mode === "import-is-not-permission") Object.assign(metadata, { saved: true, native: true, consent: true, sendAck: true });
      const original = { kontakte: [{ id: "local", uid: "canonical-person", notiz: "Saved synthetic edit", notesOriginalBasis: metadata }],
        notizen: [{ id: "keep", text: "Unchanged other domain" }] };
      w.App.init({ neu: false, regional: { language: "en", timeZone: "UTC" }, daten: original });
      const normalized = JSON.parse(JSON.stringify(w.OrganizerTest.daten()));
      assert.deepEqual(normalized.kontakte[0].notesOriginalBasis, metadata);
      w.OrganizerTest.daten().kontakte[0].notiz = "Later unrelated edit";
      w.OrganizerTest.speichereJetzt();
      const save = messages.filter(value => value.cmd === "speichern").at(-1); assert.ok(save);
      const stored = JSON.parse(save.text).kontakte[0];
      assert.deepEqual(stored.notesOriginalBasis, metadata);
      assert.equal(typeof stored.notesOriginalBasis.native_revision, "string");
      assert.equal(stored.id, "local"); assert.equal(stored.uid, "canonical-person");
      assert.equal(stored.notiz, "Later unrelated edit");
      assert.equal(save.kontaktOriginalLauf, undefined);
      assert.equal(messages.some(value => /kontakt_original|kontakt_originalquellen_update|saveack/i.test(value.cmd)), false,
        "Portable metadata authorized a native operation");
      console.log("NOTES BASIS ROUNDTRIP PASS", mode);
    } finally { w.close(); }
  }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
