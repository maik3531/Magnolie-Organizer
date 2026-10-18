"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP KDE pairing jobs timed out"); process.exit(1); }, 15000);
(async () => {
  for (const web of harness.exports.roots) {
    for (const mode of ["close", "timeout", "unsupported", "false_persistence"]) {
      const b = await harness.exports.boot(web, {});
      try {
        if (b.saves().length) b.ack(); await tick();
        b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
        const hash = "a".repeat(64), owner = "a".repeat(48);
        const state = { revision: hash, integration: "direct", running: true, owned_listener: true, listening: true, listen_port: 1716, local_id: "owned-local", local_fingerprint: hash,
          error_present: false, capabilities: { refresh: true, pairing: true, remove: true, receive_preferences: false }, peers: [], candidates: [],
          pending: [{ id: "owned-candidate", name: "Owned candidate", fingerprint: hash, attempt_id: "owned-attempt", code: "12345678", expires_ms: 1900000000000, local_confirmed: false, remote_confirmed: false }] };
        let sequence = 0, held;
        const post = b.w.webkit.messageHandlers.regression.postMessage;
        b.w.webkit.messageHandlers.regression.postMessage = text => {
          post(text); const message = JSON.parse(text);
          if (message.cmd !== "kde_mcp") return;
          held = message;
          if (mode === "unsupported") b.w.App.kdeMcpErgebnis({ requestId: message.requestId, ok: false, code: "unsupported_feature" });
          if (mode === "false_persistence") b.w.App.kdeMcpErgebnis({ requestId: message.requestId, ok: true, status: state, action: message.request.action, localVerified: true, persisted: true, pairedVerified: false, deliveryConfirmed: false });
        };
        async function rpc(method, params, session = owner) {
          const invocation = (++sequence).toString(16).padStart(48, "0");
          await b.w.App.mcpRequest({ session, invocation, message: { jsonrpc: "2.0", method, ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
          return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
        }
        const call = async (name, args, session) => (await rpc("tools/call", { name, arguments: args }, session)).result;
        const ok = result => { assert.equal(result?.isError, false, JSON.stringify(result)); return result.structuredContent; };
        const initialize = async session => { await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-kde-job", version: "1" } }, session); await rpc("notifications/initialized", {}, session); };
        await initialize(owner);
        const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
        const job = ok(await call("organizer_kde_pairing_begin", { action: "begin", expected_revision: hash, candidate_id: "owned-candidate", source_token: hash }));
        await tick(); assert.ok(held, "Begin did not dispatch the actual native request");
        if (mode === "timeout") for (const timer of b.timers.filter(timer => timer.delay === 25000)) timer.fn();
        if (mode === "close") {
          const toast = b.w.document.querySelector("#zettel").textContent;
          b.w.App.mcpClose(owner); await tick();
          b.w.App.kdeMcpErgebnis({ requestId: held.requestId, ok: true, status: state, action: held.request.action, localVerified: true, persisted: false, pairedVerified: false, deliveryConfirmed: false });
          await tick(); await initialize(owner);
          const result = await call("organizer_kde_pairing_status", { operation_id: job.operation_id });
          assert.equal(result.isError, true); assert.equal(result.structuredContent.code, "not_found");
          assert.equal(b.w.document.querySelector("#zettel").textContent, toast); assert.equal(b.w.document.querySelectorAll(".eingabe-schleier").length, 0);
        } else {
          let result;
          for (let i = 0; i < 50; i++) {
            await tick(); result = ok(await call("organizer_kde_pairing_status", { operation_id: job.operation_id }));
            if (result.phase !== "dispatching") break;
          }
          assert.equal(result.phase, "failed");
          assert.equal(result.error_code, ({ timeout: "native_timeout", unsupported: "unsupported_feature", false_persistence: "invalid_result" })[mode]);
          assert.equal(result.native_outcome_unknown, mode !== "unsupported"); assert.equal(result.paired_verified, false);
        }
        assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves);
      } finally { b.close(); }
    }
    console.log("MCP KDE PAIR JOB PASS: asynchronous dispatch, session cleanup, ignored late replies, timeout uncertainty, unsupported and invalid-store receipts " + web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
