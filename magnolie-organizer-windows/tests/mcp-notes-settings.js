"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const target = { peer_id: "11111111-1111-4111-8111-111111111111", fingerprint: "ABCD-1234-5678-90EF" };
      const initial = { content_mode: "phone_scope", auto_mode: "manual", skip_deletions: true, custom_enabled: false, time_enabled: false, time_mode: "phone_import" };
      let state = { ...target, revision: "a".repeat(64), own_device: false, remote_own_device: false, auto_wifi: false, shared: { supported: true, initialized: false, ready: false, values: null } };
      const requests = []; let mode = "ok";
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const m = JSON.parse(text); if (m.cmd !== "telefon_mcp") return;
        const r = m.request; requests.push(r);
        if (r.action === "notes_settings_update") state = { ...state, revision: "b".repeat(64), own_device: true, auto_wifi: r.value === "wifi", shared: { supported: true, initialized: true, ready: false, values: { ...initial, [r.field]: r.value } } };
        if (r.action === "notes_ownership") state = { ...state, revision: "c".repeat(64), own_device: r.enabled, auto_wifi: r.enabled && state.shared.values?.auto_mode === "wifi" };
        const payload = { requestId: m.requestId, ok: true, notesSettings: { ...state } };
        if (["notes_settings_update", "notes_ownership"].includes(r.action)) Object.assign(payload, { action: r.action, localVerified: true, persisted: mode !== "unverified", deliveryConfirmed: false });
        if (mode === "wrong_peer") payload.notesSettings.fingerprint = "0000-0000-0000-0000";
        if (mode === "invalid_schema") payload.notesSettings.shared = { ...state.shared, ready: "yes" };
        queueMicrotask(() => b.w.App.telefonMcpErgebnis(payload));
      };
      let seq = 0;
      async function rpc(method, params) {
        const invocation = (++seq).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method, ...(!method.startsWith("notifications/") ? { id: seq } : {}), params } });
        return b.messages.find(m => m.cmd === "mcp_antwort" && m.invocation === invocation)?.response;
      }
      const call = async (name, args = {}) => { const response = await rpc("tools/call", { name: "organizer_notes_settings_" + name, arguments: { ...target, ...args } }); return response.result || { isError: true, error: response.error }; };
      const ok = value => { assert.equal(value?.isError, false, JSON.stringify(value)); return value.structuredContent; };
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-notes-settings", version: "1" } }); await rpc("notifications/initialized", {});
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
      assert.equal(ok(await call("read")).own_device, false);
      const args = { expected_revision: "a".repeat(64), initial, field: "auto_mode", value: "wifi" };
      const saved = ok(await call("update", args)); assert.equal(saved.persisted, true); assert.equal(saved.state.shared.values.auto_mode, "wifi");
      assert.equal(requests.at(-1).action, "notes_settings_update"); assert.deepEqual(requests.at(-1).initial, initial);
      const count = requests.length;
      const invalid = await call("update", { ...args, field: "skip_deletions", value: "false" }); assert.equal(invalid.isError, true); assert.equal(requests.length, count);
      mode = "wrong_peer"; assert.equal((await call("read")).structuredContent.code, "source_changed");
      mode = "unverified"; assert.equal((await call("update", args)).structuredContent.code, "invalid_result");
      mode = "invalid_schema"; assert.equal((await call("read")).isError, true);
      mode = "ok";
      const ownedCall = async own_device => (await rpc("tools/call", { name: "organizer_notes_ownership_update", arguments: { ...target, expected_revision: state.revision, own_device } })).result;
      const withdrawn = ok(await ownedCall(false)); assert.equal(withdrawn.state.own_device, false); assert.equal(withdrawn.state.auto_wifi, false);
      const confirmed = ok(await ownedCall(true)); assert.equal(confirmed.state.own_device, true); assert.equal(confirmed.state.auto_wifi, true);
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves);
      console.log("MCP NOTES SETTINGS PASS: typed controls, explicit initial choices, exact target, local receipts and unchanged book " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
