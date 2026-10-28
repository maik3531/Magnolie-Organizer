"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { einstellungen: { allgemein: { tray: { aktiv: true, autostart: false, zaehler: true, oeffnen: "centered" } } } });
    try {
      b.t.oeffneEinstellungen();
      const group = b.w.document.querySelector("#allgemein-gruppe-tray");
      assert.ok(group && !group.open, "Tray group must remain initially collapsed");
      const row = group.querySelector(".allgemein-tray-hauptzeile");
      assert.equal(row.querySelectorAll("label.hak").length, 2);
      assert.ok(row.contains(group.querySelector("#allgemein-tray-aktiv")) && row.contains(group.querySelector("#allgemein-tray-autostart")));
      const option = group.querySelector("#allgemein-tray-telefon-verbinden");
      assert.ok(option && option.checked, "Legacy defaults lost the existing phone action");
      option.checked = false; option.dispatchEvent(new b.w.Event("change", { bubbles: true }));
      assert.equal(b.t.daten().einstellungen.allgemein.tray.telefonWlanVerbinden, false);
      assert.equal(b.t.daten().einstellungen.allgemein.tray.zaehler, true);
      assert.equal(b.t.daten().einstellungen.allgemein.tray.oeffnen, "centered");
      assert.equal(b.messages.filter(message => message.cmd === "tray_einstellungen").at(-1).einstellungen.telefonWlanVerbinden, false);
      b.t.speichereJetzt();
      assert.equal(JSON.parse(b.saves().at(-1).text).einstellungen.allgemein.tray.telefonWlanVerbinden, false); b.ack();
      const autostart = group.querySelector("#allgemein-tray-autostart");
      autostart.checked = true; autostart.dispatchEvent(new b.w.Event("change", { bubbles: true }));
      assert.equal(b.t.daten().einstellungen.allgemein.tray.telefonWlanVerbinden, false);
      assert.equal(b.t.daten().einstellungen.allgemein.tray.startMinimiert, true);
      console.log("TRAY PHONE UI PASS: default, persisted opt-out, native mapping, retained preferences and spaced row " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
