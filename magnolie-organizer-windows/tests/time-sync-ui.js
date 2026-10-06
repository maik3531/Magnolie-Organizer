"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { JSDOM } = require("jsdom");
const { webcrypto } = require("node:crypto");
const tick = () => new Promise(resolve => setTimeout(resolve, 1));
const plain = value => JSON.parse(JSON.stringify(value));
const id = "22222222-2222-4222-8222-222222222222", actor = "11111111-1111-4111-8111-111111111111";
const local = { enabled: true, revision: 1, epoch: "33333333-3333-4333-8333-333333333333" };
const remote = { enabled: true, revision: 1, epoch: "44444444-4444-4444-8444-444444444444" };
const peer = { device_id: "55555555-5555-4555-8555-555555555555", fingerprint: "synthetic-identity", own_device: true,
  remote_own_device: true, transport: "wifi", auto_wifi: false, time_sync: { supported: true, ready: true, local, remote } };
const entry = { id, startMinute: 1000, endMinute: 1060, pauseMinute: null, pauseMinutes: 15, zone: "UTC",
  type: "Synthetic", note: "Received version", modifiedMs: 1000, deleted: false, clock: { [actor]: 1 }, pausePlan: null };

async function check(web, scenario) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://time-sync.invalid/", pretendToBeVisual: true });
  const w = dom.window, messages = [];
  try {
    w.setTimeout = w.setInterval = w.requestAnimationFrame = () => 0;
    w.HTMLElement.prototype.scrollIntoView = () => {};
    Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
    w.__MAGNOLIE_BRUECKE__ = "test";
    w.webkit = { messageHandlers: { test: { postMessage(text) { messages.push(JSON.parse(text)); } } } };
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
    w.App.init({ daten: { zeiterfassung: { enabled: true } }, neu: false });
    const t = w.OrganizerTest, saves = () => messages.filter(value => value.cmd === "speichern");
    if (!["phone-import", "notes-activation"].includes(scenario))
      t.daten().einstellungen.sync.timeDirections = { [peer.device_id]: "two_way" };
    t.speichereJetzt(); w.App.gespeichert({ id: saves().at(-1).id, ok: true });
    if (scenario === "notes-activation") {
      t.daten().zeiterfassung.enabled = false;
      const active = { ...plain(peer), state: "online_wifi", time_sync: { ...plain(peer.time_sync), ready: false,
        local: { ...plain(local), enabled: false } } };
      w.App.telefonStand({ peers: [active] });
      assert.equal(t.daten().zeiterfassung.enabled, true);
      assert.equal(messages.filter(value => value.art === "personal_sync.time_settings" && value.inhalt.enabled).length, 1);
      w.App.telefonStand({ peers: [plain(active)] });
      assert.equal(messages.filter(value => value.art === "personal_sync.time_settings" && value.inhalt.enabled).length, 1);
      t.daten().zeiterfassung.enabled = false;
      active.time_sync.local.revision = 2;
      w.App.telefonStand({ peers: [plain(active)] });
      assert.equal(t.daten().zeiterfassung.enabled, false, "An explicit later opt-out must be respected");
      return;
    }
    if (scenario === "phone-import") {
      w.App.telefonStand({ peers: [plain(peer)] });
      t.daten().zeiterfassung.entries = [plain(entry)];
      t.daten().notizen = Array.from({ length: 30000 }, (_, n) => ({ id: "local-note-" + n, text: "Private desktop note", titel: "Local", anhaenge: [] }));
      w.App.personalTimeRequest({ device_id: peer.device_id, trigger: "manual" });
      const handled = new Set();
      for (let step = 0; step < 50; step++) {
        for (const save of saves()) if (!handled.has(save.id)) { handled.add(save.id); w.App.gespeichert({ id: save.id, ok: true }); }
        await tick();
      }
      const batches = messages.filter(value => value.art === "personal_sync.time_batch");
      assert.ok(batches.length);
      assert.ok(batches.every(value => value.inhalt.entries.length === 0), "Default import direction must not return desktop time records");
      assert.ok(batches.some(value => value.inhalt.calendar), "Inherited calendar settings remain independent of record direction");
      assert.equal(messages.filter(value => value.art === "personal_sync.batch").length, 0, "Time synchronization must not transfer 30000 desktop notes");
      return;
    }
    if (scenario === "packets") {
      w.App.telefonStand({ peers: [plain(peer)] });
      const records = Array.from({ length: 65 }, () => ({ ...plain(entry), id: webcrypto.randomUUID(), note: "😀".repeat(10000) }));
      t.daten().zeiterfassung.entries = records;
      w.App.personalTimeRequest({ device_id: peer.device_id, trigger: "manual" });
      const handled = new Set();
      for (let step = 0; step < 100; step++) {
        for (const save of saves()) if (!handled.has(save.id)) {
          handled.add(save.id); w.App.gespeichert({ id: save.id, ok: true });
        }
        await tick();
      }
      const packets = messages.filter(value => value.art === "personal_sync.time_batch").map(value => value.inhalt);
      assert.ok(packets.length > 3, "Large UTF-8 snapshots must be split before the native IPC boundary");
      assert.deepEqual(packets.flatMap(value => value.entries), records);
      for (const packet of packets) {
        assert.ok(packet.entries.length <= 32 && new TextEncoder().encode(JSON.stringify(packet)).length <= 192 * 1024);
        assert.equal(packet.sender_epoch, local.epoch); assert.equal(packet.receiver_epoch, remote.epoch);
      }
      return;
    }
    if (scenario === "auto") {
      const active = { ...plain(peer), auto_wifi: true };
      const handled = new Set();
      const settle = async () => {
        for (let step = 0; step < 50; step++) {
          for (const save of saves()) if (!handled.has(save.id)) {
            handled.add(save.id); w.App.gespeichert({ id: save.id, ok: true });
          }
          await tick();
        }
      };
      const batches = () => messages.filter(value => value.art === "personal_sync.time_batch");
      w.App.telefonStand({ peers: [active] }); await settle();
      assert.equal(batches().length, 1);
      assert.equal(batches()[0].inhalt.sender_epoch, local.epoch);
      assert.equal(batches()[0].inhalt.receiver_epoch, remote.epoch);
      w.App.telefonStand({ peers: [plain(active)] }); await settle();
      assert.equal(batches().length, 1, "An unchanged status must not start another synchronization");
      t.daten().zeiterfassung.entries = [plain(entry)]; t.speichereJetzt(); await settle();
      assert.equal(batches().length, 2); assert.equal(batches()[1].inhalt.entries[0].note, entry.note);
      w.App.telefonStand({ peers: [{ ...plain(active), auto_wifi: false }] });
      t.daten().zeiterfassung.entries[0].note = "Manual mode"; t.speichereJetzt(); await settle();
      assert.equal(batches().length, 2, "Manual mode must not initiate automatic traffic");
      w.App.personalTimeRequest({ device_id: peer.device_id, trigger: "auto_wifi" }); await settle();
      assert.equal(batches().length, 3, "A permitted remote request remains independent of local automatic initiation");
      return;
    }
    w.App.telefonStand({ peers: [plain(peer)] });
    const initial = plain(t.daten());
    const payload = { device_id: peer.device_id, pending_message_id: "66666666-6666-4666-8666-666666666666", commit_token: "synthetic-token",
      body: { format: 7, trigger: "manual", sender_epoch: remote.epoch, sender_revision: remote.revision,
        receiver_epoch: local.epoch, receiver_revision: local.revision, entries: [plain(entry)] } };
    const before = messages.length;
    const work = w.App.personalTimeBatch(payload);
    assert.equal(messages.slice(before).filter(value => value.cmd === "telefon_personal_sync_commit").length, 0);
    assert.equal(t.daten().zeiterfassung.entries[0].note, entry.note);
    if (scenario === "revoked") w.App.telefonStand({ peers: [{ ...plain(peer), time_sync: { ...plain(peer.time_sync), ready: false } }] });
    if (scenario === "identity") w.App.telefonStand({ peers: [{ ...plain(peer), fingerprint: "replacement-identity" }] });
    if (scenario === "restore") {
      initial.syncEpoch = "restored-epoch"; initial.syncMetadaten.syncEpoch = initial.syncEpoch;
      w.App.journalWiederhergestellt({ ok: true, daten: initial });
    }
    let done = false; work.finally(() => { done = true; });
    const handled = new Set();
    for (let attempt = 0; attempt < 100 && !done; attempt++) {
      for (const save of saves()) if (!handled.has(save.id)) {
        handled.add(save.id); w.App.gespeichert({ id: save.id, ok: scenario !== "failed" });
      }
      await tick();
    }
    assert.ok(done, "The save-dependent receive operation must settle");
    const receipt = messages.findLast(value => value.cmd === "telefon_personal_sync_commit");
    assert.equal(receipt.erfolgreich, scenario === "commit");
    assert.equal(receipt.token, payload.commit_token);
    if (scenario === "restore") assert.equal(t.daten().zeiterfassung.entries.length, 0);
  } finally { w.close(); }
}

(async () => {
  const roots = [path.resolve(__dirname, "../app/web")];
  const linux = path.resolve(__dirname, "../../magnolie-organizer/web");
  if (fs.existsSync(path.join(linux, "anwendung.js"))) roots.push(linux);
   for (const web of roots) for (const scenario of ["commit", "failed", "revoked", "identity", "restore", "auto", "packets", "phone-import", "notes-activation"]) await check(web, scenario);
  console.log(`TIME SYNC UI PASSED (${roots.length} frontends: durable save, failure, revocation, identity and restore)`);
})().catch(error => { console.error(error); process.exitCode = 1; });
