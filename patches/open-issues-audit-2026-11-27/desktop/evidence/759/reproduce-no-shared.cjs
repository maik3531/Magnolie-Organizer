"use strict";
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const checkout = path.resolve(process.argv[2]);
const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only", url: "https://media-wait.invalid" });
const w = dom.window, messages = [];
let saves = 0;
w.eval(fs.readFileSync(path.join(checkout, "magnolie-organizer-windows/app/web/phone-media.js"), "utf8"));
const peer = "11111111-1111-4111-8111-111111111111", api = w.MagnolieMedia;
const panel = api.createPanel(peer, x => x, value => { messages.push(value); return true; }, async () => { saves++; });
w.document.body.append(panel);
const state = { supported: true, version: "a".repeat(64), photos: false, videos: false,
  automatic: false, automatic_ready: true, automatic_phase: "idle", skip_deletions: true,
  pictures: null, video_destination: null, busy: false, metadata_ready: { images: true, video: true },
  destination_choices: { images: "7".repeat(64), video: "8".repeat(64) } };
api.receive({ requestId: messages.at(-1).requestId, device_id: peer, ok: true, ...state });
const master = panel.querySelector('[data-media="enabled"]');
const photos = panel.querySelector('[data-media="photos"]');
const automatic = panel.querySelector('[data-media="automatic"]');
const result = {
  environment: "Actual Windows phone-media.js evaluated in JSDOM; native status contract input, no native process/device run",
  master_visible: !master.closest("[hidden]"), master_disabled: master.disabled,
  photos_visible: !photos.closest("[hidden]"), photos_disabled: photos.disabled,
  automatic_visible: !automatic.closest("[hidden]"), automatic_disabled: automatic.disabled,
  status: panel.querySelector('[role="status"]').textContent,
  messages_before_edit: messages.map(x => x.action), saves_before_edit: saves
};
photos.checked = true; photos.dispatchEvent(new w.Event("change"));
setImmediate(() => {
  result.messages_after_hidden_or_visible_edit = messages.map(x => x.action);
  result.saves_after_edit = saves;
  console.log(JSON.stringify(result, null, 2));
  try {
    assert(result.master_visible && result.master_disabled, "Missing shared settings must retain a visible, unavailable master switch");
    assert(!result.photos_visible && result.photos_disabled, "Missing shared settings must not expose usable legacy media options");
    assert(!result.automatic_visible && result.automatic_disabled, "Missing shared settings must not offer legacy automatic mode");
    assert.deepEqual(result.messages_after_hidden_or_visible_edit, ["status"], "An unavailable option dispatched a native mutation");
    assert.equal(result.saves_after_edit, 0, "Waiting for shared settings must be read-only");
    console.log("PASS no-shared-settings wait contract");
  } catch (error) {
    console.error(error.stack); process.exitCode = 1;
  } finally { dom.window.close(); }
});
