"use strict";

// Existing isolated full frontends only: no service, permission, file or worker
// starts here. Native session/IPC/bytes have their separate Python proofs.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), vm = require("node:vm");
const assert = require("node:assert/strict");
const harnessPath = path.resolve(__dirname, "../../magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harness = new Module(harnessPath, module);
harness.filename = harnessPath; harness.paths = Module._nodeModulePaths(path.dirname(harnessPath));
harness._compile(fs.readFileSync(harnessPath, "utf8").split("async function run(web)")[0] +
  "\nmodule.exports = {boot, roots};", harnessPath);
const linuxWeb = path.resolve(__dirname, "../web");
const phoneId = "11111111-1111-4111-8111-111111111111";
const locales = fs.readFileSync(path.resolve(__dirname, "../po/LINGUAS"), "utf8").split(/\s+/).filter(Boolean);
for (const locale of locales) {
  let catalog;
  vm.runInNewContext(fs.readFileSync(path.join(linuxWeb, "i18n", locale + ".js"), "utf8"), {
    window: { MagnolieI18n: { registerCatalog: (_, value) => { catalog = value; } } }
  });
  for (const key of ["Also synchronize videos", "Allow video access on phone"])
    assert.ok(typeof catalog?.messages[key] === "string" && catalog.messages[key].trim(), `${locale}: missing ${key}`);
}

(async () => {
  let passed = 0;
  for (const web of harness.exports.roots) for (const locale of ["en", "de"]) {
    const b = await harness.exports.boot(web, { notizen: [{ id: "keep", titel: "Keep", text: "Do not change", html: "Do not change" }],
      einstellungen: { adressen: { kommunikation: { anruf: { telefonId: phoneId } } } } });
    try {
      if (locale === "de") {
        b.w.eval(fs.readFileSync(path.join(web, "i18n/de.js"), "utf8")); b.w.MagnolieI18n.setLocale("de");
      }
      const before = JSON.stringify(b.t.daten());
      b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-baum").click();
      const peer = { device_id: phoneId, fingerprint: "AAAA-BBBB", display_name: "Notes phone",
        own_device: true, remote_own_device: true, transport: "wifi", state: "online_wifi" };
      const imageAlbums = [{ album_id: "same-id", display_name: "Photos", visible_images: 2 }];
      const stand = { available: true, enabled: true, state: "albums", mode: "manual", automatic_supported: true,
        destination: "/native/Pictures/Phone-Fotos", albums: imageAlbums };
      const render = (extra = {}, peerExtra = {}) => b.w.App.telefonStand({ enabled: true, listening: true,
        peers: [{ ...peer, ...peerExtra, photo_sync: { ...stand, ...extra } }], bluetooth: { available: false, devices: [] },
        kdeconnect: { available: false, paired: false, reason: "no_device" } });
      const d = b.w.document;
      const video = () => d.querySelector(".notes-video-sync");
      const actions = () => b.messages.filter(message => message.cmd === "telefon_foto_aktion");
      render({ video_supported: true, video_enabled: false });
      if (path.resolve(web) !== linuxWeb) {
        assert.equal(video(), null, "An unsupported platform must not gain media controls by a copied frontend");
        assert.equal(actions().length, 0);
        passed++; continue;
      }
      const group = d.querySelector(".notes-erweiterte-funktionen");
      assert.ok(group && video() && d.querySelector(".telefon-karte").contains(group));
      assert.equal(d.querySelector(".telefon-kde-karte .notes-video-sync"), null);
      assert.equal(actions().length, 0, "Rendering native OFF must not enable videos or start I/O");
      assert.ok(!video().querySelector("[data-video-enabled]").checked);
      assert.equal(video().querySelector("[data-video-action]"), null, "OFF must not offer read/sync");
      assert.ok(video().textContent.includes(locale === "de" ? "Auch Videos synchronisieren" : "Also synchronize videos"));
      const choose = video().querySelector("[data-video-destination]"); assert.ok(choose && !choose.disabled);
      choose.click();
      assert.deepEqual(JSON.parse(JSON.stringify(b.messages.at(-1))), { cmd: "telefon_videoziel_waehlen", kennung: peer.device_id,
        fingerprint: peer.fingerprint }, "Web UI must request the native picker, never submit a path");
      const toggle = video().querySelector("[data-video-enabled]");
      toggle.checked = true; toggle.dispatchEvent(new b.w.Event("change", { bubbles: true }));
      assert.deepEqual(JSON.parse(JSON.stringify(actions().at(-1))), { cmd: "telefon_foto_aktion", kennung: peer.device_id,
        fingerprint: peer.fingerprint, request: { action: "videos_enable" } });
      const enabled = { video_supported: true, video_enabled: true, video_destination: "/native/Videos/Phone-Videos",
        video_albums: [{ album_id: "same-id", display_name: "Videos", visible_images: 3 },
          { album_id: "video-second", display_name: "<img src=x onerror=bad>", visible_images: 1 }] };
      render(enabled);
      assert.ok(video().textContent.includes(enabled.video_destination) && !video().querySelector("img"));
      assert.ok(video().querySelector("[data-video-destination]").disabled, "Live video scope cannot be redirected");
      assert.equal(d.querySelector("select[data-photo-mode]").value, "manual");
      video().querySelector("[data-video-action='read']").click();
      assert.deepEqual(JSON.parse(JSON.stringify(actions().at(-1).request)), { action: "videos_request_read" });
      video().querySelector("[data-video-action='discover']").click();
      assert.deepEqual(JSON.parse(JSON.stringify(actions().at(-1).request)), { action: "videos_discover" });
      d.querySelector("[data-photo-album]").value = "same-id";
      video().querySelector("[data-video-album]").value = "video-second";
      render(enabled);
      assert.equal(d.querySelector("[data-photo-album]").value, "same-id");
      assert.equal(video().querySelector("[data-video-album]").value, "video-second");
      video().querySelector("[data-video-action='sync']").click();
      assert.deepEqual(JSON.parse(JSON.stringify(actions().at(-1).request)), { action: "videos_sync", album_id: "video-second" });
      render({ ...enabled, busy: true, state: "syncing", active_media: "video" });
      assert.ok([...video().querySelectorAll("button")].every(button => button.disabled));
      assert.ok(!video().querySelector("[data-video-enabled]").disabled, "A running transfer must allow explicit OFF");
      assert.ok(!d.querySelector(".notes-foto-sync").textContent.includes(locale === "de" ? "Fotoabgleich aktiv" : "Photo synchronization active"));
      const off = video().querySelector("[data-video-enabled]"); off.checked = false;
      off.dispatchEvent(new b.w.Event("change", { bubbles: true }));
      assert.deepEqual(JSON.parse(JSON.stringify(actions().at(-1).request)), { action: "videos_disable" });
      render({ video_supported: true, video_enabled: false, busy: true });
      assert.ok(video().querySelector("[data-video-enabled]").disabled, "Busy must not enable a second media lane");
      assert.ok(video().querySelector("[data-video-destination]").disabled, "Busy must not select a target");
      render({ video_supported: true, video_enabled: false, video_destination: enabled.video_destination });
      assert.ok(video().textContent.includes(enabled.video_destination), "OFF must preserve/display the chosen target");
      render({ ...enabled, video_albums: [] });
      assert.ok(video().querySelector("[data-video-action='sync']").disabled);
      const count = actions().length;
      render({ ...enabled, video_supported: false }); assert.equal(video(), null);
      render({ ...enabled, enabled: false }); assert.equal(video(), null);
      render(enabled, { transport: "", state: "offline" }); assert.equal(video(), null);
      assert.equal(actions().length, count, "Capability/offline/status updates must not dispatch actions");
      assert.ok(JSON.stringify(b.t.daten()) === before, "Media UI rendering changed saved user data or grants");
      passed++;
    } finally { b.close(); }
  }
  console.log(`Video advanced UI: ${passed} frontend/locale cases passed; ${locales.length} generated catalogs checked. Installed/native GUI acceptance is separate.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
