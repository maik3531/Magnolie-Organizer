"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { JSDOM } = require("jsdom"), { webcrypto } = require("node:crypto");
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  for (const web of require("./web-test-roots")) {
    const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
      url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
    const w = dom.window, timers = new Map(), sent = [];
    let sequence = 0, pending = null;
    const phone = { device_id: "a".repeat(32), device_name: "Phone", token: "b".repeat(32), pointer: false, keyboard: true };
    const desktop = { device_id: "c".repeat(32), device_name: "Desktop", token: "d".repeat(32), pointer: true, keyboard: true };
    let status = { native: false, devices: [phone, desktop], receiver: { pointer: true, keyboard: true,
      enabled: true, ready: true, selected_device_id: "", devices: [phone, desktop] } };
    try {
      Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
      w.setTimeout = (fn, ms) => { timers.set(++sequence, { fn, ms }); return sequence; };
      w.clearTimeout = id => timers.delete(id); w.setInterval = () => 0;
      w.__MAGNOLIE_BRUECKE__ = "test";
      w.webkit = { messageHandlers: { test: { postMessage(value) {
        const message = typeof value === "string" ? JSON.parse(value) : value; sent.push(message);
        if (message.cmd === "kde_input_stand") queueMicrotask(() => w.App.kdeInput({ ...status, ok: true, requestId: message.requestId }));
        if (message.cmd === "kde_input_senden") pending = message;
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
      const block = w.document.querySelector("#kde-input"), select = block.querySelector('[aria-label="Remote control device"]');
      const button = name => [...block.querySelectorAll("button")].find(value => value.textContent === name);
      assert.equal(button("Click").disabled, true, "Phone keyboard support was mistaken for pointer support");
      assert.equal(button("Send text").disabled, false);
      const text = block.querySelector('[aria-label="Keyboard text"]'); text.value = "ä😀";
      button("Send text").click(); button("Send text").click();
      assert.equal(sent.filter(value => value.cmd === "kde_input_senden").length, 1);
      assert.equal(pending.body.key, "ä😀"); assert.equal(pending.device_id, phone.device_id);
      w.App.kdeInput({ ok: true, requestId: pending.requestId }); await flush(); assert.equal(text.value, "");
      select.value = desktop.device_id; select.dispatchEvent(new w.Event("change"));
      assert.equal(button("Click").disabled, false); button("Click").click();
      assert.equal(pending.body.singleclick, true); assert.equal(pending.device_id, desktop.device_id);
      const old = pending;
      select.value = phone.device_id; select.dispatchEvent(new w.Event("change"));
      w.App.kdeInput({ ok: false, requestId: old.requestId }); await flush();
      assert.equal(button("Send text").disabled, false, "Late previous-device failure disabled the new target");
      const pause = block.querySelector('input[type="checkbox"]'); pause.checked = true; pause.dispatchEvent(new w.Event("change"));
      const configuration = sent.findLast(value => value.cmd === "kde_input_einstellungen");
      assert.equal(configuration.enabled, false); await flush();
      status = { ...status, native: true, receiver: { system_managed: true, ready: null } };
      poll(); await flush(); assert.equal(pause.parentElement.hidden, true, "System-managed KDE permissions exposed a custom receiver switch");
      status = { native: false, devices: [], receiver: {} }; poll(); await flush();
      assert.equal(button("Send text").disabled, true);
      const count = sent.length; w.document.querySelector("#einstellungen-schleier").classList.add("verborgen");
      poll(); await flush(); assert.equal(sent.length, count, "Hidden input controls continued polling");
      console.log("KDE input DOM PASS: " + web);
    } finally { dom.window.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
