"use strict";
// #488: actual Linux frontend/bridge, no installed GTK acceptance claim.
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const web = path.resolve(__dirname, "../web");
const tick = () => new Promise(resolve => setImmediate(resolve));
async function boot() {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://source-choice.invalid/", pretendToBeVisual: true
  });
  const w = dom.window, messages = [], timers = [];
  w.setTimeout = (fn, delay) => { const t = { fn, delay }; timers.push(t); return t; };
  w.clearTimeout = t => { if (t) t.canceled = true; };
  w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.__MAGNOLIE_BRUECKE__ = "source";
  w.webkit = { messageHandlers: { source: { postMessage: text => messages.push(JSON.parse(text)) } } };
  for (const file of ["i18n.js", "zeichenblatt.js", "anwendung.js"]) w.eval(fs.readFileSync(path.join(web, file), "utf8"));
  await tick(); w.App.init({ daten: {}, neu: false, regional: { language: "en", timeZone: "UTC" } });
  w.OrganizerTest.oeffneEinstellungen();
  [...w.document.querySelectorAll(".einst-reiter-knopf")].find(b => b.textContent === "Magnolia tree").click();
  const values = { enabled: true, photos_enabled: true, videos_enabled: true, collection_mode: "entire_collection",
    direction: "pc_to_phone", auto_mode: "manual", skip_deletions: false, photos_only: false };
  const state = { available: true, enabled: false, state: "off", albums: [], video_supported: true,
    collection_sources_supported: true, sending_consent: { version: "b".repeat(64), photos: true, videos: true },
    shared_media: { version: "a".repeat(64), agreed: true, configured: true, values },
    collection_sources: { version: "c".repeat(64), roots: [{ id: "root", media_type: "images", display_path: "/private/source" }] } };
  function show(changes = {}, peerChanges = {}) {
    w.App.telefonStand({ enabled: true, peers: [{ device_id: "phone", fingerprint: "original", own_device: true,
      remote_own_device: true, transport: "wifi", ...peerChanges, photo_sync: { ...state, ...changes } }] });
  }
  show();
  return { dom, w, messages, state, show, add: () => w.document.querySelector('[data-collection-source-add="images"]'),
    sent: () => messages.filter(m => m.cmd === "telefon_sammlungsordner"),
    async ack(ok = true) { await tick(); const save = messages.filter(m => m.cmd === "speichern").at(-1);
      if (save) w.App.gespeichert({ id: save.id, ok }); await tick(); },
    reply(request, ok = true) { w.App.telefonFotoErgebnis({ device_id: "phone", requestId: request.requestId, ok }); } };
}
(async () => {
  let cases = 0;
  async function test(name, fn) { const b = await boot(); try { await fn(b); cases++; }
    catch (error) { error.message = name + ": " + error.message; throw error; } finally { b.dom.window.close(); } }
  await test("native selection waits for actual save ACK and keeps paths tooltip-only", async b => {
    assert.ok(b.add() && !b.add().disabled);
    const section = b.w.document.querySelector(".notes-pc-sammlungsordner");
    assert.ok(!section.textContent.includes("/private/source") && section.querySelector('[title="/private/source"]'));
    b.add().click(); assert.equal(b.sent().length, 0); await b.ack();
    assert.equal(b.sent().length, 1); const request = b.sent()[0];
    assert.deepEqual(Object.keys(request).sort(), ["cmd", "kennung", "fingerprint", "media_type", "action", "version", "requestId"].sort());
    assert.equal(request.action, "choose"); assert.equal(request.version, "a".repeat(64));
    assert.ok(b.add().disabled && b.w.document.querySelector('[data-media-send="photos"]').disabled);
    b.reply({ requestId: "foreign" }); assert.ok(b.add().disabled);
    b.reply(request); assert.ok(!b.add().disabled);
    assert.ok(!b.messages.some(m => m.request?.action?.includes("preview") || m.request?.action === "sync"));
  });
  for (const [name, changes] of [["import only", { collection_mode: "import_only" }], ["receive only", { direction: "phone_to_pc" }]]) {
    await test(name + " never offers export roots", async b => {
      b.show({ shared_media: { ...b.state.shared_media, values: { ...b.state.shared_media.values, ...changes } } });
      assert.equal(b.add(), null); assert.equal(b.sent().length, 0);
    });
  }
  for (const name of ["settings", "fingerprint", "book", "save failure"]) {
    await test("stale " + name + " cannot dispatch after save", async b => {
      b.add().click();
      if (name === "settings") b.show({ shared_media: { ...b.state.shared_media, version: "d".repeat(64) } });
      if (name === "fingerprint") b.show({}, { fingerprint: "replacement" });
      if (name === "book") b.w.App.init({ daten: { notizen: [{ id: "other", titel: "Other" }] }, neu: false });
      await b.ack(name !== "save failure"); assert.equal(b.sent().length, 0);
    });
  }
  await test("missing native support or send consent cannot choose sources", async b => {
    b.show({ collection_sources_supported: false }); assert.equal(b.add(), null);
    b.show({ sending_consent: { ...b.state.sending_consent, photos: false } }); assert.ok(b.add().disabled);
  });
  await test("read is independent of send consent and old replies cannot clear the next choice", async b => {
    b.show({ sending_consent: { ...b.state.sending_consent, photos: false } });
    b.w.document.querySelector('[data-collection-source-read="images"]').click(); await b.ack();
    const first = b.sent().at(-1); assert.equal(first.action, "read"); b.reply(first);
    b.show(); b.add().click(); await b.ack(); const second = b.sent().at(-1);
    assert.notEqual(first.requestId, second.requestId); b.reply(first); assert.ok(b.add().disabled);
    b.reply(second); assert.ok(!b.add().disabled);
    assert.equal(b.w.document.querySelector('[data-media-setting="auto_mode"]').value, "manual");
  });
  await test("shared OFF and nonagreed settings keep source choice disabled", async b => {
    b.show({ shared_media: { ...b.state.shared_media, agreed: false } }); assert.ok(b.add().disabled);
    b.show({ shared_media: { ...b.state.shared_media, values: { ...b.state.shared_media.values, enabled: false } } });
    assert.ok(b.add().disabled); assert.equal(b.sent().length, 0);
  });
  console.log(cases + " Linux source-folder UI cases passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
