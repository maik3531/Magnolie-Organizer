"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { JSDOM } = require("jsdom"), { webcrypto } = require("node:crypto");
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  for (const web of require("./web-test-roots")) {
    const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
      url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
    const w = dom.window, timers = new Map(), sent = [];
    let sequence = 0, devices = [{ device_id: "a".repeat(32), device_name: "Test phone" }], held = null;
    try {
      Object.defineProperty(w, "crypto", { value: webcrypto });
      w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
      w.setTimeout = (fn, ms) => { timers.set(++sequence, { fn, ms }); return sequence; };
      w.clearTimeout = id => timers.delete(id); w.setInterval = () => 0;
      w.__MAGNOLIE_BRUECKE__ = "test";
      w.webkit = { messageHandlers: { test: { postMessage(value) {
        const message = typeof value === "string" ? JSON.parse(value) : value;
        sent.push(message);
        let result;
        if (message.cmd === "kde_medien_geraete") result = { devices };
        if (message.cmd === "kde_medien_stand") result = { device_id: message.device_id, token: "b".repeat(32), ready: true,
          players: [{ player: "Music", title: "<img src=x onerror=alert(1)>", artist: "Fixture", volume: 50,
            canGoNext: false, canSeek: true, length: 20000, pos: 1000 }] };
        if (message.cmd === "kde_medien_aktion") { held = message; return; }
        if (result) queueMicrotask(() => w.App.kdeMedien({ ...result, ok: true, requestId: message.requestId }));
      } } } };
      w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
      w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
      w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
      w.App.init({ daten: {}, neu: false, regional: { language: "en" } });
      w.App.telefonStand({ peers: [], kdeconnect: { available: true, device_id: "a".repeat(32), peer_id: "a".repeat(32) } });
      w.document.querySelector("#einstellungen-schleier").classList.remove("verborgen");
      w.OrganizerTest.baueEinstellungen(); w.document.querySelector("#einst-tab-baum").click();
      const poll = () => {
        const timer = [...timers].find(([, value]) => value.fn.name === "poll");
        assert.ok(timer, "Automatic media poll missing"); timers.delete(timer[0]); timer[1].fn();
      };
      poll(); await flush();
      const block = w.document.querySelector("#kde-medien"); assert.ok(block);
      const button = name => [...block.querySelectorAll("button")].find(p => p.textContent === name);
      assert.equal(button("Play").disabled, false); assert.equal(button("Next").disabled, true);
      assert.equal(block.querySelector("img"), null, "Remote title interpreted as markup");
      assert.ok(block.textContent.includes("<img src=x"));
      button("Play").click(); button("Play").click();
      assert.equal(sent.filter(p => p.cmd === "kde_medien_aktion").length, 1, "Busy action was repeated");
      assert.equal(held.player, "Music"); assert.equal(held.token, "b".repeat(32));
      w.App.kdeMedien({ ok: true, requestId: held.requestId, state: "queued" }); await flush();
      const position = block.querySelector('[aria-label="Playback position"]');
      position.value = "5000"; position.dispatchEvent(new w.Event("change"));
      assert.equal(held.value, 5000); assert.equal(held.action, "position");
      w.App.kdeMedien({ ok: false, requestId: held.requestId }); await flush();
      assert.equal(button("Play").disabled, true, "Failed command left stale state actionable");
      devices = []; poll(); await flush();
      assert.equal(button("Play").disabled, true); assert.equal(block.querySelector("select").options.length, 0);
      const count = sent.length;
      w.document.querySelector("#einstellungen-schleier").classList.add("verborgen"); poll(); await flush();
      assert.equal(sent.length, count, "Hidden settings kept polling the transport");
      console.log("KDE media DOM PASS: " + web);
    } finally { dom.window.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
