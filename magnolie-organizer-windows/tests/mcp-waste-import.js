"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP waste fixture timed out"); process.exit(1); }, 15000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {
      termine: [{ id: "owned-ordinary", datum: "2030-02-04", titel: "Keep ordinary appointment" }],
      muelltermine: [{ id: "owned-manual", name: "Manual glass", art: "custom", von: "2030-01-01", intervallTage: 14, farbe: "#123456" }]
    });
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      let sequence = 0, snapshotMode = "success", snapshots = 0, heldSnapshot, autoSave = true, saveSeen, snapshotSeen;
      let sourceRevision = "f".repeat(64), nativeError = false;
      const rows = [["Datum", "Abfallart", "Ort", "Notiz", "UID"], ["04.02.2030", "Biotonne", "Owned point", "Owned note", "owned-bio"],
        ["04.02.2030", "Biotonne", "Owned point", "Owned note", "owned-bio"], ["05.02.2030", "Papier", "Owned point", "", "owned-paper"]];
      const source = "waste:csv:" + "b".repeat(64), post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern") {
          if (autoSave) queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true }));
          else saveSeen?.(message);
        }
        if (message.cmd === "import" && message.requestId) queueMicrotask(() => {
          assert.equal(message.art, "muell");
          if (nativeError || message.expectedRevision && message.expectedRevision !== sourceRevision) b.w.App.importErgebnis({ requestId: message.requestId, art: "muell", ok: false, code: nativeError ? "native_operation_failed" : "conflict", fehler: "owned-private-read-error" });
          else b.w.App.importErgebnis({ requestId: message.requestId, art: "muell", ok: true, pfad: message.pfad, bytes: 1234, sha256: "a".repeat(64), revision: sourceRevision,
            muellFormat: "csv", muellQuelle: source, datei: "owned.csv", zeilen: JSON.parse(JSON.stringify(rows)) });
        });
        if (message.cmd === "mutations_snapshot") {
          snapshots++; assert.equal(message.reason, "pre-change"); heldSnapshot = message;
          if (snapshotMode === "hold") { snapshotSeen?.(message); return; }
          queueMicrotask(() => {
            if (snapshotMode === "stale") b.t.daten().muelltermine[0].name = "Changed meanwhile";
            b.w.App.mutationsSnapshot({ token: message.token, ok: snapshotMode !== "error" });
          });
        }
      };
      async function rpc(method, params, explicitId) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
          ...(!method.startsWith("notifications/") ? { id: explicitId ?? sequence } : {}), ...(params === undefined ? {} : { params }) } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
      }
      const call = async (name, args, id) => (await rpc("tools/call", { name, arguments: args }, id)).result;
      const ok = result => { assert.equal(result.isError, false, JSON.stringify(result)); return result.structuredContent; };
      const fail = (result, code) => { assert.equal(result.isError, true, JSON.stringify(result)); assert.equal(result.structuredContent.code, code); };
      await rpc("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "owned-waste-fixture", version: "1" } });
      await rpc("notifications/initialized");
      const csv = { has_header: true, date_column: 0, type_column: 1, location_column: 2, note_column: 3, uid_column: 4, date_format: "dot" };
      const args = { path: "/owned-fixture/waste.csv", csv }, before = JSON.stringify(b.t.daten()), ordinary = JSON.stringify(b.t.daten().termine);
      const preview = async () => ok(await call("organizer_waste_import_preview", args));
      fail(await call("organizer_waste_import_preview", { path: args.path }), "invalid_settings");
      let inspected = await preview(); assert.equal(inspected.groups.length, 2); assert.equal(inspected.groups.find(group => group.kind === "organic").count, 2);
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(snapshots, 0);
      const applyArgs = () => ({ ...args, expected_revision: inspected.revision, expected_book_revision: inspected.book_revision, expected_mapping_revision: inspected.mapping_revision,
        groups: [{ type: inspected.groups.find(group => group.kind === "organic").type, name: "Owned organic", kind: "organic", color: "#AABBCC" }] });
      fail(await call("organizer_waste_import_apply", { ...applyArgs(), expected_book_revision: "0".repeat(64) }), "conflict");
      fail(await call("organizer_waste_import_apply", { ...applyArgs(), csv: { ...csv, note_column: -1 } }), "conflict");
      fail(await call("organizer_waste_import_apply", { ...applyArgs(), groups: [{ type: "missing" }] }), "not_found");
      fail(await call("organizer_waste_import_apply", { ...applyArgs(), groups: [applyArgs().groups[0], applyArgs().groups[0]] }), "invalid_settings");
      assert.equal(snapshots, 0);
      snapshotMode = "error"; fail(await call("organizer_waste_import_apply", applyArgs()), "snapshot_failed");
      assert.equal(JSON.stringify(b.t.daten()), before);
      snapshotMode = "stale"; fail(await call("organizer_waste_import_apply", applyArgs()), "source_changed");
      assert.equal(b.t.daten().muelltermine.length, 1); b.t.daten().muelltermine[0].name = "Manual glass";
      inspected = await preview(); snapshotMode = "hold";
      const checkpointDispatched = new Promise(resolve => { snapshotSeen = resolve; });
      const cancelled = call("organizer_waste_import_apply", applyArgs(), 8000);
      await checkpointDispatched;
      assert.equal(snapshots, 3); await rpc("notifications/cancelled", { requestId: 8000 }); fail(await cancelled, "cancelled");
      b.w.App.mutationsSnapshot({ token: heldSnapshot.token, ok: true }); await tick(); assert.equal(JSON.stringify(b.t.daten()), before);
      snapshotMode = "success"; autoSave = false; let completed = false;
      const saving = new Promise(resolve => { saveSeen = resolve; });
      const pending = call("organizer_waste_import_apply", applyArgs()).then(result => { completed = true; return result; });
      const save = await saving; assert.equal(completed, false); b.w.App.gespeichert({ id: save.id, ok: true });
      const applied = ok(await pending); autoSave = true;
      assert.equal(applied.persisted, true); assert.equal(applied.incoming_unique_count, 1); assert.equal(applied.group_ids.length, 1);
      assert.equal(b.t.daten().muelltermine.length, 2); assert.equal(b.t.daten().muelltermine[0].farbe, "#123456");
      const imported = b.t.daten().muelltermine.find(group => group.importQuelle === source), event = imported.importierteTermine[0];
      assert.equal(imported.name, "Owned organic"); assert.equal(imported.farbe, "#aabbcc"); assert.equal(imported.importierteTermine.length, 1); assert.equal(event.notiz, "Owned note");
      assert.equal(b.t.daten().einstellungen.kalender.muellkalenderAn, true);
      const after = JSON.stringify(b.t.daten()); inspected = await preview(); ok(await call("organizer_waste_import_apply", applyArgs()));
      assert.equal(JSON.stringify(b.t.daten()), after, "Replay changed stable groups/events");
      sourceRevision = "e".repeat(64); fail(await call("organizer_waste_import_apply", applyArgs()), "conflict");
      rows[1][0] = rows[2][0] = "06.02.2030"; inspected = await preview(); ok(await call("organizer_waste_import_apply", applyArgs()));
      const updated = b.t.daten().muelltermine.find(group => group.id === imported.id);
      assert.equal(updated.importierteTermine.length, 1); assert.equal(updated.importierteTermine[0].id, event.id); assert.equal(updated.importierteTermine[0].datum, "2030-02-06");
      assert.equal(JSON.stringify(b.t.daten().termine), ordinary);
      nativeError = true; const failedRead = await call("organizer_waste_import_preview", args); fail(failedRead, "native_operation_failed"); assert.ok(!JSON.stringify(failedRead).includes("owned-private-read-error"));
      nativeError = false; rows[1][0] = "invalid"; fail(await call("organizer_waste_import_preview", args), "invalid_settings");
      assert.ok(!b.w.document.querySelector(".muell-import-vorschau"));
      console.log("MCP WASTE IMPORT PASS: shared CSV model, source/book/mapping CAS, checkpoint/cancel/saveACK/replay/UID updates " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
