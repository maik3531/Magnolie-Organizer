"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const { createHash } = require("node:crypto");

const source = path.resolve(__dirname, "../../magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harness = new Module(source, module);
harness.filename = source;
harness.paths = Module._nodeModulePaths(path.dirname(source));
harness._compile(fs.readFileSync(source, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot};", source);
const web = path.resolve(__dirname, "../web");
const sha = text => createHash("sha256").update(text).digest("hex");

async function waitFor(read) {
  for (let attempt = 0; attempt < 150; attempt++) {
    const result = read();
    if (result) return result;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  throw new Error("Expected renderer message did not arrive");
}

async function check(mode) {
  const session = await harness.exports.boot(web);
  const { w, t, messages, saves } = session;
  const peer = { device_id: "22222222-2222-4222-8222-222222222222", display_name: "Synthetic", fingerprint: "test-current-key" };
  const token = Buffer.alloc(32, 1).toString("base64");
  const value = { title: "Phone task", note: "", due: "", priority: 2, completed: false,
    remind: false, lead_days: 0, reminder_minute: 480, created_ms: 1, modified_ms: 2 };
  const members = { notes: [], tasks: ["phone-task"] };
  const pending = { device_id: peer.device_id, kind: "personal_sync.batch", connection_save: mode !== "unowned",
    commit_token: token, pending_message_id: "33333333-3333-4333-8333-333333333333",
    content_scope: { format: 10, epoch: "44444444-4444-4444-8444-444444444444", revision: 1,
      scope_hash: await t.personalSyncHash(members), members },
    content_scope_fingerprint: peer.fingerprint,
    body: { trigger: "auto_connection", format: 3, run_id: "55555555-5555-4555-8555-555555555555",
      requested_modules: ["tasks"], reply: mode === "accepted_reply", records: [{ kind: "task", id: "phone-task", state: "live",
        value, hash: await t.personalSyncHash(value), modified_ms: 2, clock: [{ actor_id: peer.device_id, counter: 1 }] }] } };
  try {
    w.App.telefonStand({ peers: [peer] });
    t.speichereJetzt();
    const initial = saves().at(-1);
    const initialHash = sha(initial.text);
    w.App.gespeichert({ id: initial.id, ok: true, committed: true, standSha256: initialHash });
    const hasTask = () => t.daten().aufgaben.some(record => record.id === "phone-task");
    const commit = () => messages.find(message => message.cmd === "telefon_personal_sync_commit");
    const reply = () => messages.find(message => message.cmd === "telefon_personal_connection_reply");
    w.App.personalSync(pending);
    if (mode !== "unowned") {
      const protectedSave = await waitFor(() => saves().find(save => save.personalConnectionLauf));
      assert.deepEqual(protectedSave.personalConnectionLauf,
        { peer: peer.device_id, messageId: pending.pending_message_id, token, before: initialHash });
      const sent = JSON.parse(protectedSave.text);
      assert.equal(sent.aufgaben.find(record => record.id === "phone-task").titel, "Phone task");
      assert(sent.personalSync.applied_batches.includes(token));
      assert(!hasTask());
      assert.equal(w.document.querySelector("#schreibtisch").hasAttribute("inert"), true);
      assert(!commit());
      assert(!reply());
      w.App.gespeichert({ id: protectedSave.id, ok: mode !== "rejected", committed: mode !== "rejected",
        repairPending: mode === "repair", standSha256: sha(protectedSave.text) });
    }
    if (mode === "accepted") {
      const packet = await waitFor(reply);
      assert.equal(packet.token, token);
      assert.equal(packet.batches.length, 1);
      assert.equal(packet.batches[0].reply, true);
      assert.equal(packet.batches[0].records[0].id, "phone-task");
      assert(!commit());
    } else {
      const receipt = await waitFor(commit);
      assert.equal(receipt.erfolgreich, mode === "accepted_reply");
      assert(!reply());
    }
    assert.equal(hasTask(), ["accepted", "accepted_reply", "repair"].includes(mode));
    assert.equal(w.document.querySelector("#schreibtisch").hasAttribute("inert"), false);
    if (mode === "rejected") {
      t.daten().aufgaben.push({ id: "local-edit", titel: "Local edit" });
      t.speichereJetzt();
      const ordinarySave = saves().at(-1);
      assert(!ordinarySave.personalConnectionLauf);
      const stored = JSON.parse(ordinarySave.text);
      assert(!stored.aufgaben.some(record => record.id === "phone-task"));
      assert(!stored.personalSync.applied_batches.includes(token));
    }
    if (mode === "unowned") assert.equal(saves().length, 1);
  } finally {
    session.close();
  }
}

async function checkStart(mode) {
  const session = await harness.exports.boot(web);
  const { w, t, messages, saves } = session;
  const peer = { device_id: "22222222-2222-4222-8222-222222222222", fingerprint: "test-current-key",
    transport: "bluetooth" };
  const members = { notes: [], tasks: ["phone-task"] };
  const manifest = { format: 10, epoch: "44444444-4444-4444-8444-444444444444", revision: 1,
    scope_hash: await t.personalSyncHash(members), members };
  const prepare = () => messages.find(message => message.cmd === "telefon_personal_connection_prepare");
  const start = () => messages.find(message => message.cmd === "telefon_personal_connection_start");
  const acknowledge = (save, ok) => w.App.gespeichert({ id: save.id, ok, committed: ok, standSha256: sha(save.text) });
  try {
    t.daten().aufgaben.push({ id: "phone-task", titel: "Phone task" }, { id: "private-task", titel: "Private task" });
    w.App.telefonStand({ peers: [peer] });
    assert(!prepare());
    w.App.personalSyncCollection({ device_id: peer.device_id, fingerprint: peer.fingerprint,
      members, connection_start: true });
    const initial = await waitFor(() => saves().at(-1));
    assert(!prepare());
    acknowledge(initial, true);
    const pending = await waitFor(prepare);
    assert.equal(pending.fingerprint, peer.fingerprint);
    const token = "f".repeat(64), run_id = "55555555-5555-4555-8555-555555555555";
    const processing = w.App.personalConnectionStartErgebnis({ requestId: pending.requestId, ok: true,
      plan: { token, run_id, scope: manifest, transport: "bluetooth", format: 3 } });
    const saved = await waitFor(() => saves().at(-1) === initial ? null : saves().at(-1));
    assert(!saved.personalConnectionLauf);
    assert(!start());
    if (mode === "transport-changed") w.App.telefonStand({ peers: [{ ...peer, transport: "wifi" }] });
    acknowledge(saved, mode !== "save-failed");
    await processing;
    if (mode === "accepted") {
      const packet = await waitFor(start);
      assert.equal(packet.token, token);
      assert.equal(packet.savedHash, sha(saved.text));
      assert.deepEqual(packet.request, { format: 3, run_id, trigger: "auto_connection", modules: ["notes", "tasks"] });
      assert.deepEqual(packet.batches.flatMap(batch => batch.records.map(record => record.id)), ["phone-task"]);
      assert.equal(packet.batches[0].records[0].value.title, "Phone task");
    } else {
      assert(!start());
    }
  } finally {
    session.close();
  }
}

(async () => {
  for (const mode of ["accepted", "accepted_reply", "rejected", "repair", "unowned"]) {
    await check(mode);
    console.log(`Connection automation renderer ${mode}: PASS`);
  }
  for (const mode of ["accepted", "save-failed", "transport-changed"]) {
    await checkStart(mode);
    console.log(`Connection automation start ${mode}: PASS`);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
