"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web);
    try {
      b.t.oeffneEinstellungen();
      b.w.document.querySelector("#einst-tab-erinnerung").click();
      assert.equal(b.w.document.querySelector("#erinnerung-protokoll-an"), null);
      assert.equal(b.w.document.querySelector("#erinnerung-protokoll"), null);
      assert.equal(b.w.document.querySelector("#einst-tab-entwickler"), null);
      b.w.document.querySelector("#einst-tab-ueber").click();
      const version = b.w.document.querySelector("#entwickler-version");
      assert.ok(version.textContent.includes("Version"));
      for (let n = 0; n < 9; n++) version.click();
      assert.equal(b.w.document.querySelector("#einst-tab-entwickler"), null);
      version.click();
      assert.equal(b.t.daten().einstellungen.allgemein.entwicklermodus, true);
      assert.equal(b.t.normalisiere(b.t.daten()).einstellungen.allgemein.entwicklermodus, true);
      assert.ok(b.w.document.querySelector("#einst-tab-entwickler"));
      assert.ok(b.w.document.querySelector("#erinnerung-protokoll-an"));
      const peer = { device_id: "22222222-2222-4222-8222-222222222222", fingerprint: "fixture-key",
        state: "online_wifi", own_device: true, remote_own_device: true };
      const read = b.w.document.querySelector("#entwickler-wlan-lesen");
      assert.equal(read.disabled, true);
      b.w.App.telefonStand({ peers: [peer] });
      assert.equal(read.disabled, false); read.click();
      let request = b.messages.filter(message => message.cmd === "telefon_entwickler_diagnose").at(-1);
      assert.equal(request.kennung, peer.device_id);
      b.w.App.telefonEntwicklerDiagnose({ requestId: "wrong", kennung: peer.device_id, ok: true, diagnose: { app_version: "ignored" } });
      const output = b.w.document.querySelector("#entwickler-wlan-diagnose");
      assert.equal(output.textContent, "");
      b.w.App.telefonEntwicklerDiagnose({ requestId: request.requestId, kennung: peer.device_id, ok: true,
        diagnose: { format: 1, app_version: "fixture", events: [] } });
      assert.match(output.textContent, /fixture/); assert.equal(read.disabled, false);
      assert.equal(JSON.stringify(b.t.daten()).includes('"app_version":"fixture"'), false);
      read.click(); request = b.messages.filter(message => message.cmd === "telefon_entwickler_diagnose").at(-1);
      b.w.App.telefonStand({ peers: [{ ...peer, fingerprint: "new-key" }] });
      assert.equal(output.textContent, "");
      b.w.App.telefonEntwicklerDiagnose({ requestId: request.requestId, kennung: peer.device_id, ok: true,
        diagnose: { app_version: "late old-key" } });
      assert.equal(output.textContent, "");
      b.w.App.telefonStand({ peers: [{ ...peer, state: "online_bluetooth" }] });
      assert.equal(read.disabled, true);
      const disable = [...b.w.document.querySelectorAll("#einst-seite-entwickler button")].find(button => button.textContent === "Disable developer mode");
      assert.ok(disable); disable.click();
      assert.equal(b.t.daten().einstellungen.allgemein.entwicklermodus, false);
      assert.equal(b.t.daten().einstellungen.erinnerung.protokoll, false);
      assert.equal(b.w.document.querySelector("#einst-tab-entwickler"), null);
      const newVersion = b.w.document.querySelector("#entwickler-version");
      for (let n = 0; n < 9; n++) newVersion.click();
      assert.equal(b.w.document.querySelector("#einst-tab-entwickler"), null);
      console.log("Developer mode 9/10 clicks, notifications cleanup, persistent choice and disable: PASS " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
