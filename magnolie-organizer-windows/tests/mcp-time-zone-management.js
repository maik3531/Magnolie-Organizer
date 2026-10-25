"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "aktualisiereAutomatischeZeitzone, speichereJetzt: speichereJetzt,"));') + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const plain = value => JSON.parse(JSON.stringify(value));
const watchdog = setTimeout(() => { console.error("MCP time-zone management timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { termine: [{ id: "owned-event", uid: "owned-stable-uid", titel: "Owned local event", datum: "2026-10-22", zeit: "01:30", endZeit: "02:30", geaendert: 321 }],
      kontakte: [{ id: "owned-contact", vorname: "Owned", nachname: "Contact", vcardRoundtrip: ["TZ:America/New_York"] }] });
    try {
      if (b.saves().length) b.ack(); await tick();
      Object.assign(b.t.daten().einstellungen.regional, { timeZone: "Europe/Berlin", timeZoneManagement: "automatic", timeZoneDetection: "phone", timeZoneManual: "UTC" });
      const event = b.t.daten().termine[0], originalUid = event.uid, originalModified = event.geaendert;
      let native = plain(b.t.daten().einstellungen.regional), owner = "d".repeat(64), variant = "valid", candidateZone = "Asia/Tokyo";
      let previewVersion = 1, reads = 0, detections = 0, writes = 0, heldSave = null, heldDetect = null, heldWrite = null;
      let saveMode = "auto", writeMode = "auto", savedImage = null;
      const ack = message => { savedImage = JSON.parse(message.text); b.w.App.gespeichert({ id: message.id, ok: true }); };
      const replyCandidate = message => {
        const now = Date.now();
        b.w.App.zeitzonenErgebnis({ requestId: message.requestId, ok: true, regional: plain(native), book_source: variant === "wrong_source" ? "f".repeat(64) : owner,
          automatic: true, native_changed: variant === "early_write", time_zone: variant === "invalid_zone" ? "Mars/Olympus" : candidateZone,
          source: variant === "unselected_source" ? "ip" : "phone", captured_ms: variant === "stale" ? now - 400000 : now,
          checked_at_ms: now, fallback: false, private_position: "owned-private-position-must-not-leak" });
      };
      const replyWrite = message => {
        if (writeMode === "mismatch") { b.w.App.regionalErgebnis({ requestId: message.requestId, ok: true, regional: { ...plain(message.regional), timeZone: "UTC" } }); return; }
        native = plain(message.regional);
        b.w.App.regionalErgebnis({ requestId: message.requestId, ok: true, regional: native });
      };
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "regional_einstellungen_status") {
          reads++;
          queueMicrotask(() => b.w.App.regionalStand({ requestId: message.requestId, ok: true, regional: plain(native), time_zone_preview_version: previewVersion, book_source: owner }));
        } else if (message.cmd === "zeitzone_erkennen") {
          detections++; assert.equal(message.expectedBookSource, owner); assert.deepEqual(message.expectedRegional, native);
          if (variant === "hold") heldDetect = message; else queueMicrotask(() => replyCandidate(message));
        } else if (message.cmd === "regional_einstellungen") {
          writes++; assert.equal(message.expectedBookSource, owner); assert.deepEqual(message.expectedRegional, native);
          assert.ok(savedImage?.termine[0].icsRoundtrip.includes("DTSTART;TZID=Europe/Berlin:20261022T013000"), "Native setting changed before the original local time was durably anchored");
          if (writeMode === "hold") heldWrite = message; else queueMicrotask(() => replyWrite(message));
        } else if (message.cmd === "speichern") {
          if (saveMode === "hold") heldSave = message; else queueMicrotask(() => ack(message));
        }
      };
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      let sequence = 0;
      async function rpc(method, params) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method, ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation)?.response;
      }
      const call = async (name, args) => (await rpc("tools/call", { name, arguments: args })).result;
      const ok = result => { assert.equal(result?.isError, false, JSON.stringify(result)); return result.structuredContent; };
      const fail = (result, code) => { assert.equal(result.isError, true, JSON.stringify(result)); assert.equal(result.structuredContent.code, code); };
      const read = async () => ok(await call("organizer_regional_settings_read", {}));
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-zone-fixture", version: "1" } });
      await rpc("notifications/initialized", {});
      let listed = (await rpc("tools/list", {})).result;
      const tools = [...listed.tools];
      while (listed.nextCursor) { listed = (await rpc("tools/list", { cursor: listed.nextCursor })).result; tools.push(...listed.tools); }
      assert.equal(tools.find(tool => tool.name === "organizer_time_zone_detect").annotations.readOnlyHint, true);
      assert.equal(tools.find(tool => tool.name === "organizer_time_zone_refresh").annotations.readOnlyHint, false);
      const regionalSchema = tools.find(tool => tool.name === "organizer_regional_settings_update").inputSchema.properties;
      assert.deepEqual(regionalSchema.appointment_time_zone_display.enum, ["own", "contact", "source"]);
      assert.equal(regionalSchema.time_zone_detected_source, undefined, "A public caller must not forge native observation provenance");
      let status = await read(); assert.equal(status.time_zone_detection_available, true);
      assert.equal(status.settings.time_zone_management, "automatic");
      const before = JSON.stringify(b.t.daten()), savesBefore = b.saves().length;
      const preview = ok(await call("organizer_time_zone_detect", { expected_revision: status.revision }));
      assert.equal(preview.time_zone, "Asia/Tokyo"); assert.equal(preview.native_changed, false); assert.equal(preview.persisted, false);
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, savesBefore); assert.equal(writes, 0);
      assert.ok(!JSON.stringify(preview).includes(owner) && !JSON.stringify(preview).includes("owned-private-position"));
      for (const [mode, code] of [["invalid_zone", "invalid_result"], ["stale", "invalid_result"], ["wrong_source", "source_changed"], ["early_write", "invalid_result"], ["unselected_source", "invalid_result"]]) {
        variant = mode; fail(await call("organizer_time_zone_detect", { expected_revision: status.revision }), code);
        assert.equal(writes, 0); assert.equal(JSON.stringify(b.t.daten()), before);
      }
      variant = "valid";
      const queriesBefore = detections;
      owner = "e".repeat(64);
      fail(await call("organizer_time_zone_detect", { expected_revision: status.revision }), "conflict");
      assert.equal(detections, queriesBefore); owner = "d".repeat(64);
      previewVersion = 0;
      status = await read(); assert.equal(status.time_zone_detection_available, false);
      fail(await call("organizer_time_zone_detect", { expected_revision: status.revision }), "unsupported_feature");
      assert.equal(detections, queriesBefore); previewVersion = 1;
      native.timeZoneManagement = "off"; b.t.daten().einstellungen.regional.timeZoneManagement = "off";
      status = await read(); fail(await call("organizer_time_zone_detect", { expected_revision: status.revision }), "invalid_settings");
      assert.equal(detections, queriesBefore);
      native.timeZoneManagement = "automatic"; b.t.daten().einstellungen.regional.timeZoneManagement = "automatic";
      status = await read(); saveMode = "hold";
      const applying = call("organizer_time_zone_refresh", { expected_revision: status.revision });
      for (let index = 0; index < 500 && !heldSave; index++) await tick();
      assert.ok(heldSave); assert.equal(writes, 0); assert.equal(native.timeZone, "Europe/Berlin");
      saveMode = "auto"; ack(heldSave);
      const applied = ok(await applying); assert.equal(applied.persisted, true); assert.equal(applied.native_saved, true);
      assert.equal(native.timeZone, "Asia/Tokyo"); assert.equal(b.t.daten().einstellungen.regional.timeZone, "Asia/Tokyo");
      assert.equal(event.uid, originalUid); assert.equal(event.geaendert, originalModified);
      const originalRaw = JSON.stringify(event.icsRoundtrip);
      status = await read(); ok(await call("organizer_time_zone_refresh", { expected_revision: status.revision }));
      assert.equal(JSON.stringify(event.icsRoundtrip), originalRaw, "Repeated refresh added another shift or anchor");
      const beforePolicy = detections;
      status = await read();
      const manual = ok(await call("organizer_regional_settings_update", { expected_revision: status.revision,
        time_zone_management: "manual", time_zone_manual: "Europe/Berlin", appointment_time_zone_display: "contact", task_time_zone_display: "source" }));
      assert.equal(manual.settings.time_zone, "Europe/Berlin"); assert.equal(manual.settings.appointment_time_zone_display, "contact");
      assert.equal(manual.settings.task_time_zone_display, "source"); assert.equal(detections, beforePolicy, "Saving policy queried a sensor or network source");
      status = await read();
      ok(await call("organizer_regional_settings_update", { expected_revision: status.revision, time_zone_management: "off" }));
      status = await read(); assert.equal(status.settings.time_zone_manual, "Europe/Berlin"); assert.equal(status.settings.appointment_time_zone_display, "contact");
      ok(await call("organizer_regional_settings_update", { expected_revision: status.revision, time_zone_management: "automatic" }));
      assert.equal(detections, beforePolicy, "Enabling automatic mode must remain separate from detection");
      status = await read(); ok(await call("organizer_time_zone_refresh", { expected_revision: status.revision }));
      assert.equal(JSON.stringify(event.icsRoundtrip), originalRaw);
      native.timeZoneDetectedAt = "0"; b.t.daten().einstellungen.regional.timeZoneDetectedAt = "0";
      const beforeAutomatic = detections;
      variant = "hold"; heldDetect = null;
      const automatic = b.t.aktualisiereAutomatischeZeitzone();
      for (let index = 0; index < 500 && !heldDetect; index++) await tick(); assert.ok(heldDetect);
      await b.t.aktualisiereAutomatischeZeitzone(); assert.equal(detections, beforeAutomatic + 1, "Concurrent focus events launched duplicate automatic detection");
      variant = "valid"; replyCandidate(heldDetect); await automatic;
      const readsAfterAutomatic = reads;
      await b.t.aktualisiereAutomatischeZeitzone(); assert.equal(reads, readsAfterAutomatic, "Automatic detection did not honor its per-book throttle");
      assert.equal(JSON.stringify(event.icsRoundtrip), originalRaw);
      candidateZone = "America/New_York"; writeMode = "mismatch"; status = await read();
      fail(await call("organizer_time_zone_refresh", { expected_revision: status.revision }), "invalid_result");
      assert.equal(b.t.daten().einstellungen.regional.timeZone, "Asia/Tokyo");
      writeMode = "hold"; status = await read();
      const lateApply = call("organizer_time_zone_refresh", { expected_revision: status.revision });
      for (let index = 0; index < 500 && !heldWrite; index++) await tick(); assert.ok(heldWrite);
      b.t.oeffneTerminBlatt(null, "2026-10-24"); b.input("#tb-titel", "Owned draft survives late zone save");
      writeMode = "auto"; replyWrite(heldWrite);
      fail(await lateApply, "editor_busy");
      assert.equal(b.w.document.querySelector("#tb-titel").value, "Owned draft survives late zone save");
      const beforeDraftAutomatic = detections;
      await b.t.aktualisiereAutomatischeZeitzone(); assert.equal(detections, beforeDraftAutomatic, "Automatic refresh queried sources while an editor draft was open");
      assert.equal(b.t.daten().einstellungen.regional.timeZone, "Asia/Tokyo"); assert.equal(native.timeZone, "America/New_York");
      status = await read(); assert.equal(status.settings.time_zone, "America/New_York"); assert.equal(status.book_settings.time_zone, "Asia/Tokyo");
      const blockedBefore = detections;
      fail(await call("organizer_time_zone_refresh", { expected_revision: status.revision }), "editor_busy"); assert.equal(detections, blockedBefore);
      const readonly = ok(await call("organizer_time_zone_detect", { expected_revision: status.revision })); assert.equal(readonly.persisted, false);
      variant = "hold"; const cancelledId = sequence + 1;
      const pending = call("organizer_time_zone_detect", { expected_revision: status.revision });
      for (let index = 0; index < 500 && !heldDetect; index++) await tick(); assert.ok(heldDetect);
      await rpc("notifications/cancelled", { requestId: cancelledId }); fail(await pending, "cancelled");
      variant = "valid"; replyCandidate(heldDetect); await tick();
      assert.equal(b.w.document.querySelector("#tb-titel").value, "Owned draft survives late zone save");
      assert.equal(JSON.stringify(event.icsRoundtrip), originalRaw);
      assert.ok(reads > 0);
      console.log("MCP TIME ZONE PASS: opt-in preview, strict provenance, private handles, source CAS, durable anchors, readback, idempotence, cancellation and late draft safety " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
