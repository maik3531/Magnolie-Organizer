"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP sync settings fixture timed out"); process.exit(1); }, 20000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {
      einstellungen: { sync: { kalenderUid: "owned-offline", kalenderUids: ["owned-offline", "owned-a"], adressbuchUid: "owned-old-book", beimStart: false,
        timeDirections: { "owned-peer": "phone_import" }, kdeEmpfang: { dateien: true, geraetId: "owned-device", ordner: "/owned-fixture" } } },
      kontakte: [{ id: "owned-contact", vorname: "Owned", nachname: "Contact", sync: true, syncQuellen: { "owned-provider": { marker: "keep" } } }],
      termine: [{ id: "owned-event", datum: "2030-02-04", titel: "Keep routing", sync: true, syncKalenderUid: "owned-offline", syncQuellen: { "owned-offline": { marker: "keep" } } }]
    });
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      let sequence = 0, autoSave = true, saveSeen, onSource, sourceMode = "valid", sourceRequests = 0;
      const sources = { verfuegbar: true, buchOk: true, kalender: [{ uid: "owned-a", name: "Owned A" }, { uid: "owned-b", name: "Owned B", supportsVtodo: false }],
        adressbuecher: [{ uid: "owned-new-book", name: "Owned address book" }] };
      const replySources = message => b.w.App.edsStatus({ ...sources, ...(sourceMode === "invalid" ? { alleKalender: "" } : {}), requestId: message.requestId || "" });
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern") {
          if (autoSave) queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true })); else saveSeen?.(message);
        }
        if (message.cmd === "eds_status") {
          if (message.requestId) { sourceRequests++; if (onSource) { onSource(message); return; } }
          queueMicrotask(() => replySources(message));
        }
      };
      async function rpc(method, params, explicitId) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
          ...(!method.startsWith("notifications/") ? { id: explicitId ?? sequence } : {}), ...(params === undefined ? {} : { params }) } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
      }
      const tool = async (name, args, id) => { const response = await rpc("tools/call", { name, arguments: args }, id); assert.ok(!response.error, JSON.stringify(response)); return response.result; };
      const ok = result => { assert.equal(result.isError, false, JSON.stringify(result)); return result.structuredContent; };
      const fail = (result, code) => { assert.equal(result.isError, true, JSON.stringify(result)); assert.equal(result.structuredContent.code, code); };
      const read = async () => ok(await tool("organizer_sync_settings_read", {}));
      const update = (state, fields, id) => tool("organizer_sync_settings_update", { expected_revision: state.revision, ...fields }, id);
      await rpc("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "owned-sync-settings", version: "1" } });
      await rpc("notifications/initialized");
      const domain = () => JSON.stringify({ contacts: b.t.daten().kontakte, events: b.t.daten().termine, tombstones: b.t.daten().geloescht, transactions: b.t.daten().syncMetadaten });
      const originalDomain = domain(), clock = b.t.daten().zeiterfassung;
      const hidden = JSON.stringify({ time: b.t.daten().einstellungen.sync.timeDirections, kde: b.t.daten().einstellungen.sync.kdeEmpfang });
      let state = await read(); assert.equal(state.settings.primary_calendar_id, "owned-offline");
      autoSave = false; let completed = false;
      const saving = new Promise(resolve => { saveSeen = resolve; });
      const pending = update(state, { at_startup: true, success_notifications: true, prefer_newer_contacts: true }).then(result => { completed = true; return result; });
      const saved = await saving; assert.equal(completed, false); assert.equal(sourceRequests, 0);
      b.w.App.gespeichert({ id: saved.id, ok: true }); assert.equal(ok(await pending).persisted, true); autoSave = true;
      fail(await update(state, { success_notifications: false }), "conflict");
      state = await read();
      const linked = ok(await update(state, { calendar_ids: ["owned-offline", "owned-a", "owned-b"], address_book_id: "owned-new-book" }));
      assert.equal(linked.settings.primary_calendar_id, "owned-offline"); assert.equal(sourceRequests, 1);
      state = await read(); const savesBefore = b.saves().length;
      fail(await update(state, { calendar_ids: ["not-offered"] }), "invalid_settings"); assert.equal(b.saves().length, savesBefore);
      sourceMode = "invalid"; fail(await update(state, { address_book_id: "other-new-book" }), "invalid_result"); sourceMode = "valid";
      assert.equal((await read()).revision, state.revision);
      const hiddenBefore = b.t.daten().einstellungen.sync.timeDirections["owned-peer"];
      b.t.daten().einstellungen.sync.timeDirections["owned-peer"] = "two_way";
      fail(await update(state, { success_notifications: false }), "conflict"); b.t.daten().einstellungen.sync.timeDirections["owned-peer"] = hiddenBefore;
      let native;
      const started = new Promise(resolve => { onSource = message => { native = message; resolve(); }; });
      const racing = update(state, { address_book_id: "other-new-book" });
      await started; b.t.daten().einstellungen.sync.erfolgsmeldungen = false;
      const originalBooks = sources.adressbuecher; sources.adressbuecher = [...originalBooks, { uid: "other-new-book", name: "Other owned book" }];
      replySources(native); fail(await racing, "conflict"); onSource = null; sources.adressbuecher = originalBooks;
      state = await read(); const beforeCancel = JSON.stringify(b.t.daten().einstellungen.sync);
      const cancelStarted = new Promise(resolve => { onSource = message => { native = message; resolve(); }; });
      const cancelled = update(state, { calendar_ids: ["new-cancel-target"] }, 8000);
      await cancelStarted; await rpc("notifications/cancelled", { requestId: 8000 }); fail(await cancelled, "cancelled");
      replySources(native); onSource = null; await tick(); assert.equal(JSON.stringify(b.t.daten().einstellungen.sync), beforeCancel);
      state = await read(); const sourceCount = sourceRequests;
      const disabled = ok(await update(state, { calendar_ids: [], address_book_id: "" }));
      assert.equal(disabled.settings.primary_calendar_id, ""); assert.equal(sourceRequests, sourceCount);
      state = await read(); ok(await update(state, { calendar_ids: ["owned-a", "owned-b"] }));
      state = await read(); assert.equal(state.settings.primary_calendar_id, "owned-a");
      ok(await update(state, { calendar_ids: ["owned-b", "owned-a"] }));
      assert.equal((await read()).settings.primary_calendar_id, "owned-a", "Reordering should preserve a still-selected primary calendar");
      b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-sync").click(); await tick();
      fail(await update(await read(), { at_startup: false }), "dialog_busy");
      const a = b.w.document.querySelector('[data-kalender-uid="owned-a"]'); assert.ok(a); a.checked = false; a.dispatchEvent(new b.w.Event("change"));
      const startup = b.w.document.querySelector("#sync-beim-start"); startup.checked = false; startup.dispatchEvent(new b.w.Event("change"));
      const newer = b.w.document.querySelector("#sync-kontakte-neuer"); newer.checked = false; newer.dispatchEvent(new b.w.Event("change"));
      const notices = b.w.document.querySelector("#sync-erfolgsmeldungen"); notices.checked = true; notices.dispatchEvent(new b.w.Event("change"));
      const address = b.w.document.querySelector("#sync-wahl select"); assert.ok(address); address.value = "owned-new-book"; address.dispatchEvent(new b.w.Event("change"));
      const gui = (await read()).settings;
      assert.equal(gui.primary_calendar_id, "owned-b"); assert.deepEqual(Array.from(gui.calendar_ids), ["owned-b"]);
      assert.equal(gui.at_startup, false); assert.equal(gui.prefer_newer_contacts, false); assert.equal(gui.success_notifications, true);
      assert.equal(gui.address_book_id, "owned-new-book"); b.t.speichereJetzt(); await tick();
      b.w.document.querySelector("#einstellungen-zu").click();
      assert.equal(JSON.stringify({ time: b.t.daten().einstellungen.sync.timeDirections, kde: b.t.daten().einstellungen.sync.kdeEmpfang }), hidden);
      assert.equal(domain(), originalDomain); assert.equal(b.t.daten().zeiterfassung, clock);
      assert.ok(!b.messages.some(message => ["sync", "sync_start", "graph_anmelden"].includes(message.cmd)));
      console.log("MCP SYNC SETTINGS PASS: shared GUI choices, primary/offline semantics, source/CAS/cancel/save gates and unchanged routing " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
