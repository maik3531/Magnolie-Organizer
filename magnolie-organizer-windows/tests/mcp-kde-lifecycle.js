"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP KDE lifecycle timed out"); process.exit(1); }, 15000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const hash = "a".repeat(64), state = { revision: hash, integration: "direct", running: true, owned_listener: true, listening: true, listen_port: 1716, local_id: "owned-local", local_fingerprint: "b".repeat(64), error_present: false,
        private_key: "owned-private-key", clipboard: "owned-private-clipboard", capabilities: { refresh: true, pairing: true, remove: true, receive_preferences: false, unsafe_plugin: true },
        peers: Array.from({ length: 125 }, (_, i) => ({ id: "peer-" + i, name: "Peer " + i, fingerprint: hash, paired: true, reachable: false, type: "phone", sms: "owned-private-sms" })),
        candidates: Array.from({ length: 140 }, (_, i) => ({ id: "candidate-" + i, name: "Candidate", fingerprint: null, source_token: hash, reachable: false, address: "127.0.0.1", port: 1716, password: "owned-private-candidate" })),
        pending: [{ id: "pending-peer", name: "Pending", fingerprint: hash, attempt_id: "owned-attempt", code: "12345678", expires_ms: 1900000000000, local_confirmed: false, remote_confirmed: true, private_key: "owned-private-pending" }] };
      let sequence = 0, onNative;
      const reply = (message, extra = {}) => b.w.App.kdeMcpErgebnis({ requestId: message.requestId, ok: true, status: state, action: message.request.action, localVerified: true, persisted: false, pairedVerified: false, deliveryConfirmed: false, ...extra });
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => { post(text); const message = JSON.parse(text); if (message.cmd === "kde_mcp") { if (onNative) onNative(message); else reply(message); } };
      async function rpc(method, params, id, session = "a".repeat(48)) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session, invocation, message: { jsonrpc: "2.0", method, ...(!method.startsWith("notifications/") ? { id: id ?? sequence } : {}), params } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
      }
      const call = async (name, args = {}, id, session) => (await rpc("tools/call", { name, arguments: args }, id, session)).result;
      const read = args => call("organizer_kde_connection_read", args);
      const refresh = (args, id) => call("organizer_kde_connection_refresh", args, id);
      const ok = result => { assert.equal(result?.isError, false, JSON.stringify(result)); return result.structuredContent; };
      const fail = (result, code) => { assert.equal(result?.isError, true, JSON.stringify(result)); assert.equal(result.structuredContent.code, code); };
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-kde-lifecycle", version: "1" } }); await rpc("notifications/initialized", {});
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
      const initial = ok(await read()); assert.equal(initial.peer_total, 125); assert.equal(initial.peers.length, 100); assert.equal(initial.candidate_total, 140); assert.equal(initial.candidates.length, 100); assert.equal(initial.next_offset, 100);
      assert.ok(!JSON.stringify(initial).includes("owned-private") && !Object.hasOwn(initial.capabilities, "unsafe_plugin"));
      const later = ok(await read({ offset: 130, limit: 7 })); assert.equal(later.peers.length, 0); assert.equal(later.candidates[0].id, "candidate-130"); assert.equal(later.next_offset, 137);
      let seen; onNative = message => { seen = message; reply(message); };
      assert.equal(ok(await refresh({ expected_revision: hash })).persisted, false); assert.equal(seen.request.expectedRevision, hash);
      ok(await refresh()); assert.equal(seen.request.expectedRevision, "");
      const originalPeers = state.peers, originalPending = state.pending;
      state.peers = []; state.pending = [];
      onNative = message => {
        if (message.request.action === "pairing_complete") {
          seen = message;
          state.pending = [{ id: "candidate-0", name: "Owned pending", fingerprint: hash, attempt_id: "new-owned-attempt", code: "12345678", expires_ms: 1900000000000, local_confirmed: false, remote_confirmed: false }];
        }
        reply(message);
      };
      const begun = ok(await call("organizer_kde_pairing_begin", { action: "complete", expected_revision: hash, candidate_id: "candidate-0", source_token: hash }));
      await tick();
      const pendingFlow = ok(await call("organizer_kde_pairing_status", { operation_id: begun.operation_id }));
      assert.equal(pendingFlow.phase, "pending"); assert.equal(seen.request.sourceToken, hash); assert.equal(pendingFlow.state.pending[0].attempt_id, "new-owned-attempt");
      const other = "b".repeat(48);
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "other-kde-session", version: "1" } }, undefined, other); await rpc("notifications/initialized", {}, undefined, other);
      fail(await call("organizer_kde_pairing_status", { operation_id: begun.operation_id }, undefined, other), "not_found");
      const decision = { expected_revision: hash, peer_id: "candidate-0", fingerprint: hash, attempt_id: "new-owned-attempt", accept: true };
      assert.equal(ok(await call("organizer_kde_pairing_decide", decision)).paired_verified, false);
      onNative = message => {
        if (message.request.action === "pairing_confirm") {
          state.pending = []; state.peers = [{ id: "candidate-0", name: "Paired", fingerprint: hash, paired: true, reachable: true, type: "phone" }];
          reply(message, { pairedVerified: true, persisted: true });
        } else reply(message);
      };
      assert.equal(ok(await call("organizer_kde_pairing_decide", decision)).paired_verified, true);
      assert.equal(ok(await call("organizer_kde_pairing_status", { operation_id: begun.operation_id })).phase, "paired");
      onNative = message => reply(message, { persisted: true });
      assert.equal(ok(await call("organizer_kde_connection_remove", { expected_revision: hash, peer_id: "candidate-0", fingerprint: hash })).persisted, true);
      state.peers = originalPeers; state.pending = originalPending;
      onNative = message => reply(message, { status: { ...state, integration: "system", owned_listener: false, listening: null, listen_port: null, local_id: null, local_fingerprint: null,
        candidates: [], pending: [], capabilities: { refresh: true, pairing: false, remove: false, receive_preferences: false } } });
      const system = ok(await read()); assert.equal(system.local_id, null); assert.equal(system.listening, null); assert.equal(system.capabilities.pairing, false);
      for (const code of ["profile_locked", "native_busy", "native_unavailable", "unsupported_feature", "conflict"]) { onNative = message => reply(message, { ok: false, code }); fail(await read(), code); }
      onNative = message => reply(message, { persisted: true }); fail(await refresh(), "invalid_result");
      let held;
      const waiting = new Promise(resolve => { onNative = message => { held = message; resolve(); }; });
      const pending = refresh({}, 9000); await waiting;
      b.t.oeffneEinstellungen(); await tick(); fail(await refresh(), "dialog_busy");
      const toast = b.w.document.querySelector("#zettel").textContent;
      await rpc("notifications/cancelled", { requestId: 9000 }); fail(await pending, "cancelled"); reply(held); await tick();
      assert.equal(b.w.document.querySelector("#zettel").textContent, toast); assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves);
      console.log("MCP KDE SNAPSHOT/REFRESH PASS: native integration limits, candidate/peer pages, source tokens, no private payloads, runtime receipts, modal/cancel/late gates " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
