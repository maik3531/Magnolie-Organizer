"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP provider conflicts timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    const windows = fs.existsSync(path.resolve(web, "../../Directory.Build.props")), field = windows ? "syncKonflikte" : "kontaktProviderKonflikte", source = "generic-dav-addressbook:owned";
    for (const mode of ["keep", "merge", "replace", "snapshot_failed", "stale", "save_failed", "cancel", "platform_options", ...(!windows ? ["deleted"] : [])]) {
      const incoming = { uid: "provider-record", vorname: "Remote", nachname: "Person", notiz: "Remote note", telefone: [{ wert: "+49305550124", typen: ["CELL"] }], vcardRoundtrip: ["X-OWNED:remote"] };
      const conflict = { kontakt: incoming, transport: mode === "deleted" ? "eds" : "dav", entfernt: mode === "deleted", mapping: { id: "provider-record", etag: '"v2"', inhaltFormat: "owned-format", inhaltSha256: "owned-digest" } };
      const b = await harness.exports.boot(web, { kontakte: [{ id: "local", uid: "stable-local", vorname: "Local", nachname: "Person", notiz: "Local note", sync: true,
        telefone: [{ wert: "+49305550123", typen: ["CELL"] }], vcardRoundtrip: ["X-OWNED:local"], syncQuellen: { [source]: { id: "provider-record", etag: '"v1"' }, unrelated: { id: "preserve", etag: "other-version" } }, [field]: { [source]: conflict } },
        { id: "other", uid: "other-uid", vorname: "Other", nachname: "Person", notiz: "Keep unrelated" }] });
      try {
        if (b.saves().length) b.ack(); await tick();
        b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
        let sequence = 0, snapshotMessage, onSnapshot, onSave;
        const post = b.w.webkit.messageHandlers.regression.postMessage;
        b.w.webkit.messageHandlers.regression.postMessage = text => {
          post(text); const message = JSON.parse(text);
          if (message.cmd === "speichern") { if (onSave) onSave(message); else queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true })); }
          if (message.cmd === "mutations_snapshot") {
            snapshotMessage = message;
            if (onSnapshot) onSnapshot(message); else queueMicrotask(() => b.w.App.mutationsSnapshot({ token: message.token, ok: true }));
          }
        };
        async function rpc(method, params, id) {
          const invocation = (++sequence).toString(16).padStart(48, "0");
          await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
            ...(!method.startsWith("notifications/") ? { id: id ?? sequence } : {}), ...(params === undefined ? {} : { params }) } });
          return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
        }
        const tool = async (name, args, id) => (await rpc("tools/call", { name, arguments: args }, id)).result;
        const read = args => tool("organizer_contact_provider_conflict_read", { contact_id: "local", source_id: source, ...args });
        const ok = result => { assert.equal(result?.isError, false, JSON.stringify(result)); return result.structuredContent; };
        const fail = (result, code) => { assert.equal(result?.isError, true, JSON.stringify(result)); assert.equal(result.structuredContent.code, code); };
        await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-provider-review", version: "1" } }); await rpc("notifications/initialized", {});
        const before = JSON.stringify(b.t.daten().kontakte), other = JSON.stringify(b.t.daten().kontakte[1]);
        const view = ok(await read()); assert.equal(JSON.stringify(b.t.daten().kontakte), before); assert.equal(view.options.extra_arrays, windows); assert.equal(view.can_use_newer, false);
        assert.equal(view.incoming_list_counts.telefone, mode === "deleted" ? 0 : 1);
        const resolve = (args = {}, id) => tool("organizer_contact_provider_conflict_resolve", { contact_id: "local", source_id: source, expected_revision: view.revision,
          decision: ["keep", "merge", "replace"].includes(mode) ? mode : "keep", ...args }, id);
        fail(await resolve({ expected_revision: "0".repeat(64) }), "conflict"); assert.equal(snapshotMessage, undefined);
        fail(await read({ source_id: "__proto__" }), "not_found");
        if (mode !== "deleted") { fail(await resolve({ decision: "newer" }), "invalid_selection"); assert.equal(snapshotMessage, undefined); }
        if (mode === "snapshot_failed") onSnapshot = message => queueMicrotask(() => b.w.App.mutationsSnapshot({ token: message.token, ok: false }));
        if (mode === "stale") onSnapshot = message => queueMicrotask(() => { b.t.daten().kontakte[0].notiz = "Concurrent change"; b.w.App.mutationsSnapshot({ token: message.token, ok: true }); });
        if (mode === "save_failed") onSave = message => queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: !!b.t.daten().kontakte[0][field] }));
        if (mode === "platform_options") {
          if (windows) {
            fail(await resolve({ decision: "replace", preserve_birth_name: true }), "unsupported_feature");
            const result = await resolve({ decision: "merge", fields: [{ field: "vorname", choice: "incoming" }], extras: [{ field: "vcardRoundtrip", choice: "incoming" }] });
            ok(result); assert.ok(b.t.daten().kontakte[0].vcardRoundtrip.includes("X-OWNED:remote"));
          } else fail(await resolve({ decision: "merge", clear_lists: ["telefone"] }), "unsupported_feature");
          continue;
        }
        const args = mode === "merge" ? { fields: [{ field: "vorname", choice: "incoming" }], lists: [{ field: "telefone", incoming_index: 0, choice: "replace", existing_index: 0 }] } : {};
        if (mode === "cancel") {
          let notify;
          const waiting = new Promise(resolve => { notify = resolve; }); onSnapshot = () => notify();
          const pending = resolve(args, 9000); await waiting;
          await rpc("notifications/cancelled", { requestId: 9000 }); fail(await pending, "cancelled");
          b.w.App.mutationsSnapshot({ token: snapshotMessage.token, ok: true }); await tick();
          assert.equal(JSON.stringify(b.t.daten().kontakte), before); continue;
        }
        const result = await resolve(args);
        if (mode === "snapshot_failed") fail(result, "snapshot_failed");
        else if (mode === "stale") fail(result, "conflict");
        else if (mode === "save_failed") fail(result, "save_failed");
        else { const saved = ok(result); assert.equal(saved.persisted, true); assert.equal(saved.remote_write_performed, false); assert.equal(saved.remaining_conflicts, 0); }
        const local = b.t.daten().kontakte[0]; assert.equal(local.id, "local"); assert.equal(local.uid, "stable-local"); assert.equal(JSON.stringify(b.t.daten().kontakte[1]), other);
        if (["snapshot_failed", "stale"].includes(mode)) { assert.ok(local[field]?.[source]); assert.equal(local.syncQuellen[source].etag, '"v1"'); }
        else {
          assert.equal(local[field], undefined); assert.equal(local.syncQuellen[source].etag, '"v2"'); assert.equal(local.syncQuellen.unrelated.id, "preserve");
          assert.equal(local.vorname, ["merge", "replace"].includes(mode) ? "Remote" : "Local");
          if (mode === "deleted") { assert.equal(local.syncQuellen[source].inhaltSha256, ""); assert.equal(local.syncQuellen[source].pruefungFreigegeben, true); }
        }
        assert.ok(!b.messages.some(message => message.cmd === "sync" || message.cmd === "sync_start"));
      } finally { b.close(); }
    }
    console.log("MCP PROVIDER CONFLICT PASS: existing platform decision builders, source approval, identity retention, snapshot/CAS/save/cancel gates " + web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
