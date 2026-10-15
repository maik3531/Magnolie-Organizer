"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const watchdog = setTimeout(() => { console.error("MCP UI test timed out"); process.exit(1); }, 15000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { notizen: [{ id: "fixture-note", titel: "Fixture", text: "Owned fixture only" }] });
    try {
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const session = "a".repeat(48);
      let sequence = 0;
      async function call(message) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session, invocation, message });
        const reply = b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation);
        assert.ok(reply, "Every accepted native invocation must settle");
        assert.equal(reply.session, session);
        return reply.response;
      }
      const request = (id, method, params) => ({ jsonrpc: "2.0", id, method, ...(params === undefined ? {} : { params }) });
      assert.equal((await call(request(1, "initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "fixture", version: "1" } }))).result.serverInfo.name, "magnolie-organizer");
      assert.equal(await call({ jsonrpc: "2.0", method: "notifications/initialized" }), null);
      const tools = (await call(request(2, "tools/list"))).result.tools.map(tool => tool.name);
      assert.ok(tools.includes("organizer_data_read") && tools.includes("organizer_settings_read"));
      const notes = await call(request(3, "tools/call", { name: "organizer_data_read", arguments: { section: "notizen", limit: 1 } }));
      assert.equal(notes.result.isError, false);
      assert.equal(notes.result.structuredContent.entries[0].id, "fixture-note");
      notes.result.structuredContent.entries[0].titel = "Do not mutate source";
      assert.equal(b.t.daten().notizen[0].titel, "Fixture");
      const item = await call(request(4, "tools/call", { name: "organizer_data_read", arguments: { section: "notizen", id: "fixture-note" } }));
      assert.equal(item.result.structuredContent.entry.text, "Owned fixture only");
      const bad = await call(request(5, "tools/call", { name: "organizer_data_read", arguments: { section: "__proto__" } }));
      assert.equal(bad.error.code, -32602);
      // Settle the normal startup migration save before exercising MCP writes.
      if (b.saves().length) b.ack();
      await new Promise(resolve => setImmediate(resolve));
      const noteId = "33333333-3333-4333-8333-333333333333";
      let createdReplied = false;
      const created = call(request(30, "tools/call", { name: "organizer_note_create", arguments: {
        id: noteId, title: "Created fixture", text: "<img src=x onerror=alert(1)>\nPlain text" } })).then(result => { createdReplied = true; return result; });
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(createdReplied, false, "MCP create replied before native save acknowledgement");
      const saved = JSON.parse(b.saves().at(-1).text).notizen.find(note => note.id === noteId);
      assert.ok(saved, "MCP mutation did not use the existing native save queue");
      assert.ok(!saved.html.includes("<img"), "Plain text was treated as executable note markup");
      b.ack();
      assert.equal((await created).result.structuredContent.persisted, true);
      const duplicate = await call(request(31, "tools/call", { name: "organizer_note_create", arguments: {
        id: noteId, title: "Retry", text: "Must not duplicate" } }));
      assert.equal(duplicate.result.structuredContent.code, "already_exists");
      assert.equal(b.t.daten().notizen.filter(note => note.id === noteId).length, 1);
      let onSave;
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text);
        if (JSON.parse(text).cmd === "speichern" && onSave) { const resolve = onSave; onSave = null; resolve(); }
      };
      async function persisted(id, name, args) {
        const saving = new Promise(resolve => { onSave = resolve; });
        const operation = call(request(id, "tools/call", { name, arguments: args }));
        await saving;
        b.ack();
        const response = await operation;
        assert.equal(response.result.isError, false, JSON.stringify(response));
        assert.equal(response.result.structuredContent.persisted, true);
        return response.result.structuredContent;
      }
      const beforeUpdate = (await call(request(33, "tools/call", { name: "organizer_note_read", arguments: { id: noteId } }))).result.structuredContent;
      assert.match(beforeUpdate.revision, /^[a-f0-9]{64}$/);
      const conflict = await call(request(34, "tools/call", { name: "organizer_note_update", arguments: {
        id: noteId, expected_revision: "0".repeat(64), title: "Stale overwrite" } }));
      assert.equal(conflict.result.structuredContent.code, "conflict");
      assert.equal(b.t.daten().notizen.find(note => note.id === noteId).titel, "Created fixture");
      await persisted(35, "organizer_note_update", { id: noteId, expected_revision: beforeUpdate.revision,
        title: "Updated fixture", text: "<b>still plain text</b>" });
      const afterUpdate = (await call(request(36, "tools/call", { name: "organizer_note_read", arguments: { id: noteId } }))).result.structuredContent;
      assert.equal(afterUpdate.note.titel, "Updated fixture");
      assert.notEqual(afterUpdate.revision, beforeUpdate.revision);
      const removed = await persisted(37, "organizer_note_delete", { id: noteId, expected_revision: afterUpdate.revision });
      assert.ok(removed.trash_id);
      assert.equal(b.t.daten().notizen.some(note => note.id === noteId), false);
      const restored = await persisted(38, "organizer_trash_restore", { id: removed.trash_id });
      assert.equal(restored.restored_id, noteId);
      assert.equal(b.t.daten().notizen.find(note => note.id === noteId).titel, "Updated fixture");
      const failedSave = call(request(32, "tools/call", { name: "organizer_note_create", arguments: { title: "Failed fixture", text: "Check state" } }));
      await new Promise(resolve => setImmediate(resolve));
      b.ack(false);
      assert.equal((await failedSave).result.structuredContent.code, "save_failed");
      const disabled = await call(request(20, "tools/call", { name: "notes_diagnostics_read" }));
      assert.equal(disabled.result.structuredContent.code, "developer_mode_disabled");
      b.t.daten().einstellungen.allgemein.entwicklermodus = true;
      const peer = { device_id: "22222222-2222-4222-8222-222222222222", fingerprint: "owned-fixture-key",
        state: "online_wifi", own_device: true, remote_own_device: true };
      b.w.App.telefonStand({ peers: [peer] });
      const diagnostic = call(request(21, "tools/call", { name: "notes_diagnostics_read" }));
      await new Promise(resolve => setImmediate(resolve));
      const nativeRead = b.messages.filter(message => message.cmd === "telefon_entwickler_diagnose").at(-1);
      assert.equal(nativeRead.kennung, peer.device_id);
      b.w.App.telefonEntwicklerDiagnose({ requestId: "wrong", kennung: peer.device_id, ok: true, diagnose: { app_version: "ignore" } });
      b.w.App.telefonEntwicklerDiagnose({ requestId: nativeRead.requestId, kennung: peer.device_id, ok: true,
        diagnose: { format: 1, app_version: "owned-diagnostic-fixture", events: [] } });
      assert.equal((await diagnostic).result.structuredContent.diagnostics.app_version, "owned-diagnostic-fixture");
      assert.ok(!JSON.stringify(b.t.daten()).includes("owned-diagnostic-fixture"));
      const revoked = call(request(22, "tools/call", { name: "notes_diagnostics_read" }));
      await new Promise(resolve => setImmediate(resolve));
      const obsoleteRead = b.messages.filter(message => message.cmd === "telefon_entwickler_diagnose").at(-1);
      b.w.App.telefonStand({ peers: [{ ...peer, fingerprint: "replacement-key" }] });
      b.w.App.telefonEntwicklerDiagnose({ requestId: obsoleteRead.requestId, kennung: peer.device_id, ok: true,
        diagnose: { app_version: "must-not-leak" } });
      const rejected = await revoked;
      assert.equal(rejected.result.structuredContent.code, "source_changed");
      assert.ok(!JSON.stringify(rejected).includes("must-not-leak"));
      const filesystem = call(request(23, "tools/call", { name: "kde_filesystem_status" }));
      await new Promise(resolve => setImmediate(resolve));
      const fsRead = b.messages.filter(message => message.cmd === "kde_dateisystem_stand").at(-1);
      b.w.App.kdeMedien({ requestId: fsRead.requestId, ok: true, devices: [] });
      assert.equal((await filesystem).result.isError, false);
      const actionsBefore = b.messages.filter(message => message.cmd === "kde_medien_aktion").length;
      const shell = await call(request(24, "tools/call", { name: "kde_media_action", arguments: {
        device_id: peer.device_id, token: "a".repeat(32), player: "fixture", action: "shell" } }));
      assert.equal(shell.error.code, -32602);
      assert.equal(b.messages.filter(message => message.cmd === "kde_medien_aktion").length, actionsBefore);
      b.w.App.init({ gesperrt: true });
      const locked = await call(request(6, "tools/call", { name: "organizer_data_read", arguments: { section: "notizen" } }));
      assert.equal(locked.result.isError, true);
      assert.equal(locked.result.structuredContent.code, "locked_or_not_ready");
      assert.ok(!JSON.stringify(locked).includes("Owned fixture"));
      const status = await call(request(7, "tools/call", { name: "organizer_status" }));
      assert.equal(status.result.structuredContent.locked, true);
      b.w.App.mcpClose(session);
      assert.equal((await call(request(8, "tools/list"))).error.code, -32002);
      console.log("MCP product reads, Notes nonce/source gates, native KDE results, typed actions, lock revocation and session cleanup PASS " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
