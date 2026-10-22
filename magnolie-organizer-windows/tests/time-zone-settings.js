"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(file, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "baueSeiteRegional, mcpRegionaleEinstellungenWerkzeuge, icsExpansion, speichereJetzt: speichereJetzt,"));');
harness._compile(source + "\nmodule.exports={boot,roots};", file);
async function until(predicate) { for (let n = 0; n < 100; n++) { if (predicate()) return; await new Promise(setImmediate); } throw new Error("Expected timezone transaction phase was not reached"); }
const watchdog = setTimeout(() => { console.error("Time-zone transaction timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) for (const scenario of ["mcp", "failed-save", "source-changed", "gui"]) {
    const failedSave = scenario === "failed-save";
    const b = await harness.exports.boot(web, { termine: [{ id: "anchor", datum: "2026-10-21", zeit: "23:30", endZeit: "23:45", titel: "Keep instant" }] });
    try {
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      b.t.speichereJetzt(); if (b.saves().length) b.ack();
      let native = JSON.parse(JSON.stringify(b.t.daten().einstellungen.regional)), writes = 0;
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "regional_einstellungen_status") queueMicrotask(() => b.w.App.regionalStand({ requestId: message.requestId, ok: true, regional: native }));
        if (message.cmd === "regional_einstellungen") {
          writes++; assert.equal(native.timeZone, "UTC");
          assert.equal(message.expectedRegional.timeZone, "UTC");
          native = JSON.parse(JSON.stringify(message.regional));
          queueMicrotask(() => b.w.App.regionalErgebnis({ requestId: message.requestId, ok: true, regional: native }));
        }
      };
      const [read, update] = b.t.mcpRegionaleEinstellungenWerkzeuge(), signal = new AbortController().signal;
      const before = await read.call({}, signal), initialSaves = b.saves().length;
      let result, button;
      if (scenario === "gui") {
        const root = b.w.document.createElement("div"); b.w.document.body.append(root); b.t.baueSeiteRegional(root);
        root.querySelector("#regional-zeitzone").value = "Europe/Berlin";
        button = root.querySelector("#regional-speichern"); button.click();
      } else result = update.call({ expected_revision: before.revision, time_zone: "Europe/Berlin" }, signal).then(value => ({ value }), error => ({ error }));
      await until(() => b.saves().length > initialSaves);
      assert.equal(writes, 0, "Native timezone must remain unchanged until anchor SaveACK");
      assert.equal(native.timeZone, "UTC");
      const entry = b.t.daten().termine.find(item => item.id === "anchor");
      assert.ok(entry.icsRoundtrip.includes("DTSTART;TZID=UTC:20261021T233000"));
      if (scenario === "source-changed") entry.titel = "Concurrent edit retained";
      b.ack(!failedSave);
      if (failedSave || scenario === "source-changed") {
        const outcome = await result; assert.equal(outcome.error?.code, failedSave ? "save_failed" : "source_changed"); assert.equal(writes, 0);
        assert.equal(native.timeZone, "UTC");
        if (scenario === "source-changed") assert.equal(entry.titel, "Concurrent edit retained");
      } else {
        await until(() => writes === 1 && b.saves().length > initialSaves + 1);
        b.ack();
        if (scenario === "gui") await until(() => !button.disabled && b.w.document.querySelector("#zettel").textContent.includes("Regional settings saved"));
        else { const outcome = await result; assert.ok(!outcome.error, String(outcome.error)); assert.equal(outcome.value.persisted, true); }
        assert.equal(native.timeZone, "Europe/Berlin");
        const occurrences = b.t.icsExpansion(entry, Date.parse("2026-10-21T00:00Z"), Date.parse("2026-10-23T00:00Z"));
        assert.equal(occurrences[0].datum, "2026-10-22"); assert.equal(occurrences[0].zeit, "01:30");
        assert.equal(occurrences[0].icsStartUtc, Date.parse("2026-10-21T23:30Z"));
      }
      console.log("TIME ZONE SETTINGS PASS: " + scenario + " " + (failedSave || scenario === "source-changed" ? "failed save or changed source prevents native write " : "anchor SaveACK precedes native CAS and final book SaveACK ") + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
