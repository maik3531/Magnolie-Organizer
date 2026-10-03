"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");

async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/index.html", pretendToBeVisual: true });
  const w = dom.window;
  const commands = [];
  try {
    Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
    w.__MAGNOLIE_BRUECKE__ = "test"; w.webkit = { messageHandlers: { test: { postMessage(message) {
      commands.push(typeof message === "string" ? JSON.parse(message) : message);
    } } } };
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    w.App.init({ daten: { notizen: [{ id: "private-note", titel: "Private", text: "Desktop text", html: "<b>Desktop text</b>",
      angelegt: 1, anhaenge: [{ id: "private-file", name: "private.pdf", art: "pdf", daten: "data:application/pdf;base64,JVBERg==" }] }],
      aufgaben: [{ id: "task", titel: "Independent task", angelegt: 1 }] }, neu: false });
    const t = w.OrganizerTest;
    const peer = { device_id: "33333333-3333-4333-8333-333333333333", note_sync: { supported: true, ready: true,
      local: { mode: "two_way" }, remote: { mode: "phone_import" } } };
    for (const format of [1, 2, 3]) {
      const snapshot = await t.personalSyncSnapshot(["notes", "tasks"], format, peer.device_id);
      assert(snapshot.some(r => r.kind === "note") && snapshot.some(r => r.kind === "notebook") && snapshot.some(r => r.kind === "task"));
      const before = JSON.stringify(snapshot);
      const filtered = t.personalSyncNotizAusgang(peer, snapshot);
      assert(filtered.length > 0 && filtered.every(record => record.kind === "task"));
      assert.equal(filtered.attachmentSources.length, 0);
      assert.equal(JSON.stringify(snapshot), before, "the local clock snapshot must survive filtering");
      const packets = t.personalSyncPakete(filtered, webcrypto.randomUUID(), false, format);
      assert(packets.flat().every(record => record.kind === "task"));
      const twoWay = { note_sync: { supported: true, ready: true, local: { mode: "two_way" }, remote: { mode: "two_way" } } };
      assert.equal(t.personalSyncNotizAusgang(twoWay, snapshot), snapshot);
    }
    assert(t.personalSyncNotizBereit({}), "legacy consent remains available");
    assert(!t.personalSyncNotizBereit({ note_sync: { supported: true, ready: false } }));
    assert(!t.personalSyncNotizBereit({ note_sync: { supported: false, ready: false, local: { mode: "phone_import" } } }));
    assert(t.personalSyncNotizImport(peer));
    assert(t.personalSyncNotizImport({ note_sync: { local: { mode: "phone_import" } } }));
    assert(!t.personalSyncNotizImport({ note_sync: { local: { mode: "two_way" } } }));
    const empty = t.personalSyncNotizAusgang(peer, [{ kind: "note" }]);
    assert.equal(t.personalSyncPakete(empty, webcrypto.randomUUID(), true, 2).length, 1,
      "an import-only reply still completes with an empty batch");
    const initial = JSON.parse(JSON.stringify(t.daten()));
    for (const choice of ["local", "remote", "cancel", "edited", "mode-changed"]) {
      w.App.init({ daten: JSON.parse(JSON.stringify(initial)), neu: false });
      const currentPeer = { ...peer, own_device: true, remote_own_device: true, auto_wifi: false,
        state: "offline", transport: "", local_grants: { grants: { personal_notes_sync: true } },
        grants: { grants: { personal_notes_sync: true } } };
      w.App.telefonStand({ peers: [currentPeer] });
      const local = (await t.personalSyncSnapshot(["notes"], 1, peer.device_id)).find(record => record.kind === "note");
      const remote = JSON.parse(JSON.stringify(local));
      remote.value.text = "Changed on phone"; remote.value.html = "<b>Changed on phone</b>";
      remote.value.modified_ms += 1; remote.modified_ms = remote.value.modified_ms;
      remote.hash = await t.personalSyncHash(remote.value);
      remote.clock = [{ actor_id: "99999999-9999-4999-8999-999999999999", counter: 1 }];
      let finished = false, failure;
      const application = t.personalSyncAnwenden([remote], {}, 1, peer.device_id, ["notes"])
        .then(() => { finished = true; }, error => { failure = error; finished = true; });
      let dialog;
      for (let attempt = 0; attempt < 100 && !finished; attempt++) {
        dialog = w.document.getElementById("personal-note-conflict");
        if (dialog) break;
        await new Promise(resolve => setTimeout(resolve, 5));
      }
      assert(dialog, "a local/phone conflict must offer a decision before replacing content");
      assert(dialog.textContent.includes("Desktop text") && dialog.textContent.includes("Changed on phone"));
      assert.equal(t.daten().notizen.length, 1);
      assert.equal(t.daten().notizen[0].text, "Desktop text");
      if (choice === "edited") t.daten().notizen[0].text = "Edited while reviewing";
      if (choice === "mode-changed") w.App.telefonStand({ peers: [{ ...currentPeer,
        note_sync: { supported: true, ready: false, local: { mode: "two_way" } } }] });
      const buttonText = choice === "local" ? "Keep (Organizer)" : choice === "cancel" ? "Cancel" : "Apply (Notes)";
      [...dialog.querySelectorAll("button")].find(button => button.textContent === buttonText).click();
      await application;
      assert.equal(t.daten().notizen.length, 1, "deciding an import conflict must not create an arbitrary conflict copy");
      assert.equal(t.daten().notizen[0].anhaenge.length, 1, "a format-1 import must preserve the local attachment");
      if (["cancel", "edited", "mode-changed"].includes(choice)) {
        assert(failure, "cancelled or stale review must leave the incoming batch uncommitted");
        assert.equal(t.daten().notizen[0].text, choice === "edited" ? "Edited while reviewing" : "Desktop text");
      } else {
        assert.ifError(failure);
        assert.equal(t.daten().notizen[0].text, choice === "remote" ? "Changed on phone" : "Desktop text");
        await t.personalSyncAnwenden([remote], {}, 1, peer.device_id, ["notes"]);
        assert.equal(w.document.getElementById("personal-note-conflict"), null, "ACK-loss replay must retain the recorded decision");
        assert.equal(t.daten().notizen.length, 1);
      }
      if (choice === "cancel") {
        const pending = { device_id: peer.device_id, kind: "personal_sync.batch", pending_message_id: webcrypto.randomUUID(),
          commit_token: webcrypto.randomUUID(), body: { format: 1, run_id: webcrypto.randomUUID(), reply: true,
            requested_modules: ["notes"], records: [remote] } };
        w.App.personalSync(pending);
        let offered;
        for (let attempt = 0; attempt < 100; attempt++) {
          offered = w.document.getElementById("personal-note-conflict");
          if (offered) break;
          await new Promise(resolve => setTimeout(resolve, 5));
        }
        assert(offered);
        [...offered.querySelectorAll("button")].find(button => button.textContent === "Cancel").click();
        for (let attempt = 0; attempt < 100 && !commands.some(command => command.token === pending.commit_token); attempt++)
          await new Promise(resolve => setTimeout(resolve, 5));
        assert(commands.some(command => command.cmd === "telefon_personal_sync_commit" &&
          command.token === pending.commit_token && command.erfolgreich === false));
        w.App.personalSync(pending);
        await new Promise(resolve => setTimeout(resolve, 20));
        assert.equal(w.document.getElementById("personal-note-conflict"), null, "a cancelled review must not reopen on every native status replay");
        assert.equal(t.daten().notizen[0].text, "Desktop text");
      }
    }
  } finally { w.close(); }
}

(async () => {
  for (const web of require("./web-test-roots")) await check(web);
  console.log("Personal note import: snapshots, task-only batches, empty replies, attachment suppression and consent gates passed for " + require("./web-test-roots").length + " frontend(s).");
})().catch(error => { console.error(error); process.exitCode = 1; });
