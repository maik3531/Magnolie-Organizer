"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const vectors = JSON.parse(fs.readFileSync(path.join(__dirname, "../../contracts/time-control-v13.json"), "utf8"));
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP Notes timer timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const target = { peer_id: "11111111-1111-4111-8111-111111111111", fingerprint: "ABCD-1234-5678-90EF" }, requests = [];
      const source = "c".repeat(64), operation = "33333333-3333-4333-8333-333333333333";
      let mode = "valid", held, sequence = 0;
      function result(request) {
        const body = request.body, report = structuredClone(vectors.reports[body.action === "read" ? 0 : 1]);
        report.request_id = body.request_id; report.operation_id = body.operation_id;
        if (body.action !== "read") report.applied_entry_id = body.action === "start" ? body.operation_id : body.entry_id;
        const value = { report, source_revision: source, dispatch_started: true };
        if (mode === "running" || mode === "bad_running_clock") report.entries = [{ id: operation, startMinute: 1000, endMinute: null, pauseMinute: null,
          pauseMinutes: 0, zone: "UTC", type: "Owned native timer", note: "", modifiedMs: 1000, deleted: false,
          clock: mode === "running" ? { "44444444-4444-4444-8444-444444444444": 1 } : { untrusted: 1 },
          pausePlan: { baseMinutes: 0, fixed: [], manual: [], replaced: [], fixedEnds: {} } }];
        if (mode === "wrong_nonce") report.request_id = b.w.crypto.randomUUID();
        if (mode === "wrong_source") value.source_revision = "d".repeat(64);
        if (mode === "false_save") report.persisted = false;
        if (mode === "read_save") report.persisted = true;
        if (mode === "extra") report.unknown_private_field = "must not pass";
        if (mode === "wrong_entry") report.applied_entry_id = b.w.crypto.randomUUID();
        if (mode === "extra_envelope") value.peer_id = target.peer_id;
        if (mode === "bad_clock_actor") report.applied_clock = { untrusted: 1 };
        return value;
      }
      const reply = message => b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: true, timeControl: result(message.request) });
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text); if (message.cmd !== "telefon_mcp") return;
        const request = message.request; requests.push(request);
        if (request.action === "time_control_source") {
          queueMicrotask(() => b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: mode !== "unsupported", code: "unsupported_feature", sourceRevision: source })); return;
        }
        if (request.action === "time_control_cancel") {
          queueMicrotask(() => b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: true, cancel_requested: true, remote_recall_confirmed: false })); return;
        }
        if (request.action !== "time_control_query") return;
        if (mode === "hold") { held = message; return; }
        if (mode === "book_change") b.w.App.init({ daten: JSON.parse(JSON.stringify(b.t.daten())), neu: false, regional: { language: "en", timeZone: "UTC" } });
        queueMicrotask(() => reply(message));
      };
      async function rpc(method, params) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
          ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation)?.response;
      }
      const call = async (action, extra = {}) => (await rpc("tools/call", { name: "organizer_notes_timer_" + action,
        arguments: { ...target, ...(action === "read" ? {} : { expected_source_revision: source, expected_timer_revision: "a".repeat(64),
          restore_epoch: "native-book", operation_id: operation, ...(action === "start" ? {} : { entry_id: operation }) }), ...extra } })).result;
      const ok = value => { assert.equal(value?.isError, false, JSON.stringify(value)); return value.structuredContent; };
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-timer-fixture", version: "1" } });
      await rpc("notifications/initialized", {});
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
      assert.equal(ok(await call("read")).report.persisted, false);
      mode = "running"; assert.equal(ok(await call("read")).report.entries[0].id, operation); mode = "valid";
      for (const action of ["start", "pause", "resume", "finish"]) {
        const value = ok(await call(action)); assert.equal(value.report.persisted, true); assert.equal(value.report.status, "duplicate");
        const request = requests.findLast(value => value.action === "time_control_query");
        assert.equal(request.body.action, action); assert.equal(request.sourceRevision, source);
        assert.equal(request.body.operation_id, operation); assert.equal(request.body.restore_epoch, "native-book");
        assert.equal("clock" in request.body, false); assert.equal("sent_ms" in request.body, false);
      }
      for (const [change, action] of [["wrong_nonce", "read"], ["wrong_source", "read"], ["false_save", "start"], ["read_save", "read"],
        ["extra", "read"], ["wrong_entry", "pause"], ["extra_envelope", "read"], ["bad_clock_actor", "start"], ["bad_running_clock", "read"]]) {
        mode = change; assert.equal((await call(action)).structuredContent.code, "invalid_result", change);
      }
      mode = "unsupported"; const sentBefore = requests.filter(value => value.action === "time_control_query").length;
      assert.equal((await call("read")).structuredContent.code, "unsupported_feature");
      assert.equal(requests.filter(value => value.action === "time_control_query").length, sentBefore);
      mode = "hold"; b.t.oeffneTerminBlatt(null, "2026-10-20"); b.input("#tb-titel", "Owned timer late-reply draft");
      const rpcId = sequence + 1, pending = call("start");
      for (let index = 0; index < 100 && !held; index++) await tick(); assert.ok(held);
      await rpc("notifications/cancelled", { requestId: rpcId });
      assert.equal((await pending).structuredContent.code, "cancelled");
      mode = "valid"; reply(held); await tick();
      assert.equal(b.w.document.querySelector("#tb-titel").value, "Owned timer late-reply draft");
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves);
      assert.ok(requests.some(request => request.action === "time_control_cancel" && request.requestId === held.request.body.request_id));
      assert.equal(requests.filter(request => request.action === "time_control_cancel" && request.requestId === held.request.body.request_id).length, 1);
      mode = "book_change"; assert.equal((await call("read")).structuredContent.code, "source_changed");
      console.log("MCP NOTES TIMER PASS: native source/state CAS, four actions/replay, strict reports, cancellation and late draft safety " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
