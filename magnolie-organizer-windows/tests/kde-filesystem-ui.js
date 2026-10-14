"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web);
    try {
      const device = { device_id: "a".repeat(32), device_name: "Handy <Fixture>", token: "b".repeat(32), available: true, transport: "wifi" };
      let block;
      const stand = devices => {
        b.w.App.telefonStand({ peers: [], kdeconnect: { available: false, filesystem: { devices } } });
        block = b.w.document.querySelector("#kde-dateisystem");
      };
      stand([]); b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-baum").click();
      block = b.w.document.querySelector("#kde-dateisystem");
      assert.ok(block && block.hidden && !block.querySelector("button"));
      stand([{ ...device, transport: "bluetooth" }]); assert.equal(block.hidden, true);
      stand([{ ...device, available: false }]); assert.equal(block.hidden, true);
      stand([device]); assert.equal(block.hidden, false);
      assert.equal(block.querySelector("button").textContent, "Handy <Fixture> filesystem");
      assert.equal(block.querySelector("Fixture"), null, "Phone name was interpreted as HTML");
      block.querySelector("button").click();
      const request = b.messages.filter(value => value.cmd === "kde_dateisystem_oeffnen").at(-1);
      assert.equal(request.device_id, device.device_id); assert.equal(request.token, device.token);
      assert.equal("uri" in request, false); assert.equal("password" in request, false);
      assert.equal(block.querySelector("button").disabled, true);
      stand([{ ...device, token: "c".repeat(32) }]);
      b.w.App.kdeMedien({ ok: true, requestId: request.requestId, state: "opened", device_id: device.device_id });
      await flush();
      assert.equal(block.querySelector("button").disabled, false, "Completed old request left current source disabled");
      stand([]); assert.equal(block.hidden, true); assert.equal(block.querySelector("button"), null);
      assert.equal(JSON.stringify(b.t.daten()).includes('"token":"cccc'), false);
      console.log("KDE filesystem name, WLAN-only visibility, source binding and disconnect removal: PASS " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
