"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const fixture = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(fixture, module);
harness.filename = fixture; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(fixture, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "contactPreviewStart: starteKdeKontaktImport, speichereJetzt: speichereJetzt,"));') +
  "\nmodule.exports={boot,roots};", fixture);
const watchdog = setTimeout(() => { console.error("Bounded contact-preview fixture timed out"); process.exit(1); }, 20000);
(async () => {
  for (const web of harness.exports.roots) for (const [provider, failure] of [["notes", ""], ["kde", ""], ["notes", "invalid-last"], ["notes", "denied"]]) {
    const b = await harness.exports.boot(web, { kontakte: [], einstellungen: { adressen: { foto: false } } });
    try {
      const device = provider === "notes" ? "notes:11111111-1111-4111-8111-111111111111" : "synthetic-kde";
      const fingerprint = "a".repeat(64);
      const cards = Array.from({ length: 6 }, (_, index) => ({ uid: "synthetic-" + index,
        bindung: "urn:magnolie:import:" + provider + ":" + createHash("sha256").update(provider + "-contact-v1\0" + device + "\0" + fingerprint + "\0synthetic-" + index).digest("hex"),
        kontakt: { vorname: "Synthetic " + index, email: "fixture" + index + "@example.invalid" } }));
      b.w.App.telefonStand(provider === "notes" ? { peers: [{ device_id: device.slice(6), state: "online_wifi", own_device: true,
        remote_own_device: true, contacts_read_available: true, contacts_fingerprint: fingerprint }], kdeconnect: { contacts_available: false } } :
        { peers: [], kdeconnect: { contacts_available: true, contacts_device_id: device } });
      const before = JSON.stringify(b.t.daten().kontakte), handled = new Set(), cardRequests = [];
      let complete = false;
      b.t.contactPreviewStart().then(() => { complete = true; });
      const deadline = Date.now() + 6000;
      while (!complete && Date.now() < deadline) {
        await new Promise(resolve => setImmediate(resolve));
        for (const message of b.messages) {
          if (handled.has(message)) continue; handled.add(message);
          if (message.cmd === "speichern") b.w.App.gespeichert({ id: message.id, ok: true });
          if (message.cmd !== "telefon_kontakte") continue;
          const dialog = b.w.document.querySelector(".kontakt-import-dialog");
          assert.ok(dialog.querySelector(".hauptknopf").disabled, "An unfinished preview allowed Apply");
          if (message.uids) cardRequests.push(message.uids.length);
          // Notes serializes native cards. Each response is individually valid,
          // but combining five under one bridge deadline can exceed that deadline.
          const nativeBudgetExceeded = provider === "notes" && (message.uids?.length || 0) * 3 > 8;
          let contacts = message.uids ? cards.filter(card => message.uids.includes(card.uid)).map(card => ({ ...card })) :
            cards.map(card => ({ uid: card.uid, modified_ms: 1 }));
          if (message.uids && failure === "invalid-last") contacts = contacts.map(card => card.uid === cards.at(-1).uid ? { ...card, kontakt: null } : card);
          b.w.App.telefonKontakte({ ok: failure !== "denied" && !nativeBudgetExceeded, requestId: message.requestId,
            device_id: device, fingerprint, contacts });
        }
      }
      assert.ok(complete, "Preview did not reach a bounded outcome");
      const dialog = b.w.document.querySelector(".kontakt-import-dialog");
      assert.equal(JSON.stringify(b.t.daten().kontakte), before, "Reading a preview changed contacts");
      if (failure) assert.ok(dialog.querySelector(".hauptknopf").disabled, "Invalid or denied data allowed Apply");
      else {
        assert.equal(dialog.querySelectorAll("details").length, 6, "A valid multi-contact preview was lost to a native aggregate deadline");
        assert.equal(dialog.querySelector(".hauptknopf").disabled, false);
        if (provider === "kde") assert.deepEqual(cardRequests, [5, 1], "Native KDE batching was unnecessarily serialized");
      }
      [...dialog.querySelectorAll("button")].find(button => button.textContent === "Cancel").click();
      assert.equal(JSON.stringify(b.t.daten().kontakte), before);
      assert.ok(!b.messages.some(message => message.cmd === "mutations_snapshot"), "Preview/cancel created a contact transaction");
    } finally { b.close(); }
  }
  console.log("PHONE CONTACT PREVIEW BUDGET PASS: both providers/frontends, six cards, pending/invalid/denied Apply guard, no data writes");
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
