"use strict";
// Independent lifecycle checks against unchanged product JavaScript.
// Usage: NODE_PATH=/path/to/node_modules node review-759-lifecycle.cjs CHECKOUT OUTPUT_JSON
const fs = require("node:fs"), path = require("node:path"), crypto = require("node:crypto");
const assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
if (process.argv.length !== 4) throw new Error("Usage: review-759-lifecycle.cjs CHECKOUT OUTPUT_JSON");
const sourcePath = path.join(path.resolve(process.argv[2]), "magnolie-organizer-windows/app/web/phone-media.js");
const source = fs.readFileSync(sourcePath, "utf8");
const tick = () => new Promise(resolve => setImmediate(resolve));
const peer1 = "11111111-1111-4111-8111-111111111111", peer2 = "22222222-2222-4222-8222-222222222222";
const values = { enabled: true, photos_enabled: true, videos_enabled: false, collection_mode: "phone_inventory",
  direction: "phone_to_pc", auto_mode: "manual", skip_deletions: true, photos_only: false };
const shared = { supported: true, version: "a".repeat(64), photos: true, videos: false, automatic: false,
  automatic_ready: true, automatic_phase: "idle", skip_deletions: true, busy: false,
  metadata_ready: { images: true, video: true }, pictures: { version: "b".repeat(64), default: true },
  video_destination: null, destination_choices: { images: "c".repeat(64), video: "d".repeat(64) },
  shared_settings: { values, versions: Object.fromEntries(Object.keys(values).map((key, i) => [key, String(i + 1).repeat(64)])) },
  shared_matched: true, shared_runtime_ready: true, shared_start_version: "e".repeat(64),
  receive_consent: { granted: true, version: "f".repeat(64) } };
function boot() {
  const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only", url: "https://media-lifecycle.invalid" });
  const w = dom.window, observedMaps = [], messages = [], timers = new Map();
  const OriginalMap = w.Map;
  // Observe the two original top-level ownership maps, without replacing the
  // product source or retaining all its per-panel local maps in the harness.
  w.Map = class ObservedMap extends OriginalMap {
    constructor(...args) { super(...args); if (observedMaps.length < 2) observedMaps.push(this); }
  };
  const originalQueue = w.queueMicrotask.bind(w); let queuedMicrotasks = 0;
  w.queueMicrotask = callback => { queuedMicrotasks++; originalQueue(callback); };
  const originalSetTimeout = w.setTimeout.bind(w), originalClearTimeout = w.clearTimeout.bind(w);
  w.setTimeout = (callback, delay, ...args) => {
    let id;
    id = originalSetTimeout(() => { timers.delete(id); callback(...args); }, delay);
    timers.set(id, delay); return id;
  };
  w.clearTimeout = id => { timers.delete(id); originalClearTimeout(id); };
  w.eval(source);
  assert.equal(observedMaps.length, 2);
  const api = w.MagnolieMedia, send = message => { messages.push(JSON.parse(JSON.stringify(message))); return true; };
  return { dom, w, api, messages, timers, pending: observedMaps[0], panels: observedMaps[1],
    queuedMicrotasks: () => queuedMicrotasks,
    create(peer, withRecovery = true) {
      const recovery = withRecovery ? api.createRecoveryPanel(peer, x => x, send, async () => {}) : null;
      const panel = api.createPanel(peer, x => x, send, async () => {}, () => true,
        recovery ? { recovery, mountLive: () => {} } : {});
      return { panel, recovery, peer };
    },
    reply(request, value) { api.receive({ requestId: request.requestId, device_id: request.device_id, ok: true, ...value }); },
    settle(requests) {
      for (const request of requests) this.reply(request, request.action === "status" ? { supported: false } :
        { backups: [], next_cursor: null, backup_location: null });
    }
  };
}
const cases = [
  ["128 two-phone rebuilds retain only current owners and keep automatic refresh", async b => {
    let maximumPendingAfterCleanup = 0, maximumPanelsAfterCleanup = 0;
    for (let iteration = 0; iteration < 128; iteration++) {
      const firstMessage = b.messages.length, firstMicrotask = b.queuedMicrotasks();
      const first = b.create(peer1), second = b.create(peer2);
      b.w.document.body.replaceChildren(first.panel, second.panel);
      await tick();
      assert.equal(b.queuedMicrotasks() - firstMicrotask, 3,
        "Two existing preview-observer microtasks plus one shared cleanup must cover the synchronous rebuild");
      assert.equal(b.pending.size, 6); assert.equal(b.panels.size, 2);
      assert([...b.pending.values()].every(item => item.root.isConnected));
      assert([...b.panels.keys()].every(root => root.isConnected));
      maximumPendingAfterCleanup = Math.max(maximumPendingAfterCleanup, b.pending.size);
      maximumPanelsAfterCleanup = Math.max(maximumPanelsAfterCleanup, b.panels.size);
      b.settle(b.messages.slice(firstMessage)); assert.equal(b.pending.size, 0);
      const beforeRefresh = b.messages.length;
      b.api.changed({ device_id: peer1 }); b.api.changed({ device_id: peer2 });
      assert.deepEqual(b.messages.slice(beforeRefresh).map(item => [item.device_id, item.action]),
        [[peer1, "status"], [peer2, "status"]]);
      b.settle(b.messages.slice(beforeRefresh)); await tick();
      assert.equal(b.pending.size, 0); assert.equal(b.panels.size, 2); assert.equal(b.timers.size, 0);
    }
    return { rebuild_turns: 128, phone_rows_per_turn: 2, maximum_pending_after_cleanup: maximumPendingAfterCleanup,
      maximum_panel_owners_after_cleanup: maximumPanelsAfterCleanup, final_pending: b.pending.size,
      final_panel_owners: b.panels.size, active_timers: b.timers.size,
      microtasks_per_rebuild: 3, existing_preview_observer_microtasks_per_rebuild: 2,
      additional_cleanup_microtasks_per_rebuild: 1 };
  }],
  ["detached folder request releases its real timeout and cannot revive an old owner", async b => {
    const old = b.create(peer1, false); b.w.document.body.append(old.panel); await tick();
    b.reply(b.messages.at(-1), shared);
    const choice = [...old.panel.querySelectorAll("button")].find(button => button.textContent === "Photos · Destination folder");
    assert(choice && !choice.disabled); choice.click(); await tick();
    const stale = b.messages.at(-1); assert.equal(stale.action, "pick_destination");
    assert.equal(b.timers.size, 1); assert.equal([...b.timers.values()][0], 65000);
    assert(b.pending.has(stale.requestId));
    old.panel.remove();
    const current = b.create(peer2, false); b.w.document.body.append(current.panel); await tick();
    assert.equal(b.timers.size, 0, "Detached request retained its 65-second timeout closure");
    assert(!b.pending.has(stale.requestId)); assert.equal(b.panels.size, 1);
    assert([...b.panels.keys()].every(root => current.panel.contains(root)));
    b.w.document.body.append(old.panel);
    const before = b.messages.length;
    b.reply(stale, { ...shared, canceled: true }); b.api.changed({ device_id: peer1 });
    assert.equal(b.messages.length, before); assert.equal(b.panels.size, 1);
    return { detached_request_removed: true, timeout_cleared: true, old_owner_revived: false };
  }]
];
(async () => {
  const results = [];
  for (const [name, test] of cases) {
    const b = boot();
    try { results.push({ name, passed: true, observations: await test(b) }); }
    catch (error) { results.push({ name, passed: false, error: error.stack }); }
    finally { b.dom.window.close(); }
  }
  const report = { source_path: sourcePath, source_sha256: crypto.createHash("sha256").update(source).digest("hex"),
    environment: "Actual unchanged Windows phone-media.js in JSDOM; ownership maps, queued microtasks and real JSDOM timeout handles observed by harness",
    scope_limit: "Bounded UI lifecycle regression tests; not a native Windows, real-device, heap-profile, month-long tray or wall-clock duration test",
    tests_executed: true, total: results.length, passed: results.filter(item => item.passed).length, results };
  fs.writeFileSync(process.argv[3], JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify(report, null, 2));
  if (report.passed !== report.total) process.exitCode = 1;
})();
