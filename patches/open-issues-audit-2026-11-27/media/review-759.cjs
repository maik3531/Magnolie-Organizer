"use strict";
// Independent read-only product review: real Windows panel source in JSDOM.
// Usage: NODE_PATH=/path/to/existing/node_modules node review-759.cjs CHECKOUT OUTPUT_JSON
const fs = require("node:fs"), path = require("node:path"), crypto = require("node:crypto");
const assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
if (process.argv.length !== 4) throw new Error("Usage: review-759.cjs CHECKOUT OUTPUT_JSON");
const sourcePath = path.join(path.resolve(process.argv[2]), "magnolie-organizer-windows/app/web/phone-media.js");
const source = fs.readFileSync(sourcePath, "utf8");
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
function boot() {
  const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only", url: "https://media-review.invalid" });
  const w = dom.window, messages = []; let saves = 0, resolveSave;
  w.eval(source);
  const api = w.MagnolieMedia;
  const panel = api.createPanel(peer, x => x, message => { messages.push(JSON.parse(JSON.stringify(message))); return true; },
    () => { saves++; return new Promise(resolve => { resolveSave = resolve; }); });
  w.document.body.append(panel);
  const b = { dom, w, api, panel, messages,
    button: text => [...panel.querySelectorAll("button")].find(x => x.textContent === text),
    input: key => panel.querySelector(`[data-media="${key}"]`),
    reply: (request, result) => api.receive({ requestId: request.requestId, device_id: peer, ok: true, ...result }),
    last: () => messages.at(-1), saves: () => saves, finishSave: () => resolveSave(),
    status: result => { b.button("Refresh").click(); const request = b.last(); b.reply(request, result); return request; } };
  return b;
}
const cases = [
  ["folder choice loses shared settings during Save-ACK and releases its wait slot", async b => {
    b.reply(b.last(), shared);
    const folder = b.button("Photos · Destination folder");
    assert(!folder.disabled);
    folder.click(); assert.equal(b.saves(), 1);
    b.status(legacy);
    assert(b.input("photos").disabled && b.input("photos").closest("[hidden]"));
    b.finishSave(); await tick();
    assert.deepEqual(b.messages.map(x => x.action), ["status", "status"]);
    assert(b.input("enabled").disabled);
    b.status(shared);
    assert(!folder.disabled, "The rejected folder request retained its busy/choice slot");
    assert(b.input("enabled").checked && !b.input("enabled").disabled);
  }],
  ["late legacy status cannot replace the newer confirmed shared status", async b => {
    b.reply(b.last(), shared);
    b.button("Refresh").click(); const old = b.last();
    b.button("Refresh").click(); const fresh = b.last();
    b.reply(fresh, shared);
    b.reply(old, legacy);
    assert(!b.input("enabled").disabled && b.input("enabled").checked);
    assert(!b.input("photos").disabled && !b.input("photos").closest("[hidden]"));
    assert(!b.panel.querySelector('[role="status"]').textContent.includes("Waiting for native media status"));
    assert.equal(b.saves(), 0);
    assert(b.messages.every(x => x.action === "status"));
  }]
];
(async () => {
  const results = [];
  for (const [name, test] of cases) {
    const b = boot();
    try { await test(b); results.push({ name, passed: true }); }
    catch (error) { results.push({ name, passed: false, error: error.stack }); }
    finally { b.dom.window.close(); }
  }
  const report = { source_path: sourcePath, source_sha256: crypto.createHash("sha256").update(source).digest("hex"),
    environment: "Actual Windows phone-media.js evaluated in JSDOM with synthetic native replies; no native process/device/transport execution",
    tests_executed: true, total: results.length, passed: results.filter(x => x.passed).length, results };
  fs.writeFileSync(process.argv[3], JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify(report, null, 2));
  if (report.passed !== report.total) process.exitCode = 1;
})();
