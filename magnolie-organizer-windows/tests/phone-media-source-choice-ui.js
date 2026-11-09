"use strict";
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const tick = () => new Promise(resolve => setImmediate(resolve));
function boot() {
  const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only", url: "https://native-source.invalid" });
  const w = dom.window, messages = []; let resolveSave, rejectSave, sameBook = true;
  w.eval(fs.readFileSync(path.join(__dirname, "../app/web/phone-media.js"), "utf8"));
  const peer = "11111111-1111-4111-8111-111111111111", api = w.MagnolieMedia;
  const panel = api.createPanel(peer, x => x, value => { messages.push(JSON.parse(JSON.stringify(value))); return true; },
    () => new Promise((resolve, reject) => { resolveSave = resolve; rejectSave = reject; }), () => sameBook);
  w.document.body.append(panel);
  const values = { enabled: true, photos_enabled: true, videos_enabled: true, collection_mode: "entire_collection",
    direction: "pc_to_phone", auto_mode: "manual", skip_deletions: false, photos_only: false };
  const state = { supported: true, busy: false, automatic_ready: true, metadata_ready: { images: true, video: true },
    shared_runtime_ready: true, shared_matched: true, shared_settings: { values, versions: {} },
    receive_consent: { granted: false, version: "b".repeat(64) }, send_consent: { photos: true, videos: true, version: "c".repeat(64) },
    collection_sources_supported: true, collection_sources_version: "a".repeat(64),
    destination_choices: { images: "d".repeat(64), video: "e".repeat(64) },
    pictures: { version: "f".repeat(64), default: false }, video_destination: { version: null, default: false },
    collection_sources: [{ id: "opaque-root", media_type: "images", display_path: "C:\\private\\<img src=x>" }] };
  function reply(request, value) { api.receive({ requestId: request.requestId, device_id: peer, ok: true, ...value }); }
  reply(messages.at(-1), state);
  const add = kind => panel.querySelector(`[data-collection-source-add="${kind}"]`);
  const refresh = () => [...panel.querySelectorAll("button")].find(b => b.textContent === "Refresh").click();
  return { dom, w, api, panel, messages, state, reply, add, refresh,
    sourceMessages: () => messages.filter(m => m.action === "pick_collection_source"),
    changeBook: () => { sameBook = false; }, save: () => resolveSave(), fail: () => rejectSave(Error("actual save failed")) };
}
(async () => {
  let cases = 0;
  async function test(name, fn) { const b = boot(); try { await fn(b); cases++; }
    catch (error) { error.message = name + ": " + error.message; throw error; } finally { b.dom.window.close(); } }
  await test("source choice is independent of PC receive and waits for actual save", async b => {
    assert(!b.add("images").disabled); assert(b.panel.querySelector('[data-destination="images"]').disabled);
    const path = b.state.collection_sources[0].display_path;
    assert(!b.panel.textContent.includes(path)); assert.equal(b.panel.querySelector("img"), null);
    assert(b.panel.querySelector('[title="' + path.replaceAll("\\", "\\\\") + '"]'));
    b.add("images").click(); assert.equal(b.sourceMessages().length, 0); assert(b.add("video").disabled);
    b.save(); await tick(); const request = b.sourceMessages()[0];
    assert.deepEqual(Object.keys(request).sort(), ["cmd", "requestId", "device_id", "action", "media_type", "version"].sort());
    assert.equal(request.version, b.state.collection_sources_version); assert.equal(request.media_type, "images");
    assert(!b.panel.querySelector('[data-media-thumbnails]').checked);
    b.api.receive({ requestId: "foreign-old-choice", device_id: request.device_id, ok: true, ...b.state }); assert(b.add("images").disabled);
    b.reply(request, { ...b.state, canceled: true }); assert(!b.add("images").disabled);
    assert.equal(b.sourceMessages().length, 1);
    assert(!b.messages.some(m => ["sync", "sync_shared", "trash_preview", "trash_thumbnail"].includes(m.action)));
  });
  for (const [name, changes] of [["import-only", { collection_mode: "import_only" }], ["receive-only", { direction: "phone_to_pc" }],
    ["OFF", { enabled: false }], ["images disabled", { photos_enabled: false }]]) {
    await test(name + " cannot dispatch export selection", async b => {
      b.refresh(); b.reply(b.messages.at(-1), { ...b.state, shared_settings: { ...b.state.shared_settings, values: { ...b.state.shared_settings.values, ...changes } } });
      assert(b.add("images").disabled); b.add("images").click(); await tick(); assert.equal(b.sourceMessages().length, 0);
    });
  }
  for (const [name, changes] of [["unmatched", { shared_matched: false }], ["unsupported", { collection_sources_supported: false }],
    ["no local SEND consent", { send_consent: { photos: false, videos: false } }], ["missing connection version", { collection_sources_version: null }]]) {
    await test(name + " keeps selection closed", async b => {
      b.refresh(); b.reply(b.messages.at(-1), { ...b.state, ...changes }); assert(b.add("images").disabled);
    });
  }
  await test("save failure creates no native request", async b => {
    b.add("images").click(); b.fail(); await tick(); assert.equal(b.sourceMessages().length, 0); assert(!b.add("images").disabled);
  });
  await test("changed full native context during save cannot reach picker", async b => {
    b.refresh(); const status = b.messages.at(-1); b.add("images").click();
    b.reply(status, { ...b.state, collection_sources_version: "d".repeat(64) });
    b.save(); await tick(); assert.equal(b.sourceMessages().length, 0); assert(!b.add("images").disabled);
  });
  await test("detached book panel cannot dispatch a late saved choice", async b => {
    b.add("images").click(); b.panel.remove(); b.save(); await tick(); assert.equal(b.sourceMessages().length, 0);
  });
  await test("a retained panel cannot adopt a different book during save", async b => {
    b.add("images").click(); b.changeBook(); b.save(); await tick(); assert.equal(b.sourceMessages().length, 0);
  });
  for (const action of ["pick_destination", "default_destination"]) {
    for (const newer of [false, true]) await test(action + " releases its Save-ACK slot after unsupported or superseded reply " + newer, async b => {
      const state = { ...b.state, receive_consent: { ...b.state.receive_consent, granted: true } };
      b.refresh(); b.reply(b.messages.at(-1), state);
      const pick = () => b.panel.querySelector(`[data-destination="images"][data-destination-action="${action}"]`);
      pick().click(); b.save(); await tick(); const choice = b.messages.at(-1);
      if (newer) { b.refresh(); b.reply(b.messages.at(-1), state); }
      b.reply(choice, newer ? { ...state, canceled: true } : { supported: false });
      b.refresh(); b.reply(b.messages.at(-1), state);
      assert(!pick().disabled, "Completed native choice left Save-ACK slot stuck");
    });
    for (const scenario of ["accept", "save-failure", "book", "detached", "context", "missing-context"]) {
      await test(action + " original Save-ACK fence " + scenario, async b => {
        const state = { ...b.state, receive_consent: { ...b.state.receive_consent, granted: true } };
        b.refresh(); b.reply(b.messages.at(-1), state);
        if (scenario === "missing-context") {
          b.refresh(); b.reply(b.messages.at(-1), { ...state, destination_choices: null });
          assert(b.panel.querySelector(`[data-destination="images"][data-destination-action="${action}"]`).disabled); return;
        }
        b.refresh(); const statusRequest = b.messages.at(-1);
        b.panel.querySelector(`[data-destination="images"][data-destination-action="${action}"]`).click();
        assert.equal(b.messages.filter(m => m.action === action).length, 0);
        assert(b.add("images").disabled);
        if (scenario === "save-failure") b.fail();
        else {
          if (scenario === "book") b.changeBook();
          if (scenario === "detached") b.panel.remove();
          if (scenario === "context") b.reply(statusRequest, { ...state, destination_choices: { ...state.destination_choices, images: "9".repeat(64) } });
          b.save();
        }
        await tick(); const requests = b.messages.filter(m => m.action === action);
        assert.equal(requests.length, scenario === "accept" ? 1 : 0);
        if (requests.length) {
          assert.equal(requests[0].version, state.destination_choices.images);
          assert.notEqual(requests[0].version, state.pictures.version);
          assert.deepEqual(Object.keys(requests[0]).sort(), ["cmd", "requestId", "device_id", "action", "media_type", "version"].sort());
          b.reply(requests[0], { ...state, canceled: true }); assert(!b.add("images").disabled);
        }
        assert(!b.messages.some(m => ["sync", "sync_shared", "trash_preview", "trash_thumbnail"].includes(m.action)));
      });
    }
  }
  console.log(cases + " Windows source-folder frontend cases passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
