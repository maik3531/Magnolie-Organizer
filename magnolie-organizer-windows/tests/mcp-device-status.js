"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP device status timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const peer = "11111111-1111-4111-8111-111111111111", fingerprint = "ABCD-1234-5678-90EF", requests = [];
      const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "resources/telefon-control-contract.json"), "utf8")).device_status_v3;
      let mode = "valid", held = null;
      function result(request) {
        const report = { ...fixture, request_id: request.queryId, captured_ms: Date.now() };
        const version = request.includeIdentifiers || mode === "unrequested" ? 4 : 3;
        if (version === 4) Object.assign(report, { version: 4, identifiers: {
          phone_number: { status: "permission_missing", value: "" }, serial: { status: "os_restricted", value: "" }, imei: { status: "available", value: "000000000000001" } } });
        const data = { peer_id: peer, fingerprint, transport: "wifi", protocol_version: version, received_ms: Date.now(), expires_ms: Date.now() + 30000,
          include_identifiers: request.includeIdentifiers, report, source_verified: true, request_correlated: true, persisted: false };
        if (mode === "wrong_nonce") report.request_id = b.w.crypto.randomUUID();
        if (mode === "wrong_peer") data.fingerprint = "FFFF-1234-5678-90EF";
        if (mode === "expired") data.expires_ms = Date.now() - 1;
        if (mode === "extra_field") report.private_unknown = "owned-private-should-not-pass";
        return data;
      }
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd !== "telefon_mcp") return;
        requests.push(message.request);
        if (message.request.action === "device_status_cancel") { queueMicrotask(() => b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: true, cancelled: true })); return; }
        if (message.request.action !== "device_status_query") return;
        if (mode === "hold") { held = message; return; }
        queueMicrotask(() => b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: true, deviceStatus: result(message.request) }));
      };
      let sequence = 0;
      async function rpc(method, params) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method, ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation)?.response;
      }
      const args = { expected_revision: "c".repeat(64), peer_id: peer, fingerprint };
      const call = async values => (await rpc("tools/call", { name: "organizer_phone_device_status_read", arguments: { ...args, ...values } })).result;
      const ok = value => { assert.equal(value?.isError, false, JSON.stringify(value)); return value.structuredContent; };
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-status-fixture", version: "1" } }); await rpc("notifications/initialized", {});
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
      const ordinary = ok(await call({}));
      assert.equal(requests.at(-1).includeIdentifiers, false); assert.equal(ordinary.identifiers, null); assert.equal(ordinary.protocol_version, 3);
      assert.equal(ordinary.status.app_version, fixture.app_version); assert.equal(ordinary.persisted, false);
      const explicit = ok(await call({ include_identifiers: true })); assert.equal(explicit.identifiers.imei.value, "000000000000001");
      for (const [change, code] of [["wrong_nonce", "source_changed"], ["wrong_peer", "source_changed"], ["expired", "source_changed"], ["extra_field", "invalid_result"], ["unrequested", "source_changed"]]) {
        mode = change; const invalid = await call({}); assert.equal(invalid.structuredContent.code, code, change);
        await tick(); assert.equal(requests.at(-1).action, "device_status_cancel");
      }
      mode = "hold"; b.t.oeffneTerminBlatt(null, "2026-10-18"); b.input("#tb-titel", "Owned GUI draft must survive");
      const rpcId = sequence + 1, pending = call({ include_identifiers: true });
      for (let index = 0; index < 100 && !held; index++) await tick(); assert.ok(held);
      await rpc("notifications/cancelled", { requestId: rpcId }); const cancelled = await pending;
      assert.equal(cancelled.structuredContent.code, "cancelled");
      mode = "valid"; b.w.App.telefonMcpErgebnis({ requestId: held.requestId, ok: true, deviceStatus: result(held.request) }); await tick();
      assert.equal(b.w.document.querySelector("#tb-titel").value, "Owned GUI draft must survive");
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves);
      assert.ok(requests.some(request => request.action === "device_status_cancel" && request.queryId === held.request.queryId));
      console.log("MCP DEVICE STATUS PASS: default privacy, explicit IDs, strict peer/nonce/version/expiry/schema, cancellation and late GUI draft safety " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
