"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP phone call actors timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) for (const scenario of ["success", "cancel_create", "cancel_start", "wrong_ref", "extra", "book_change", "draft", "session_close"]) {
    const b = await harness.exports.boot(web, {});
    try {
      if (b.saves().length) b.ack(); await tick(); b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const target = { peer_id: "11111111-1111-4111-8111-111111111111", fingerprint: "ABCD-1234-5678-90EF" }, source = "a".repeat(64);
      const reference = "22222222-2222-4222-8222-222222222222", actorId = "33333333-3333-4333-8333-333333333333", token = "b".repeat(64);
      const requests = []; let sequence = 0, held, operation, command, reported = false;
      const native = (phase = reported ? "reported" : "awaiting_phone") => {
        const result = phase === "reported" ? { state: "submitted", error: "none", occurred_ms: Date.now(),
          ...(command === "dial" ? { client_ref: operation } : { command_ref: operation, call_ref: reference }) } : null;
        if (result && scenario === "wrong_ref") (command === "dial" ? result.client_ref = b.w.crypto.randomUUID() : result.command_ref = b.w.crypto.randomUUID());
        if (result && scenario === "extra") result.private_unrequested = "must not pass";
        return { actor_id: actorId, operation_id: operation, command, phase, dispatch_started: phase !== "reserved", transport_dispatched: phase !== "reserved",
          receipt_persisted: phase !== "reserved", phone_result_received: result !== null, phone_result: result,
          cancel_requested: phase === "cancelled", remote_recall_confirmed: false, native_outcome_unknown: phase === "cancelled", error_code: phase === "cancelled" ? "cancelled" : "none" };
      };
      const reply = message => {
        const action = message.request.action;
        b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: true,
          ...(action === "call_actor_create" ? { callActorHandle: { actor_id: actorId, owner_token: token } } : {}),
          callActor: native(action === "call_actor_cancel" ? "cancelled" : action === "call_actor_create" ? "reserved" : undefined) });
      };
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text); if (message.cmd !== "telefon_mcp") return;
        const request = message.request; requests.push(request);
        if (request.action === "call_context_read") {
          queueMicrotask(() => b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: true, callContext: {
            ...target, source_revision: source, transport: "wifi", permissions: { dial_request: true, incoming_call_state: true, answer_call: true, end_call: true },
            call: { call_ref: reference, revision: "9007199254740993", state: "ringing", direction: "incoming", phone_occurred_ms: Date.now(), native_received_ms: Date.now(),
              observation: "authenticated_session_event", scope: "shared_call_state", phone_status_queried: false }, phone_status_queried: false, persisted: false } })); return;
        }
        if (request.action === "call_actor_create") { operation = request.operationId; command = request.command; reported = false; }
        if (request.action === "call_actor_create" && ["cancel_create", "session_close"].includes(scenario) || request.action === "call_actor_start" && scenario === "cancel_start") { held = message; return; }
        queueMicrotask(() => reply(message));
      };
      async function rpc(method, params, session = "a".repeat(48)) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session, invocation, message: { jsonrpc: "2.0", method, ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation)?.response;
      }
      const call = async (name, args, session) => (await rpc("tools/call", { name, arguments: args }, session)).result;
      const ok = value => { assert.equal(value?.isError, false, scenario + JSON.stringify(value)); return value.structuredContent; };
      for (const session of ["a".repeat(48), "b".repeat(48)]) {
        await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-call-actor", version: "1" } }, session);
        await rpc("notifications/initialized", {}, session);
      }
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
      const context = ok(await call("organizer_phone_call_read", target)); assert.equal(context.call.revision, "9007199254740993"); assert.equal(context.phone_status_queried, false);
      if (scenario === "draft") { b.t.oeffneTerminBlatt(null, "2026-10-20"); b.input("#tb-titel", "Owned current draft"); }
      for (const action of scenario === "success" ? ["dial", "answer", "end"] : ["dial"]) {
        const args = { ...target, expected_source_revision: source, command_id: b.w.crypto.randomUUID(), command: action,
          ...(action === "dial" ? { to: "+49301234567" } : { call_ref: reference, expected_call_revision: context.call.revision }) };
        const started = await call("organizer_phone_call_command_start", args);
        if (scenario === "draft") { assert.equal(started.structuredContent.code, "editor_busy"); assert.ok(!requests.some(value => value.action === "call_actor_create")); continue; }
        let state = ok(started); const id = state.operation_id;
        assert.equal((await call("organizer_phone_call_command_status", { operation_id: id }, "b".repeat(48))).structuredContent.code, "not_found");
        for (let n = 0; n < 100 && !held && !requests.some(value => value.action === "call_actor_start" && value.actorId === actorId); n++) await tick();
        if (["cancel_create", "cancel_start", "session_close"].includes(scenario)) {
          for (let n = 0; n < 100 && !held; n++) await tick(); assert.ok(held);
          b.t.oeffneTerminBlatt(null, "2026-10-20"); b.input("#tb-titel", "Owned late call draft");
          if (scenario === "session_close") b.w.App.mcpClose("a".repeat(48));
          else { state = ok(await call("organizer_phone_call_command_cancel", { operation_id: id })); assert.equal(state.phase, "cancelled"); }
          reply(held); await tick(); await tick();
          assert.equal(b.w.document.querySelector("#tb-titel").value, "Owned late call draft");
          assert.ok(requests.some(value => value.action === "call_actor_cancel" && value.ownerToken === token));
          if (scenario !== "cancel_start") assert.ok(!requests.some(value => value.action === "call_actor_start"));
          continue;
        }
        for (let n = 0; n < 100 && state.phase !== "awaiting_phone"; n++) { await tick(); state = ok(await call("organizer_phone_call_command_status", { operation_id: id })); }
        assert.equal(state.phase, "awaiting_phone", JSON.stringify(state)); assert.equal(state.phone_result_received, false);
        if (scenario === "book_change") b.w.App.init({ daten: JSON.parse(JSON.stringify(b.t.daten())), neu: false, regional: { language: "en", timeZone: "UTC" } });
        reported = true; state = ok(await call("organizer_phone_call_command_status", { operation_id: id }));
        if (["wrong_ref", "extra", "book_change"].includes(scenario)) {
          assert.equal(state.phase, "failed"); assert.equal(state.error_code, scenario === "book_change" ? "source_changed" : "invalid_result");
        } else {
          assert.equal(state.phase, "reported"); assert.equal(state.phone_result_received, true); assert.equal(state.receipt_persisted, true);
          assert.equal(state.remote_recall_confirmed, false); assert.ok(!JSON.stringify(state).includes(token));
        }
      }
      if (scenario !== "book_change") { assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves); }
      console.log("MCP CALL ACTOR PASS: " + scenario + " " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
