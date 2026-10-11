"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);

(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { notizen: [
      { id: "older", titel: "Older note", text: "Keep this text", angelegt: Date.UTC(2026, 0, 2), geaendert: "2026-01-03",
        zusammenfuehrungen: [{ id: "original", angelegt: Date.UTC(2025, 11, 1), geaendert: "2025-12-02", zeitpunkt: Date.UTC(2026, 0, 2), art: "sync" }] },
      { id: "newer", titel: "Newer note", text: "Other text", angelegt: Date.UTC(2026, 0, 4), geaendert: "2026-01-04" }
    ] });
    try {
      await b.t.wechsel("notizen");
      const findButton = (root, label) => [...root.querySelectorAll("button")].find(button => button.textContent.replace(/^✓ /, "") === label);
      const menu = id => {
        const row = b.w.document.querySelector(`[data-notiz-id="${id}"]`);
        assert.ok(row); row.dispatchEvent(new b.w.MouseEvent("contextmenu", { bubbles: true, clientX: 10, clientY: 10 }));
        return b.w.document.querySelector("#vorschlags-menue");
      };
      findButton(menu("older"), "Properties").click();
      const properties = b.w.document.querySelector(".notiz-eigenschaften");
      assert.ok(properties); assert.match(properties.textContent, /2025/); assert.match(properties.textContent, /2026/);
      findButton(properties, "Close").click();
      findButton(menu("older"), "Newest first").click();
      assert.deepEqual([...b.w.document.querySelectorAll("[data-notiz-id]")].map(row => row.dataset.notizId), ["newer", "older"]);
      findButton(menu("older"), "Group by day").click();
      assert.equal(b.t.daten().einstellungen.notizUebersicht.view, "days");
      assert.equal(b.t.normalisiere(b.t.daten()).einstellungen.notizUebersicht.sort, "created_desc");
      assert.equal(b.t.daten().notizen.find(note => note.id === "older").text, "Keep this text");

      const peer = { device_id: "22222222-2222-4222-8222-222222222222", fingerprint: "test-pair", state: "online_wifi",
        own_device: true, remote_own_device: true, capabilities: { items: {} }, local_grants: { grants: {} }, grants: { grants: {} },
        shared_sync: { supported: true, initialized: true, ready: true, values: { content_mode: "phone_scope", auto_mode: "manual",
          skip_deletions: true, custom_enabled: false, time_enabled: false, time_mode: "phone_import" } } };
      b.w.App.telefonStand({ peers: [peer] });
      assert.ok(findButton(menu("older"), "Send to Notes"));
      b.w.document.querySelector("#vorschlags-menue").remove();
      for (let attempt = 0; attempt < 2; attempt++) {
        findButton(b.w.document.querySelector("#kopf-links"), "New page").click();
        const dialog = b.w.document.querySelector(".eingabe-dialog"), checkbox = dialog.querySelector('input[type="checkbox"]');
        assert.ok(checkbox); assert.equal(checkbox.checked, false); assert.equal(checkbox.disabled, false);
        checkbox.checked = true; findButton(dialog, "Cancel").click();
      }
      peer.shared_sync.values.content_mode = "two_way";
      b.w.App.telefonStand({ peers: [peer] });
      assert.equal(findButton(menu("older"), "Send to Notes"), undefined);
      console.log("Notizansicht, Eigenschaften und Einzelversand-Bedienung bestanden:", web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
