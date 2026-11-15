"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const plain = value => JSON.parse(JSON.stringify(value));
const cases = [
  { uri: "http://example.org/public%20attachment.pdf?part=1#section", open: false },
  { uri: "https://example.org/public%20attachment.pdf?part=1#section", open: true },
  { uri: "https://drive.google.com/public-document", open: true },
  { uri: "https://user:password@example.org/private.pdf", open: false },
  { uri: "file:///synthetic/not-a-real-file.pdf", open: false },
  { uri: "javascript:throw('never executed')", open: false },
  { uri: "webdav://example.org/synthetic.pdf", open: false },
  { uri: "https://example.org/held.pdf", localOnly: true, open: false }
];
const watchdog = setTimeout(() => { console.error("Calendar attachment actions timed out"); process.exit(1); }, 60000);
(async () => {
  assert.equal(harness.exports.roots.length, 2, "Both GUI sources are required");
  for (const web of harness.exports.roots) {
    const attachments = cases.map((value, index) => ({ id: "attachment-" + index, uri: value.uri,
      name: "Synthetic attachment " + index, mimeType: "application/pdf", groesse: 123,
      ...(value.localOnly ? { localOnly: true } : {}) }));
    const b = await harness.exports.boot(web, { termine: [{ id: "appointment", uid: "appointment",
      datum: "2026-11-15", zeit: "12:00", endZeit: "13:00", titel: "Synthetic attachments",
      kalenderAnhaenge: attachments }] });
    try {
      const appointment = b.t.daten().termine[0];
      const original = plain(appointment.kalenderAnhaenge);
      b.t.oeffneTerminBlatt(appointment, "2026-11-15");
      function row(uri) {
        const result = [...b.w.document.querySelectorAll(".tb-kalender-anhang")]
          .find(element => element.querySelector("input").value === uri);
        assert.ok(result, uri); return result;
      }
      function button(element, label) { return [...element.querySelectorAll("button")].find(value => value.textContent === label); }
      for (const value of cases) {
        const element = row(value.uri), open = button(element, "Open");
        assert.equal(Boolean(open && !open.disabled && !open.hidden), value.open,
          "Actual form offers an unsupported attachment action: " + value.uri);
        const before = b.messages.filter(message => message.cmd === "sozial").length;
        if (open) open.click();
        const sent = b.messages.filter(message => message.cmd === "sozial").slice(before);
        assert.equal(sent.length, value.open ? 1 : 0);
        if (value.open) {
          assert.equal(sent[0].dienst, "custom"); assert.equal(sent[0].aktionArt, "url");
          assert.equal(sent[0].wert, value.uri); assert.equal(sent[0].aktionZiel, value.uri);
        }
        if (value.uri.startsWith("http:")) assert.match(element.textContent, /Only HTTPS attachments can be opened/);
        const copy = button(element, "Copy"); assert.ok(copy && !copy.disabled, "Original URI must remain copyable");
        copy.click(); assert.equal(b.messages.filter(message => message.cmd === "ablage_kopieren").at(-1).text, value.uri);
      }
      const editable = row(cases[0].uri), input = editable.querySelector("input");
      input.value = "https://example.org/changed.pdf"; input.dispatchEvent(new b.w.Event("change", { bubbles: true }));
      assert.ok(!button(editable, "Open").disabled && !button(editable, "Open").hidden, "Changing HTTP to HTTPS must refresh the actual action");
      input.value = cases[0].uri; input.dispatchEvent(new b.w.Event("change", { bubbles: true }));
      assert.ok(button(editable, "Open").disabled || button(editable, "Open").hidden, "Changing back to HTTP must revoke the Open action");
      b.w.document.querySelector("#tb-fertig").click();
      assert.deepEqual(plain(appointment.kalenderAnhaenge), original, "Saving must not upgrade, discard or mutate attachment data");
      b.t.oeffneTerminBlatt(appointment, "2026-11-15");
      assert.equal(row(cases[0].uri).querySelector("input").value, cases[0].uri, "HTTP URI lost after reopening");
      b.w.document.querySelector("#tb-fertig").click(); b.t.speichereJetzt();
      const saved = b.saves().at(-1); assert.ok(saved, "Actual GUI serialization was not reached");
      const persisted = JSON.parse(saved.text);
      assert.deepEqual(plain(persisted.termine[0].kalenderAnhaenge), original, "Serialized save changed attachment data");
      b.ack();
      const reopened = await harness.exports.boot(web, persisted);
      try {
        reopened.t.oeffneTerminBlatt(reopened.t.daten().termine[0], "2026-11-15");
        const restored = [...reopened.w.document.querySelectorAll(".tb-kalender-anhang")]
          .find(element => element.querySelector("input").value === cases[0].uri);
        assert.ok(restored, "HTTP attachment lost after serialized-book reinitialization");
        const open = button(restored, "Open"); assert.ok(!open || open.disabled || open.hidden);
        button(restored, "Copy").click();
        assert.equal(reopened.messages.filter(message => message.cmd === "ablage_kopieren").at(-1).text, cases[0].uri);
      } finally { reopened.close(); }
      console.log("Calendar attachment actions passed: HTTPS only, copy, URI edits and save/reopen preservation", web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
