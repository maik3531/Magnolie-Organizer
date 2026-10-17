"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP print fixture timed out"); process.exit(1); }, 15000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {
      kontakte: [{ id: "owned-print-contact", vorname: "Owned", nachname: "<Print>" }],
      aufgaben: [{ id: "owned-print-task", titel: "Owned completed task", erledigt: true, prio: 2 }],
      notizen: [{ id: "owned-print-note", titel: "Owned note", text: "Owned <private> text" }],
      termine: [{ id: "owned-print-event", datum: "2030-02-04", zeit: "09:05", endDatum: "2030-02-06", endZeit: "10:00", titel: "Owned printed appointment" }],
      gesundheit: { vitalwerte: [{ id: "owned-print-vital", datum: "2030-02-04", zeit: "09:05", puls: 65, gewicht: 70, groesse: 175 }] },
      jahrestage: [{ id: "owned-print-anniversary", name: "Owned anniversary", datum: "2000-02-04", typ: "other" }],
      customOrganizer: { version: 3, modules: [{ id: "owned-print-block", type: "notes", title: "Owned block", page: "left", order: 0,
        items: [{ id: "owned-print-item", title: "Owned item", text: "Owned block text", html: "Owned block text" }] }] }
    });
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      let sequence = 0, onPrint;
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern") queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true }));
        if (message.cmd === "drucken" && message.requestId && onPrint) onPrint(message);
      };
      async function rpc(method, params, explicitId) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
          ...(!method.startsWith("notifications/") ? { id: explicitId ?? sequence } : {}), ...(params === undefined ? {} : { params }) } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
      }
      const request = async (args, id, name = "organizer_cards_print") => (await rpc("tools/call", { name, arguments: args }, id)).result;
      const ok = result => { assert.equal(result.isError, false, JSON.stringify(result)); return result.structuredContent; };
      const fail = (result, code) => { assert.equal(result.isError, true, JSON.stringify(result)); assert.equal(result.structuredContent.code, code); };
      await rpc("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "owned-print-fixture", version: "1" } });
      await rpc("notifications/initialized");
      const revision = ok((await rpc("tools/call", { name: "organizer_book_revision_read" })).result).revision;
      const before = JSON.stringify(b.t.daten());
      const args = { expected_book_revision: revision, section: "contacts", ids: ["owned-print-contact"] };
      const reply = (message, extra = {}) => b.w.App.printErgebnis({ requestId: message.requestId, ok: true, stage: "dialog_returned", dialogAction: "cancel", ...extra });
      let native, completed = false;
      const dispatched = new Promise(resolve => { onPrint = message => { native = message; resolve(); }; });
      const pending = request(args).then(value => { completed = true; return value; });
      await dispatched; assert.ok(native.html.includes("&lt;Print&gt;")); assert.ok(native.html.includes("Content-Security-Policy"));
      reply({ ...native, requestId: "wrong-request" }); await tick(); assert.equal(completed, false);
      reply(native); const cancelledChoice = ok(await pending);
      assert.equal(cancelledChoice.dialog_action, "cancel"); assert.equal(cancelledChoice.paper_output_confirmed, false);
      onPrint = message => reply(message, { stage: "dialog_requested", dialogAction: "unknown" });
      assert.equal(ok(await request(args)).stage, "dialog_requested");
      onPrint = message => reply(message, { dialogAction: "print" });
      assert.equal(ok(await request(args)).paper_output_confirmed, false);
      onPrint = message => reply(message, { stage: "dialog_requested", dialogAction: "print" });
      fail(await request(args), "invalid_result");
      onPrint = message => reply(message, { ok: false, code: "native_unavailable", fehler: "owned-private-error" });
      const failed = await request(args); fail(failed, "native_unavailable"); assert.ok(!JSON.stringify(failed).includes("owned-private-error"));
      fail(await request({ ...args, expected_book_revision: "0".repeat(64) }), "conflict");
      fail(await request({ ...args, ids: ["missing"] }), "not_found");
      b.t.zustand().aufgaben.filter = { suche: "does-not-match", person: "missing-person" };
      onPrint = message => { assert.ok(message.html.includes("Owned completed task")); assert.ok(!message.html.includes("missing-person")); reply(message); };
      assert.equal(ok(await request({ expected_book_revision: revision, section: "tasks" })).count, 1);
      onPrint = message => { assert.ok(message.html.includes("Owned &lt;private&gt; text")); reply(message); };
      assert.equal(ok(await request({ expected_book_revision: revision, section: "notes", ids: ["owned-print-note"] })).count, 1);
      onPrint = message => { assert.ok(message.html.includes("Owned anniversary")); reply(message); };
      assert.equal(ok(await request({ expected_book_revision: revision, section: "anniversaries" })).count, 1);
      onPrint = message => { assert.ok(message.html.includes("Owned block text")); reply(message); };
      assert.equal(ok(await request({ expected_book_revision: revision, section: "custom", ids: ["owned-print-block"] })).count, 1);
      onPrint = message => { assert.equal(message.html.split("Owned printed appointment").length - 1, 1); reply(message); };
      assert.equal(ok(await request({ expected_book_revision: revision, section: "appointments", year: 2030, month: 2, ids: ["owned-print-event"] })).count, 1);
      fail(await request({ expected_book_revision: revision, section: "appointments" }), "invalid_settings");
      fail(await request({ ...args, year: 2030, month: 2 }), "invalid_settings");
      fail(await request({ expected_book_revision: revision, section: "appointments", year: 2030, month: 3, ids: ["owned-print-event"] }), "not_found");
      const report = (name, options = {}, id) => request({ expected_book_revision: revision, ...options }, id, "organizer_" + name + "_print");
      onPrint = message => { assert.ok(message.html.includes("2030")); assert.ok(!message.html.includes("Owned printed appointment")); reply(message); };
      assert.equal(ok(await report("planner", { year: 2030, layout: "year" })).report, "planner");
      onPrint = message => { assert.ok(message.html.includes("Owned printed appointment")); reply(message); };
      assert.equal(ok(await report("planner", { year: 2030, layout: "month", month: 2, appointments: true })).report, "planner");
      onPrint = message => { assert.ok(!message.html.includes("Owned printed appointment")); reply(message); };
      ok(await report("planner", { year: 2030, layout: "month", month: 2, appointments: false }));
      fail(await report("planner", { year: 2030, layout: "month" }), "invalid_settings");
      fail(await report("planner", { year: 2030, layout: "year", appointments: false }), "invalid_settings");
      onPrint = message => { assert.ok(message.html.includes("<td>65</td>")); reply(message); };
      assert.equal(ok(await report("health", { table: "vital", mode: "values", from: "2030-02-01", to: "2030-02-28" })).report, "health");
      onPrint = message => { assert.ok(!message.html.includes("<td>65</td>")); reply(message); };
      ok(await report("health", { table: "vital", mode: "blank" }));
      ok(await report("health", { table: "vital", mode: "values", from: "2030-03-01" }));
      onPrint = message => { assert.ok(message.html.includes("bz-mit-schema")); reply(message); };
      ok(await report("health", { table: "blood-glucose", mode: "blank", insulin_scheme: true }));
      onPrint = message => { assert.ok(message.html.includes("<svg")); reply(message); };
      ok(await report("health", { table: "none", mode: "values", history: "single", history_metric: "pulse" }));
      onPrint = message => { assert.ok(message.html.includes("diagramm-raster")); reply(message); };
      ok(await report("health", { table: "none", mode: "values", history: "all" }));
      fail(await report("health", { table: "vital", mode: "blank", from: "2030-02-01" }), "invalid_settings");
      fail(await report("health", { table: "vital", mode: "values", insulin_scheme: true }), "invalid_settings");
      onPrint = message => { assert.ok(message.html.includes("Owned &lt;report&gt;")); reply(message); };
      assert.equal(ok(await report("time", { year: 2030, month: 2, report_name: "Owned <report>", days: [1, 4] })).report, "time");
      fail(await report("time", { year: 2030, month: 2, days: [30] }), "invalid_settings");
      fail(await report("time", { expected_book_revision: "0".repeat(64), year: 2030, month: 2 }), "conflict");
      onPrint = message => reply(message, { stage: "dialog_requested", dialogAction: "print" });
      fail(await report("time", { year: 2030, month: 2 }), "invalid_result");
      const lateStarted = new Promise(resolve => { onPrint = message => { native = message; resolve(); }; });
      const cancelled = request(args, 8000);
      await lateStarted; await rpc("notifications/cancelled", { requestId: 8000 }); fail(await cancelled, "cancelled");
      const toast = b.w.document.querySelector("#zettel").textContent; reply(native);
      assert.equal(b.w.document.querySelector("#zettel").textContent, toast);
      assert.equal(JSON.stringify(b.t.daten()), before);
      const note = b.t.daten().notizen.find(entry => entry.id === "owned-print-note"), oldText = note.text;
      note.text = "🌸".repeat(190000);
      const largeRevision = ok((await rpc("tools/call", { name: "organizer_book_revision_read" })).result).revision;
      onPrint = () => assert.fail("Oversized print page reached native renderer");
      fail(await request({ expected_book_revision: largeRevision, section: "notes", ids: [note.id] }), "export_limit");
      note.text = oldText;
      console.log("MCP PRINT PASS: shared cards, explicit selection/filter independence, CAS/native receipts/cancel " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
