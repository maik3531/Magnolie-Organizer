"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
async function until(test) {
  for (let attempt = 0; attempt < 500; attempt++) {
    if (test()) return;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  throw Error("Personal synchronization notification check timed out");
}
async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, commands = []; let saved;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const message = JSON.parse(text); commands.push(message);
    if (message.cmd === "speichern") {
      saved = JSON.parse(message.text);
      queueMicrotask(() => w.App.gespeichert({ id: message.id, ok: true }));
    }
    if (message.cmd === "mutations_snapshot")
      queueMicrotask(() => w.App.mutationsSnapshot({ token: message.token, ok: true }));
  } } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
    w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    const peer = { device_id: "33333333-3333-4333-8333-333333333333", own_device: true, remote_own_device: true,
      state: "offline", auto_wifi: false, local_grants: { grants: { personal_tasks_sync: true } },
      grants: { grants: { personal_tasks_sync: true } } };
    const init = data => {
      w.App.init({ daten: data, neu: false }); w.App.telefonStand({ peers: [peer] });
      w.document.getElementById("zettel").textContent = "";
      w.document.getElementById("zettel").classList.add("verborgen");
    };
    init({ einstellungen: { sync: { erfolgsmeldungen: false } } });
    const batch = () => ({ device_id: peer.device_id, kind: "personal_sync.batch", pending_message_id: webcrypto.randomUUID(),
      commit_token: webcrypto.randomUUID(), body: { format: 1, run_id: webcrypto.randomUUID(), reply: true,
        last: true, requested_modules: ["tasks"], records: [] } });
    const complete = async message => {
      const previous = commands.filter(command => command.cmd === "telefon_personal_sync_commit" &&
        command.token === message.commit_token && command.erfolgreich === true).length;
      w.App.personalSync(message);
      await until(() => commands.filter(command => command.cmd === "telefon_personal_sync_commit" &&
        command.token === message.commit_token && command.erfolgreich === true).length > previous);
      assert.ok(saved.personalSync.applied_batches.includes(message.commit_token), "ACK sent without durable batch completion");
    };
    await complete(batch()); await complete(batch());
    assert.ok(!w.document.body.textContent.includes("Personal synchronization complete."), "Disabled success notification still appears");
    assert.strictEqual(saved.einstellungen.sync.erfolgsmeldungen, false);
    init(saved); await complete(batch());
    assert.ok(!w.document.body.textContent.includes("Personal synchronization complete."), "Reload lost disabled preference");
    w.OrganizerTest.daten().einstellungen.sync.erfolgsmeldungen = true;
    const enabled = batch(); await complete(enabled);
    assert.ok(w.document.body.textContent.includes("Personal synchronization complete."), "Explicit success opt-in ignored");
    w.document.getElementById("zettel").textContent = "";
    w.document.getElementById("zettel").classList.add("verborgen");
    await complete(enabled);
    assert.ok(!w.document.body.textContent.includes("Personal synchronization complete."), "ACK-loss replay creates another success notification");
    w.OrganizerTest.daten().einstellungen.sync.erfolgsmeldungen = false;
    w.App.personalSyncFehler({ fehler: "Synthetic synchronization error" });
    assert.ok(w.document.body.textContent.includes("Synthetic synchronization error"), "Errors suppressed with success notifications");
    console.log("PERSONAL SUCCESS NOTIFICATIONS PASSED: " + web);
  } finally { w.close(); }
}
(async () => { for (const web of require("./web-test-roots")) await check(web); })()
  .catch(error => { console.error(error); process.exitCode = 1; });
