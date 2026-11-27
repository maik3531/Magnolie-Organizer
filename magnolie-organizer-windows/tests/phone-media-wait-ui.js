"use strict";
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const sourceRoot = process.env.MAGNOLIE_TEST_SOURCE_ROOT || path.resolve(__dirname, "../..");
const source = fs.readFileSync(path.join(sourceRoot, "magnolie-organizer-windows/app/web/phone-media.js"), "utf8");
const tick = () => new Promise(resolve => setImmediate(resolve));
const peer = "11111111-1111-4111-8111-111111111111";
const legacy = { supported: true, version: "a".repeat(64), photos: true, videos: false, automatic: false,
  automatic_ready: true, automatic_phase: "idle", skip_deletions: true, busy: false,
  metadata_ready: { images: true, video: true }, pictures: { version: "b".repeat(64), default: true },
  video_destination: null, destination_choices: { images: "c".repeat(64), video: "d".repeat(64) } };
const values = { enabled: true, photos_enabled: true, videos_enabled: false, collection_mode: "phone_inventory",
  direction: "phone_to_pc", auto_mode: "manual", skip_deletions: true, photos_only: false };
const versions = Object.fromEntries(Object.keys(values).map((field, i) => [field, String(i + 1).repeat(64)]));
const shared = { ...legacy, shared_settings: { values, versions }, shared_matched: true,
  shared_runtime_ready: true, shared_start_version: "e".repeat(64), receive_consent: { granted: true, version: "f".repeat(64) } };
const backup = { backup_id: "1".repeat(64), version: "2".repeat(64), display_name: "saved.jpg", saved_ms: 1234 };
function boot({ deferredSave = false, withRecovery = false } = {}) {
  const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only", url: "https://media-wait.invalid" });
  const w = dom.window, messages = []; let saves = 0, finishSave;
  w.eval(source);
  const api = w.MagnolieMedia, send = message => { messages.push(JSON.parse(JSON.stringify(message))); return true; };
  const save = () => { saves++; return deferredSave ? new Promise(resolve => { finishSave = resolve; }) : Promise.resolve(); };
  const recovery = withRecovery ? api.createRecoveryPanel(peer, x => x, send, save) : null;
  // This case checks preservation of already loaded local history. The initial
  // application construction sequence has its own separate regression.
  if (recovery) {
    w.document.body.append(recovery);
    for (const request of messages.filter(message => message.action === "backup_list"))
      api.receive({ requestId: request.requestId, device_id: peer, ok: true, next_cursor: null,
        backups: request.media_type === "images" ? [backup] : [], location_id: "3".repeat(64),
        backup_location: request.media_type === "images" ? { is_default: true, sources: [] } : null });
  }
  const panel = api.createPanel(peer, x => x, send, save, () => true,
    recovery ? { recovery, mountLive: () => {} } : {});
  w.document.body.append(panel);
  const b = { dom, w, api, messages, panel, recovery,
    input: key => panel.querySelector(`[data-media="${key}"]`),
    button: title => [...panel.querySelectorAll("button")].find(button => button.textContent === title),
    last: () => messages.at(-1), saves: () => saves, finishSave: () => finishSave(),
    reply: (request, value) => api.receive({ requestId: request.requestId, device_id: peer, ok: true, ...value }),
    refresh: value => { api.changed({ device_id: peer }); b.reply(b.last(), value); } };
  return b;
}
function assertWaiting(b) {
  const master = b.input("enabled"), photos = b.input("photos"), automatic = b.input("automatic");
  assert(!b.panel.hidden && !master.closest("[hidden]") && master.disabled && !master.checked,
    "A supported peer without shared settings needs a visible unavailable master");
  assert(photos.closest("[hidden]") && photos.disabled && automatic.closest("[hidden]") && automatic.disabled,
    "Missing shared settings exposed legacy controls");
  assert(b.panel.querySelector('[role="status"]').textContent.includes("Waiting for native media status"));
  assert(!b.button("Refresh").closest("[hidden]") && !b.button("Refresh").disabled,
    "Waiting must remain refreshable");
}
const cases = [
  ["old peer waits without legacy edits or readiness claims", async b => {
    b.reply(b.last(), { ...legacy, skip_deletions: null }); assertWaiting(b);
    const before = b.messages.length;
    b.input("photos").checked = false; b.input("photos").dispatchEvent(new b.w.Event("change"));
    b.input("automatic").value = "wifi"; b.input("automatic").dispatchEvent(new b.w.Event("change"));
    b.input("enabled").dispatchEvent(new b.w.Event("change"));
    await tick();
    assert.equal(b.messages.length, before); assert.equal(b.saves(), 0);
    b.refresh({ supported: false }); assert(b.panel.hidden);
  }],
  ["confirmed shared values restore controls without enabling or starting", async b => {
    b.reply(b.last(), legacy); assertWaiting(b);
    const off = { ...shared, shared_matched: false,
      shared_settings: { values: { ...values, enabled: false }, versions } };
    const snapshot = JSON.stringify(off);
    b.refresh(off);
    assert(!b.input("enabled").disabled && !b.input("enabled").checked);
    assert(!b.input("photos").closest("[hidden]") && b.input("photos").disabled);
    assert.equal(b.saves(), 0); assert(b.messages.every(message => message.action === "status"));
    assert.equal(JSON.stringify(off), snapshot);
    const beforeEnable = b.messages.length;
    b.input("enabled").click(); await tick();
    assert.equal(b.messages.length, beforeEnable + 1, "One setting choice must not require an extra confirmation command");
    assert.equal(b.panel.querySelector("dialog"), null);
    assert.equal(b.last().action, "shared_setting"); assert.equal(b.last().field, "enabled");
    assert.equal(b.last().value, true); assert.equal(b.last().version, versions.enabled);
    b.reply(b.last(), shared);
    assert(!b.input("photos").disabled);
    assert(!b.messages.some(message => ["sync", "sync_shared", "request_read"].includes(message.action)));
  }],
  ["loss of shared settings removes old choices without rewriting them", async b => {
    const snapshot = JSON.stringify(shared);
    b.reply(b.last(), shared); assert(!b.input("photos").disabled);
    b.refresh(legacy); assertWaiting(b);
    const before = b.messages.length;
    b.button("Synchronize now").click(); b.button("Photos · Destination folder").click();
    b.input("photos").dispatchEvent(new b.w.Event("change")); await tick();
    assert.equal(b.messages.length, before); assert.equal(b.saves(), 0);
    assert.equal(JSON.stringify(shared), snapshot);
    b.refresh(shared); assert(!b.input("photos").disabled && b.input("enabled").checked);
  }],
  ["shared settings lost during Save-ACK do not dispatch the old edit", async b => {
    b.reply(b.last(), shared);
    b.input("photos").checked = false; b.input("photos").dispatchEvent(new b.w.Event("change"));
    assert.equal(b.saves(), 1);
    b.refresh(legacy); assertWaiting(b);
    b.finishSave(); await tick();
    assert(b.messages.every(message => message.action === "status")); assertWaiting(b);
  }, { deferredSave: true }],
  ["waiting retains Stop for an already running native operation", async b => {
    b.reply(b.last(), { ...legacy, busy: true, transfer_busy: true }); assertWaiting(b);
    const stop = b.button("Stop"); assert(!stop.closest("[hidden]") && !stop.disabled);
    stop.click(); await tick(); assert.equal(b.last().action, "cancel"); assert.equal(b.saves(), 0);
    b.reply(b.last(), { state: "idle" });
    assert(stop.hidden && stop.disabled); assert(b.input("photos").disabled);
  }],
  ["loaded local recovery remains reachable while shared media settings wait", async b => {
    b.reply(b.messages.find(message => message.action === "status"), legacy); assertWaiting(b);
    assert(!b.recovery.closest("[hidden]"));
    const restore = [...b.recovery.querySelectorAll("button")].find(button => button.textContent === "Restore");
    restore.click(); await tick();
    assert.equal(b.last().action, "backup_restore"); assert.equal(b.last().backup_id, backup.backup_id);
    assert(!b.messages.some(message => ["settings", "mode", "sync", "sync_shared"].includes(message.action)));
    b.reply(b.last(), { canceled: true });
    assert.equal(b.recovery.querySelectorAll("li").length, 1);
  }, { withRecovery: true }]
];
(async () => {
  let failures = 0;
  for (const [name, run, options] of cases) {
    const b = boot(options);
    try { await run(b); console.log("PASS " + name); }
    catch (error) { failures++; console.error("FAIL " + name + "\n" + error.stack); }
    finally { b.dom.window.close(); }
  }
  console.log(`${cases.length - failures}/${cases.length} Windows media waiting-state cases passed (JSDOM)`);
  if (failures) process.exitCode = 1;
})();
