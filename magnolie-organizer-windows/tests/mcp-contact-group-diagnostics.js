"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP contact-group diagnostics timed out"); process.exit(1); }, 30000);
const fingerprint = "a".repeat(64), device = "11111111-1111-4111-8111-111111111111";
const stand = { deviceId: "notes:" + device, fingerprint, uid: "native-private-uid", groups: ["Family"] };

async function run(web, mode) {
  const b = await harness.exports.boot(web, { kontakte: [{ id: "local", vorname: "Synthetic", telefonGruppenStand: stand,
    vcardRoundtrip: ["CATEGORIES:Family"] }], einstellungen: { allgemein: { entwicklermodus: mode !== "disabled" }, adressen: { foto: false } } });
  try {
    b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
    const peer = { device_id: device, state: "online_wifi", own_device: true, remote_own_device: true,
      contacts_fingerprint: fingerprint, capabilities: { items: { device_status: { available: true, versions: mode === "old" ? [5, 17] : [5, 17, 18] } } } };
    b.w.App.telefonStand({ enabled: true, peers: [peer], kdeconnect: {} });
    const requests = [];
    const post = b.w.webkit.messageHandlers.regression.postMessage;
    b.w.webkit.messageHandlers.regression.postMessage = text => {
      post(text); const request = JSON.parse(text);
      if (request.cmd !== "telefon_kontaktgruppen") return;
      requests.push(request);
      assert.equal(request.action, "diagnostics"); assert.equal(request.uid, stand.uid);
      assert.equal(request.device_id, stand.deviceId); assert.equal(request.fingerprint, fingerprint);
      assert.ok(!("groups" in request) && !("token" in request), "A diagnostic must not carry a membership replacement or ticket");
      queueMicrotask(() => {
        if (mode === "source-changed") b.w.App.telefonStand({ enabled: true, peers: [{ ...peer, contacts_fingerprint: "b".repeat(64) }], kdeconnect: {} });
        const result = { ok: true, version: 18, requestId: request.requestId, device_id: stand.deviceId,
          fingerprint, uid: stand.uid, action: "diagnostics", state: "failed", stage: "groups",
          error_type: "IllegalArgumentException", reason: "contact_groups_unknown", raw_count: 1, version_count: 1,
          account_count: 1, mime_supported: false, reader_complete: true,
          account: { name: "private-must-not-leak@example.invalid" }, token: "private-must-not-leak" };
        if (mode === "bad-count") result.raw_count = true;
        if (mode === "wrong-uid") result.uid = "other-native-uid";
        if (mode === "fake-success") result.state = "available";
        b.w.App.kontaktGruppenErgebnis(result);
      });
    };
    let sequence = 0;
    async function rpc(method, params) {
      const invocation = (++sequence).toString(16).padStart(48, "0");
      await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
        ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
      return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation)?.response;
    }
    await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-group-diagnostics", version: "1" } });
    await rpc("notifications/initialized", {});
    const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
    const response = (await rpc("tools/call", { name: "notes_contact_groups_diagnostics_read", arguments: { id: "local" } })).result;
    if (mode === "valid") {
      assert.equal(response.isError, false, JSON.stringify(response));
      assert.equal(response.structuredContent.diagnostics.stage, "groups");
      assert.equal(response.structuredContent.diagnostics.raw_count, 1);
      assert.ok(!JSON.stringify(response).includes("private-must-not-leak"));
      assert.ok(!JSON.stringify(response).includes(stand.uid));
    } else {
      assert.equal(response.isError, true, mode);
      assert.equal(response.structuredContent.code, mode === "source-changed" ? "source_changed" : "diagnostics_unavailable");
    }
    assert.equal(requests.length, ["disabled", "old"].includes(mode) ? 0 : 1);
    assert.equal(JSON.stringify(b.t.daten()), before, "Reading diagnostics changed contact content or pending intent");
    assert.equal(b.saves().length, saves, "Reading diagnostics created a book save");
    await tick();
  } finally { b.close(); }
}
(async () => {
  for (const web of harness.exports.roots) {
    for (const mode of ["valid", "disabled", "old", "source-changed", "bad-count", "wrong-uid", "fake-success"]) await run(web, mode);
    console.log("MCP CONTACT GROUP DIAGNOSTICS PASS: " + web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
