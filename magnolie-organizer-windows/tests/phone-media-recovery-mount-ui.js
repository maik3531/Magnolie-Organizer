"use strict";
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const sourceRoot = process.env.MAGNOLIE_TEST_SOURCE_ROOT || path.resolve(__dirname, "../..");
const source = fs.readFileSync(path.join(sourceRoot, "magnolie-organizer-windows/app/web/phone-media.js"), "utf8");
const tick = () => new Promise(resolve => setImmediate(resolve));
const peer1 = "11111111-1111-4111-8111-111111111111", peer2 = "22222222-2222-4222-8222-222222222222";
function boot() {
  const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only", url: "https://media-mount.invalid" });
  const w = dom.window, messages = []; let saves = 0;
  w.eval(source);
  const api = w.MagnolieMedia, send = message => { messages.push(JSON.parse(JSON.stringify(message))); return true; };
  const b = { dom, w, api, messages, saves: () => saves,
    create(peer, live = true) {
      const recovery = api.createRecoveryPanel(peer, x => x, send, async () => { saves++; });
      // This is the exact application order: create history, create its wrapper,
      // append the enclosing phone list only after its children are ready.
      const panel = api.createPanel(peer, x => x, send, async () => { saves++; }, () => true,
        { recovery, mountLive: live ? parent => parent.append(w.document.createElement("aside")) : null });
      return { peer, recovery, panel };
    },
    deliver(request, device = request.device_id) {
      const value = request.action === "status" ? { supported: false } : {
        backups: [{ backup_id: "a".repeat(64), version: "b".repeat(64), display_name: request.media_type + ".jpg", saved_ms: 1234 }],
        next_cursor: null, location_id: "c".repeat(64), backup_location: { is_default: true, sources: [] }
      };
      api.receive({ requestId: request.requestId, device_id: device, ok: true, ...value });
    }
  };
  return b;
}
function assertLoaded(item) {
  assert.equal(item.recovery.querySelectorAll("li").length, 2, "Initial image/video history replies were discarded during construction");
  assert(!item.recovery.closest("[hidden]"), "Existing local recovery was hidden after its readback");
}
const cases = [
  ["initial live phone row receives both local history replies", async b => {
    const item = b.create(peer1); b.w.document.body.append(item.panel); await tick();
    for (const request of [...b.messages]) b.deliver(request);
    assertLoaded(item); assert.equal(b.saves(), 0);
    assert.deepEqual(b.messages.map(message => message.action), ["backup_list", "backup_list", "status"]);
  }],
  ["multiple initial rows retain history and automatic status refresh", async b => {
    const first = b.create(peer1), second = b.create(peer2);
    b.w.document.body.append(first.panel, second.panel); await tick();
    for (const request of [...b.messages]) b.deliver(request);
    assertLoaded(first); assertLoaded(second);
    const before = b.messages.length;
    b.api.changed({ device_id: peer1 }); b.api.changed({ device_id: peer2 });
    assert.deepEqual(b.messages.slice(before).map(message => [message.device_id, message.action]),
      [[peer1, "status"], [peer2, "status"]], "A later initial row discarded an earlier automatic refresh owner");
    assert.equal(b.saves(), 0);
  }],
  ["offline local history remains independent of live media status", async b => {
    const item = b.create(peer1, false); b.w.document.body.append(item.panel); await tick();
    for (const request of [...b.messages]) b.deliver(request);
    assertLoaded(item); assert(b.messages.every(message => message.action === "backup_list"));
    assert.equal(b.saves(), 0);
  }],
  ["disposed history requests cannot populate a reattached old row", async b => {
    const old = b.create(peer1); b.w.document.body.append(old.panel); await tick();
    for (const request of [...b.messages]) b.deliver(request);
    const refresh = [...old.recovery.querySelectorAll("button")].find(button => button.textContent === "Refresh"); refresh.click();
    const stale = b.messages.at(-1); assert.equal(stale.action, "backup_list");
    old.panel.remove();
    const current = b.create(peer2); b.w.document.body.append(current.panel); await tick();
    // A discarded owner stays discarded even if somebody later reattaches its
    // old DOM; merely connected again must not revive its pending read request.
    old.recovery.querySelector("ul").replaceChildren(); b.w.document.body.append(old.panel);
    b.deliver(stale); assert.equal(old.recovery.querySelector("ul").children.length, 0);
    const before = b.messages.length; b.api.changed({ device_id: peer1 });
    assert.equal(b.messages.length, before);
  }],
  ["initial history replies remain bound to their actual peer", async b => {
    const item = b.create(peer1); b.w.document.body.append(item.panel); await tick();
    const reads = b.messages.filter(message => message.action === "backup_list");
    b.deliver(reads[0], peer2); assert.equal(item.recovery.querySelectorAll("li").length, 0);
    for (const request of [...b.messages]) b.deliver(request);
    assertLoaded(item); assert.equal(b.saves(), 0);
  }]
];
(async () => {
  let failures = 0;
  for (const [name, run] of cases) {
    const b = boot();
    try { await run(b); console.log("PASS " + name); }
    catch (error) { failures++; console.error("FAIL " + name + "\n" + error.stack); }
    finally { b.dom.window.close(); }
  }
  console.log(`${cases.length - failures}/${cases.length} Windows media recovery-mount cases passed (JSDOM)`);
  if (failures) process.exitCode = 1;
})();
