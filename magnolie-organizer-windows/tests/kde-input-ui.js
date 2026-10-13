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
    try {
      Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
      w.setTimeout = (fn, ms) => { timers.set(++sequence, { fn, ms }); return sequence; };
      w.clearTimeout = id => timers.delete(id); w.setInterval = () => 0;
      w.__MAGNOLIE_BRUECKE__ = "test";
      w.webkit = { messageHandlers: { test: { postMessage(value) {
        const message = typeof value === "string" ? JSON.parse(value) : value; sent.push(message);
        if (message.cmd === "kde_input_stand") queueMicrotask(() => w.App.kdeInput({ ...status, ok: true, requestId: message.requestId }));
        if (message.cmd === "kde_input_einstellungen") queueMicrotask(() => w.App.kdeInput({ ok: true, requestId: message.requestId }));
      } } } };
      w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
      w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
      w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
      w.App.init({ daten: {}, neu: false, regional: { language: "en" } });
      w.App.telefonStand({ peers: [], kdeconnect: { available: true, peer_id: phone.device_id } });
      w.document.querySelector("#einstellungen-schleier").classList.remove("verborgen");
      w.OrganizerTest.baueEinstellungen(); w.document.querySelector("#einst-tab-baum").click();
      const poll = () => {
        const timer = [...timers].find(([, value]) => value.fn.name === "pollInput");
        assert.ok(timer); timers.delete(timer[0]); timer[1].fn();
      };
      poll(); await flush();
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
