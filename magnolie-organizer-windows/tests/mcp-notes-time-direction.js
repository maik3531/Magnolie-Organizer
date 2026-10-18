"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("Notes time-direction test timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    for (const scenario of ["success", "inactive", "save_failed", "cancel", "source_changed", "modern", "stale", "draft"]) {
      const b = await harness.exports.boot(web, {});
      try {
        if (b.saves().length) b.ack(); await tick();
        b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
        const target = { peer_id: "11111111-1111-4111-8111-111111111111", fingerprint: "ABCD-1234-5678-90EF" };
        const state = { ...target, revision: "a".repeat(64), own_device: true, remote_own_device: true, auto_wifi: false, skip_deletions: true,
          note_direction: { supported: true, local_mode: "phone_import" }, policies: { custom: { supported: true, local_enabled: false }, time: { supported: true, local_enabled: scenario !== "inactive" } },
          shared: { supported: scenario === "modern", initialized: false, ready: false, values: null } };
        let sequence = 0, saved = false, held; const resets = [];
        const post = b.w.webkit.messageHandlers.regression.postMessage;
        const reply = message => {
          const r = message.request;
          if (r.action === "notes_legacy_policy") {
            state.revision = (r.enabled ? "c" : "b").repeat(64); state.policies.time.local_enabled = r.enabled;
          }
          b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: true, notesSettings: JSON.parse(JSON.stringify(state)), action: r.action,
            localVerified: true, persisted: true, deliveryConfirmed: false });
        };
        b.w.webkit.messageHandlers.regression.postMessage = text => {
          post(text); const m = JSON.parse(text);
          if (m.cmd === "speichern") queueMicrotask(() => { saved = scenario !== "save_failed"; b.w.App.gespeichert({ id: m.id, ok: saved }); });
          if (m.cmd !== "telefon_mcp") return;
          if (m.request.action === "notes_legacy_policy") {
            assert.equal(saved, true, "native policy must not reset before actual book SaveACK"); resets.push(m.request);
            if (scenario === "cancel") { held = m; return; }
            if (scenario === "source_changed") b.t.daten().einstellungen.allgemein.ownedConcurrentChange = true;
          }
          queueMicrotask(() => reply(m));
        };
        async function rpc(method, params, session = "a".repeat(48)) {
          const invocation = (++sequence).toString(16).padStart(48, "0");
          await b.w.App.mcpRequest({ session, invocation, message: { jsonrpc: "2.0", method,
            ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
          return b.messages.find(m => m.cmd === "mcp_antwort" && m.invocation === invocation)?.response;
        }
        const call = async (suffix, args, session) => (await rpc("tools/call", { name: "organizer_notes_legacy_time_direction_" + suffix, arguments: args }, session)).result;
        const ok = result => { assert.equal(result?.isError, false, scenario + JSON.stringify(result)); return result.structuredContent; };
        for (const session of ["a".repeat(48), "b".repeat(48)]) {
          await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-notes-time-direction", version: "1" } }, session);
          await rpc("notifications/initialized", {}, session);
        }
        const initial = ok(await call("read", target)), savesBefore = b.saves().length;
        if (scenario === "draft") { b.t.oeffneTerminBlatt(null, "2026-10-19"); b.input("#tb-titel", "Owned draft"); }
        const started = await call("start", { ...target, expected_book_revision: scenario === "stale" ? "0".repeat(64) : initial.book_revision,
          expected_notes_revision: initial.state.revision, mode: "two_way" });
        if (["modern", "stale", "draft"].includes(scenario)) {
          assert.equal(started.isError, true); assert.equal(started.structuredContent.code, { modern: "unsupported_feature", stale: "conflict", draft: "editor_busy" }[scenario]);
          assert.equal(b.saves().length, savesBefore); assert.equal(resets.length, 0); continue;
        }
        let status = ok(started); const operation_id = status.operation_id;
        const other = await call("status", { operation_id }, "b".repeat(48)); assert.equal(other.structuredContent.code, "not_found");
        for (let n = 0; n < 100 && !["completed", "failed", "cancelled"].includes(status.phase); n++) {
          await tick();
          if (scenario === "cancel" && held) {
            b.t.oeffneTerminBlatt(null, "2026-10-19"); b.input("#tb-titel", "Owned late-reply draft");
            ok(await call("cancel", { operation_id })); reply(held); held = null;
          }
          status = ok(await call("status", { operation_id }));
        }
        if (["success", "inactive"].includes(scenario)) {
          assert.equal(status.phase, "completed", JSON.stringify(status)); assert.equal(status.book_persisted, true); assert.equal(status.policy_reset, scenario === "success");
          assert.deepEqual(resets.map(r => r.enabled), scenario === "success" ? [false, true] : []);
          assert.equal(JSON.parse(b.saves().at(-1).text).einstellungen.sync.timeDirections[target.peer_id], "two_way");
        } else {
          assert.equal(status.phase, scenario === "cancel" ? "cancelled" : "failed", JSON.stringify(status));
          assert.equal(status.book_persisted, scenario !== "save_failed"); assert.equal(resets.length, scenario === "save_failed" ? 0 : 1);
          if (scenario === "cancel") {
            assert.equal(status.native_outcome_unknown, true);
            assert.equal(b.w.document.querySelector("#tb-titel").value, "Owned late-reply draft");
          }
        }
        assert.equal(status.delivery_confirmed, false);
      } finally { b.close(); }
    }
    console.log("MCP NOTES TIME DIRECTION PASS: session-owned jobs, dual CAS, actual SaveACK before native resets, partial/cancel/late-draft safety " + web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
