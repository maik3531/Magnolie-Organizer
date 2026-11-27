"use strict";
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const checkout = path.resolve(process.argv[2]);
const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only", url: "https://media-recovery.invalid" });
const w = dom.window, messages = [], peer = "11111111-1111-4111-8111-111111111111";
w.eval(fs.readFileSync(path.join(checkout, "magnolie-organizer-windows/app/web/phone-media.js"), "utf8"));
const api = w.MagnolieMedia, send = message => { messages.push(message); return true; };
// The current application creates recovery first, wraps it into the live panel,
// and only then appends the enclosing phone row to the document.
const recovery = api.createRecoveryPanel(peer, x => x, send, async () => {});
const panel = api.createPanel(peer, x => x, send, async () => {}, () => true,
  { recovery, mountLive: advanced => advanced.append(w.document.createElement("aside")) });
w.document.body.append(panel);
for (const request of messages) {
  const value = request.action === "status" ? { supported: false } : {
    backups: [{ backup_id: "1".repeat(64), version: "2".repeat(64), display_name: request.media_type + ".jpg", saved_ms: 1234 }],
    next_cursor: null, location_id: "3".repeat(64), backup_location: { is_default: true, sources: [] }
  };
  api.receive({ requestId: request.requestId, device_id: peer, ok: true, ...value });
}
console.log(JSON.stringify({ environment: "Actual UI construction order in JSDOM; no native device run",
  sent: messages.map(message => ({ action: message.action, media_type: message.media_type })),
  visible_recovery: !recovery.closest("[hidden]"), loaded_rows: recovery.querySelectorAll("li").length }, null, 2));
try {
  assert.equal(recovery.querySelectorAll("li").length, 2, "Initial local-history replies were discarded before the phone row was mounted");
  assert(!recovery.closest("[hidden]"), "Existing local history must be visible after native readback");
  console.log("PASS initial live-panel recovery mount");
} catch (error) { console.error(error.stack); process.exitCode = 1; }
finally { dom.window.close(); }
