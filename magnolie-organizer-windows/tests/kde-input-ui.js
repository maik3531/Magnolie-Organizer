"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { JSDOM } = require("jsdom"), { webcrypto } = require("node:crypto");
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  for (const web of require("./web-test-roots")) {
    const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
      url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
    const w = dom.window, timers = new Map(), sent = [];
    let sequence = 0;
    const phone = { device_id: "a".repeat(32), device_name: "Phone" };
    let status = { native: false, receiver: { pointer: true, keyboard: true, enabled: true,
      ready: true, selected_device_id: "", devices: [phone] } };
    let media = { available: true, music: "music.desktop", video: "video.desktop", applications: [
      { id: "music.desktop", name: "Music fixture" }, { id: "video.desktop", name: "Video fixture" },
      { id: "iptv-recorder.desktop", name: "IPTV Recorder", slots: ["video"], can_open_files: false }] };
    try {
      Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
      w.setTimeout = (fn, ms) => { timers.set(++sequence, { fn, ms }); return sequence; };
      w.clearTimeout = id => timers.delete(id); w.setInterval = () => 0;
      w.__MAGNOLIE_BRUECKE__ = "test";
      w.webkit = { messageHandlers: { test: { postMessage(value) {
        const message = typeof value === "string" ? JSON.parse(value) : value; sent.push(message);
        if (message.cmd === "kde_input_stand") queueMicrotask(() => w.App.kdeInput({ ...status, ok: true, requestId: message.requestId }));
        if (message.cmd === "kde_input_einstellungen") queueMicrotask(() => w.App.kdeInput({ ok: true, requestId: message.requestId }));
        if (message.cmd === "kde_player_stand") queueMicrotask(() => w.App.kdePlayer({ ...media, ok: true, requestId: message.requestId }));
        if (message.cmd === "kde_player_titel") queueMicrotask(() => w.App.kdePlayer({ ok: true, available: !(message.slot === "video" && media.video === "iptv-recorder.desktop"),
          tracks: message.track ? [] : [{ id: "/fixture/" + message.slot, title: message.slot === "music" ? "Owned song" : "Owned film", artist: "Fixture artist" }],
          token: "a".repeat(64), requestId: message.requestId }));
        if (message.cmd === "kde_player_datei") queueMicrotask(() => w.App.kdePlayer({ ok: true, cancelled: true, requestId: message.requestId }));
        if (message.cmd === "kde_player_waehlen") {
          media = { ...media, [message.slot]: message.application };
          queueMicrotask(() => w.App.kdePlayer({ ...media, ok: true, requestId: message.requestId }));
        }
      } } } };
      w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
      w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
      w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
      w.App.init({ daten: {}, neu: false, regional: { language: "en" } });
      w.App.telefonStand({ peers: [], kdeconnect: { available: true, peer_id: phone.device_id } });
      w.document.querySelector("#einstellungen-schleier").classList.remove("verborgen");
       w.OrganizerTest.baueEinstellungen(); w.document.querySelector("#einst-tab-baum").click();
       const advanced = w.document.querySelector("#kde-erweiterte-funktionen");
       assert.ok(advanced && advanced.tagName === "DETAILS");
       assert.equal(advanced.open, false);
       assert.equal(advanced.querySelector("summary").textContent, "Advanced functions");
       assert.equal(w.document.querySelector("#kde-input").closest("details"), advanced);
       assert.equal(w.document.querySelector("#kde-local-players").closest("details"), advanced);
       advanced.open = true;
      const poll = () => {
        const timer = [...timers].find(([, value]) => value.fn.name === "pollInput");
        assert.ok(timer); timers.delete(timer[0]); timer[1].fn();
      };
      poll(); await flush();
      const loadPlayers = [...timers].find(([, value]) => value.fn.name === "load" && value.fn.toString().includes("kde_player_stand"));
      assert.ok(loadPlayers); timers.delete(loadPlayers[0]); loadPlayers[1].fn(); await flush();
      const players = w.document.querySelector("#kde-local-players");
      assert.equal(players.hidden, false);
      const music = players.querySelector('#kde-player-music'), video = players.querySelector('#kde-player-video');
      assert.equal(music.value, "music.desktop"); assert.equal(video.value, "video.desktop");
      assert.ok(![...music.options].some(option => option.value === "iptv-recorder.desktop"), "TV application appeared as an audio-player choice");
      assert.ok([...video.options].some(option => option.value === "iptv-recorder.desktop"));
      const libraries = players.querySelectorAll(".kde-medien-titel");
      assert.equal(libraries.length, 2);
      assert.equal(libraries[0].hidden, false); assert.equal(libraries[1].hidden, false);
      assert.equal(libraries[0].querySelector("option").textContent, "Owned song · Fixture artist");
      assert.equal(libraries[1].querySelector("option").textContent, "Owned film · Fixture artist");
      const search = libraries[0].querySelector('input[type="search"]');
      search.value = "unrelated"; search.dispatchEvent(new w.Event("input"));
      assert.equal(libraries[0].querySelectorAll("option").length, 0);
      assert.equal(libraries[1].querySelectorAll("option").length, 1, "Music search must not change video choices");
      search.value = "artist"; search.dispatchEvent(new w.Event("input"));
      libraries[0].querySelector("select").value = "/fixture/music";
      libraries[0].querySelector("select").dispatchEvent(new w.Event("change"));
      libraries[0].querySelector("button").click(); await flush();
      assert.equal(sent.findLast(value => value.cmd === "kde_player_titel").track, "/fixture/music");
      players.querySelector('[aria-label="Video player · Open"]').click(); await flush();
      assert.equal(sent.findLast(value => value.cmd === "kde_player_datei").slot, "video");
      music.value = ""; music.dispatchEvent(new w.Event("change")); await flush();
      assert.equal(sent.findLast(value => value.cmd === "kde_player_waehlen").slot, "music");
      assert.equal(sent.findLast(value => value.cmd === "kde_player_waehlen").application, "");
      assert.equal(video.value, "video.desktop", "Changing music overwrote video choice");
      video.value = "iptv-recorder.desktop"; video.dispatchEvent(new w.Event("change")); await flush();
      assert.equal(players.querySelector('[aria-label="Video player · Open"]').disabled, true, "TV application claimed unsupported local-file opening");
      assert.equal(libraries[1].hidden, true, "A TV application without a TrackList claimed searchable titles");
      const block = w.document.querySelector("#kde-input");
      assert.equal(block.hidden, false);
      assert.equal(w.document.querySelector("#kde-medien"), null, "Computer-to-phone media controls still displayed");
      assert.equal(block.querySelector('[aria-label="Remote control device"]'), null);
      assert.equal(block.querySelector('[aria-label="Keyboard text"]'), null);
      assert.equal(block.querySelector(".kde-touchpad"), null);
      const pause = block.querySelector('input[type="checkbox"]');
      pause.checked = true; pause.dispatchEvent(new w.Event("change")); await flush();
      assert.equal(sent.findLast(value => value.cmd === "kde_input_einstellungen").enabled, false);
      const receiver = block.querySelector('[aria-label="Incoming control device"]');
      receiver.value = phone.device_id; receiver.dispatchEvent(new w.Event("change")); await flush();
      assert.equal(sent.findLast(value => value.cmd === "kde_input_einstellungen").device_id, phone.device_id);
      status = { native: false, receiver: { pointer: false, keyboard: false } }; poll(); await flush();
      assert.equal(block.hidden, true, "Unsupported input module displayed");
      status = { native: true, receiver: { system_managed: true, available: false } }; poll(); await flush();
      assert.equal(block.hidden, true, "Unavailable system plugin displayed");
      status = { native: true, receiver: { system_managed: true, available: true } }; poll(); await flush();
      assert.equal(block.hidden, false); assert.equal(pause.parentElement.hidden, true);
      assert.equal(receiver.hidden, true, "Native system permissions exposed a custom selector");
      assert.equal(sent.some(value => value.cmd === "kde_input_senden" || value.cmd.startsWith("kde_medien_")), false);
      const count = sent.length; w.document.querySelector("#einstellungen-schleier").classList.add("verborgen");
      poll(); await flush(); assert.equal(sent.length, count);
      w.App.telefonStand({ enabled: true, listening: true, peers: [{ device_id: phone.device_id,
        display_name: "Notes fixture", fingerprint: "fixture", state: "paired" }],
        kdeconnect: { available: true, peer_id: phone.device_id } });
      w.OrganizerTest.baueEinstellungen();
      const notes = w.document.querySelector(".telefon-karte");
      const renew = [...notes.querySelectorAll("button")].find(value => value.textContent === "Renew pairing");
      assert.ok(renew && !renew.disabled, "Known Notes phone cannot be confirmed again without removal");
      renew.click(); assert.equal(sent.at(-1).cmd, "telefon_pairing_oeffnen");
      console.log("KDE incoming-only DOM PASS: " + web);
    } finally { dom.window.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
