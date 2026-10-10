"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
async function until(test) {
  for (let n = 0; n < 500; n++) { if (test()) return; await new Promise(resolve => setTimeout(resolve, 5)); }
  throw Error("Scoped frontend reply timed out");
}
async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, commands = []; let saved;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const message = JSON.parse(text); commands.push(message);
    if (message.cmd === "speichern") { saved = JSON.parse(message.text); queueMicrotask(() => w.App.gespeichert({ id: message.id, ok: true })); }
    if (message.cmd === "mutations_snapshot") queueMicrotask(() => w.App.mutationsSnapshot({ token: message.token, ok: true }));
  } } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    const peer = { device_id: "22222222-2222-4222-8222-222222222222", fingerprint: "fixture-key", own_device: true, remote_own_device: true,
      state: "offline", auto_wifi: false, local_grants: { grants: { personal_notes_sync: true, personal_tasks_sync: true } },
      grants: { grants: { personal_notes_sync: true, personal_tasks_sync: true } },
      note_sync: { supported: true, ready: true, local: { mode: "phone_import" }, remote: { mode: "phone_import" } } };
    w.App.init({ neu: false, daten: {
      notizen: [{ id: "organizer-only", titel: "Mobile", text: "Phone text", notizbuchId: "private-book", angelegt: 1 }],
      notizbuecher: [{ id: "private-book", name: "Field notes" }], aufgaben: [{ id: "organizer-task", titel: "Private task", angelegt: 1 }]
    } });
    w.App.telefonStand({ peers: [peer] });
    const t = w.OrganizerTest;
    const manifest = async (notes, tasks, revision = 1) => {
      const members = { notes, tasks };
      return { format: 10, epoch: webcrypto.randomUUID(), revision, scope_hash: await t.personalSyncHash(members), members };
    };
    const scope = await manifest(["phone-note"], ["phone-task"]);
    const noteValue = { title: "Mobile", text: "Phone text", html: "", notebook_id: "phone-book", symbol: "note", created_ms: 1, modified_ms: 2, attachments: [] };
    const taskValue = { title: "Mobile task", note: "", due: "", priority: 2, completed: false, remind: false,
      lead_days: 0, reminder_minute: 480, created_ms: 1, modified_ms: 2, uid: "phone-task-uid", parent_uid: "", order: 0 };
    const bookValue = { name: "Field notes", modified_ms: 0 };
    const record = async (kind, id, value) => ({ kind, id, state: "live", clock: [{ actor_id: peer.device_id, counter: 1 }],
      hash: await t.personalSyncHash(value), modified_ms: value.modified_ms, value });
    const incoming = [await record("note", "phone-note", noteValue), await record("notebook", "phone-book", bookValue), await record("task", "phone-task", taskValue)];
    const event = (records, contentScope = scope, fingerprint = peer.fingerprint) => ({ device_id: peer.device_id,
      kind: "personal_sync.batch", content_scope: contentScope, content_scope_fingerprint: fingerprint,
      pending_message_id: webcrypto.randomUUID(), commit_token: webcrypto.randomUUID(),
      body: { format: 3, run_id: webcrypto.randomUUID(), reply: false, requested_modules: ["notes", "tasks"], trigger: "manual", records } });
    const apply = async message => {
      w.App.personalSync(message);
      await until(() => commands.some(command => command.cmd === "personal_sync_lauf_senden" && command.commit?.token === message.commit_token));
      const reply = commands.find(command => command.cmd === "personal_sync_lauf_senden" && command.commit?.token === message.commit_token);
      assert.ok(saved.personalSync.applied_batches.includes(message.commit_token), "Reply preceded durable apply");
      return reply.batches.flatMap(batch => batch.records);
    };
    let reply = await apply(event(incoming));
    assert.deepEqual(reply.map(record => record.kind + ":" + record.id).sort(), ["note:phone-note", "notebook:phone-book", "task:phone-task"]);
    assert.equal(t.daten().notizen.length, 2, "Scope updates merged an unrelated same-content Organizer note");
    assert.ok(t.daten().notizbuecher.some(book => book.id === "phone-book"), "Scope notebook was replaced by an unrelated matching name");
    assert.ok(!t.daten().personalSync.entities["note\0organizer-only"]);
    assert.ok(!t.daten().personalSync.entities["task\0organizer-task"]);
    t.daten().notizen.find(note => note.id === "phone-note").text = "Organizer addition";
    reply = await apply(event(incoming));
    assert.equal(reply.find(record => record.kind === "note").value.text, "Organizer addition", "Existing scoped note's Organizer update was not sent back");
    const retained = JSON.stringify(t.daten().notizen);
    reply = await apply(event([], await manifest([], [], 2)));
    assert.deepEqual(reply, []);
    assert.equal(JSON.stringify(t.daten().notizen), retained, "Phone removal deleted an Organizer copy");
    const invalid = event(incoming, scope, "other-device-key"); w.App.personalSync(invalid);
    await until(() => commands.some(command => command.cmd === "telefon_personal_sync_commit" && command.token === invalid.commit_token && command.erfolgreich === false));
    assert.equal(JSON.stringify(t.daten().notizen), retained);
    await assert.rejects(t.personalSyncScopeAusManifest({ ...scope, scope_hash: "0".repeat(64) }));
    const golden = { format: 10, epoch: "44444444-4444-4444-8444-444444444444", revision: 7,
      scope_hash: "589f36e8c7d673b4e24e3bebc8a020441d9e313a465f2f8f011b9cebb596fdc2",
      members: { notes: ["mobile-note", "\ue000", "😀"], tasks: ["mobile-task"] } };
    assert.equal((await t.personalSyncScopeAusManifest(golden)).notes.size, 3);
    console.log("SCOPED FRONTEND REPLY PASSED: " + web);
  } finally { w.close(); }
}
(async () => { for (const web of require("./web-test-roots")) await check(web); })().catch(error => { console.error(error); process.exitCode = 1; });
