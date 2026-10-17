"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP planner fixture timed out"); process.exit(1); }, 15000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { termine: [{ id: "owned-planner-event", uid: "owned-planner-event", datum: "2030-02-04", zeit: "09:05", titel: "Owned planner event" }],
      kontakte: [{ id: "owned-sheet-contact", vorname: "Owned", nachname: "Spreadsheet" }],
      gesundheit: { vitalwerte: [{ id: "owned-sheet-vital", datum: "2030-02-04", zeit: "09:05", puls: 65, gewicht: 70, groesse: 175 }] } });
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      let sequence = 0, onExport;
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern") queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true }));
        if (["planer_ods", "adressen_ods", "gesundheit_ods", "zeit_ods"].includes(message.cmd) && message.requestId && onExport) onExport(message);
      };
      async function rpc(method, params, explicitId) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
          ...(!method.startsWith("notifications/") ? { id: explicitId ?? sequence } : {}), ...(params === undefined ? {} : { params }) } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
      }
      const request = async (args, id, name = "organizer_planner_export") => (await rpc("tools/call", { name, arguments: args }, id)).result;
      const ok = result => { assert.equal(result.isError, false, JSON.stringify(result)); return result.structuredContent; };
      const failure = (result, code) => { assert.equal(result.isError, true, JSON.stringify(result)); assert.equal(result.structuredContent.code, code); };
      await rpc("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "owned-planner-fixture", version: "1" } });
      await rpc("notifications/initialized");
      const revision = ok((await rpc("tools/call", { name: "organizer_book_revision_read" })).result).revision;
      const before = JSON.stringify(b.t.daten()), selectedYear = b.t.zustand().planer.jahr;
      const reply = (message, extra = {}) => b.w.App.documentExportErgebnis({ requestId: message.requestId, ok: true, pfad: message.pfad, bytes: 123, sha256: "d".repeat(64), ...extra });
      let native, completed = false;
      const dispatched = new Promise(resolve => { onExport = message => { native = message; resolve(); }; });
      const pending = request({ expected_book_revision: revision, year: 2030, layout: "year", path: "/owned-fixture/year.ods" }).then(value => { completed = true; return value; });
      await dispatched; assert.equal(native.spalten.length, 12); assert.equal(native.zeilen.length, 31); assert.equal(native.overwrite, false);
      reply({ ...native, requestId: "wrong-document-request" }); await tick(); assert.equal(completed, false);
      reply(native); assert.equal(ok(await pending).month, null);
      onExport = message => {
        assert.equal(message.layout, "month"); assert.equal(message.monat, 2); assert.equal(message.spalten.length, 8); assert.equal(message.zeilen.length, 6);
        assert.ok(JSON.stringify(message.zeilen).includes("Owned planner event")); reply(message);
      };
      const month = ok(await request({ expected_book_revision: revision, year: 2030, layout: "month", month: 2, appointments: true, path: "/owned-fixture/month.ods", overwrite: true }));
      assert.equal(month.confirmed, true); assert.equal(month.month, 2);
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.t.zustand().planer.jahr, selectedYear);
      failure(await request({ expected_book_revision: revision, year: 2030, layout: "month", path: "/owned-fixture/missing-month.ods" }), "invalid_settings");
      failure(await request({ expected_book_revision: revision, year: 2030, layout: "year", appointments: false, path: "/owned-fixture/invalid-options.ods" }), "invalid_settings");
      failure(await request({ expected_book_revision: "0".repeat(64), year: 2030, layout: "year", path: "/owned-fixture/stale.ods" }), "conflict");
      onExport = message => reply(message, { ok: false, code: "native_operation_failed", fehler: "owned-private-document-error" });
      const failed = await request({ expected_book_revision: revision, year: 2030, layout: "year", path: "/owned-fixture/error.ods" });
      failure(failed, "native_operation_failed"); assert.ok(!JSON.stringify(failed).includes("owned-private-document-error"));
      onExport = message => reply(message, { sha256: undefined });
      failure(await request({ expected_book_revision: revision, year: 2030, layout: "year", path: "/owned-fixture/incomplete.ods" }), "invalid_result");
      const lateStarted = new Promise(resolve => { onExport = message => { native = message; resolve(); }; });
      const cancelled = request({ expected_book_revision: revision, year: 2030, layout: "year", path: "/owned-fixture/cancelled.ods" }, 8000);
      await lateStarted; await rpc("notifications/cancelled", { requestId: 8000 }); failure(await cancelled, "cancelled");
      const toast = b.w.document.querySelector("#zettel").textContent; reply(native);
      assert.equal(b.w.document.querySelector("#zettel").textContent, toast);
      onExport = message => { assert.equal(message.cmd, "adressen_ods"); assert.equal(message.spalten.length, 2); assert.equal(message.zeilen.length, 1); reply(message); };
      const contacts = ok(await request({ expected_book_revision: revision, path: "/owned-fixture/contacts.ods", contact_ids: ["owned-sheet-contact"], fields: ["vorname", "nachname", "notiz"] }, undefined, "organizer_contacts_spreadsheet_export"));
      assert.equal(contacts.kind, "contacts");
      failure(await request({ expected_book_revision: revision, path: "/owned-fixture/missing-contact.ods", contact_ids: ["missing"] }, undefined, "organizer_contacts_spreadsheet_export"), "not_found");
      failure(await request({ expected_book_revision: revision, path: "/owned-fixture/empty-column.ods", fields: ["notiz"] }, undefined, "organizer_contacts_spreadsheet_export"), "no_entries");
      onExport = message => { assert.equal(message.cmd, "gesundheit_ods"); assert.equal(message.tabellen.length, 1); assert.ok(JSON.stringify(message.tabellen[0].zeilen).includes("65")); reply(message); };
      const health = ok(await request({ expected_book_revision: revision, path: "/owned-fixture/health.ods", table: "vital", mode: "values", from: "2030-02-01", to: "2030-02-28" }, undefined, "organizer_health_spreadsheet_export"));
      assert.equal(health.kind, "health");
      failure(await request({ expected_book_revision: revision, path: "/owned-fixture/invalid-health.ods", table: "vital", mode: "values", insulin_scheme: true }, undefined, "organizer_health_spreadsheet_export"), "invalid_settings");
      onExport = message => { assert.equal(message.cmd, "zeit_ods"); assert.equal(message.sheet.month, "2030-02"); assert.equal(message.sheet.name, "Owned document name"); assert.deepEqual(message.sheet.days, [1, 4]); reply(message); };
      const time = ok(await request({ expected_book_revision: revision, path: "/owned-fixture/time.ods", year: 2030, month: 2, report_name: "Owned document name", days: [1, 4] }, undefined, "organizer_time_spreadsheet_export"));
      assert.equal(time.kind, "time");
      failure(await request({ expected_book_revision: revision, path: "/owned-fixture/invalid-days.ods", year: 2030, month: 2, days: [30] }, undefined, "organizer_time_spreadsheet_export"), "invalid_settings");
      assert.equal(JSON.stringify(b.t.daten()), before, "Spreadsheet exports must retain canonical values and report preferences");
      console.log("MCP PLANNER EXPORT PASS: shared year/month payloads, correlation/CAS/options/cancel " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
