"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP Microsoft sign-in timed out"); process.exit(1); }, 20000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const owner = "a".repeat(48), other = "b".repeat(48), clientId = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
      let sequence = 0, onStart, onStatus, onCancel;
      const native = new Map();
      const base = message => ({ requestId: message.requestId, ok: true, flowId: message.flowId, clientId, state: "starting", userCode: "", verificationUri: "", expiresAt: 0,
        errorCode: "none", persistenceVerified: false, tokenStorageMayHaveChanged: false, browserAccepted: null, cancellationRequested: false,
        deviceCode: "owned-private-device", accessToken: "owned-private-access", refreshToken: "owned-private-refresh" });
      const reply = (message, extra = {}) => b.w.App.graphAnmeldeVorgang({ ...base(message), ...native.get(message.flowId), ...extra, requestId: message.requestId });
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern") queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true }));
        if (message.cmd === "baum_briefkasten_status") queueMicrotask(() => b.w.App.baumBriefkastenStatus({ requestId: message.requestId || "",
          kontoArt: "nextcloud", davAktiv: false, briefkastenAktiv: false, url: "https://owned.example.test", benutzer: "owned-reader", kennwortVorhanden: false, zustand: "inaktiv", fehler: "", fehlerCode: "none" }));
        if (message.cmd === "graph_mcp_start") {
          native.set(message.flowId, base(message));
          if (onStart) onStart(message); else reply(message);
        }
        if (message.cmd === "graph_mcp_status") { if (onStatus) onStatus(message); else reply(message); }
        if (message.cmd === "graph_mcp_cancel") {
          if (onCancel) onCancel(message); else {
            if (native.has(message.flowId)) native.set(message.flowId, { ...base(message), state: "cancelled", errorCode: "cancelled", cancellationRequested: true });
            reply(message);
          }
        }
      };
      async function rpc(method, params, session = owner, explicitId) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session, invocation, message: { jsonrpc: "2.0", method,
          ...(!method.startsWith("notifications/") ? { id: explicitId ?? sequence } : {}), ...(params === undefined ? {} : { params }) } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation)?.response ?? null;
      }
      const call = async (suffix, args, session = owner, id) => (await rpc("tools/call", { name: "organizer_microsoft_sign_in_" + suffix, arguments: args }, session, id))?.result ?? null;
      const begin = (options = {}, session = owner, id) => call("begin", { expected_client_id: clientId, ...options }, session, id);
      const read = (id, session = owner, requestId) => call("read", { flow_id: id }, session, requestId);
      const cancel = id => call("cancel", { flow_id: id });
      const ok = result => { assert.equal(result?.isError, false, JSON.stringify(result)); return result.structuredContent; };
      const fail = (result, code) => { assert.equal(result?.isError, true, JSON.stringify(result)); assert.equal(result.structuredContent.code, code); };
      for (const session of [owner, other]) {
        await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-signin-probe", version: "1" } }, session);
        await rpc("notifications/initialized", {}, session);
      }
      const before = JSON.stringify(b.t.daten()), saveCount = b.saves().length;
      let startMessage, completed = false;
      const started = new Promise(resolve => { onStart = message => { startMessage = message; resolve(); }; });
      const pendingBegin = begin().then(result => { completed = true; return result; }); await started;
      assert.equal(startMessage.expectedClientId, clientId); assert.equal(startMessage.openBrowser, false);
      reply({ ...startMessage, requestId: "wrong-id" }); await tick(); assert.equal(completed, false);
      reply(startMessage); onStart = null;
      const first = ok(await pendingBegin), id = first.flow_id;
      assert.match(id, /^[a-f0-9]{48}$/); assert.equal(first.state, "starting"); assert.equal(first.persistence_verified, false);
      assert.ok(!JSON.stringify(first).includes("owned-private"));
      const readCount = b.messages.filter(message => message.cmd === "graph_mcp_status").length;
      fail(await read(id, other), "not_found"); assert.equal(b.messages.filter(message => message.cmd === "graph_mcp_status").length, readCount);
      fail(await begin(), "native_busy");
      native.set(id, { ...base({ flowId: id }), state: "pending", userCode: "OWNED-CODE", verificationUri: "https://microsoft.com/devicelogin", expiresAt: 1900000000 });
      assert.equal(ok(await read(id)).user_code, "OWNED-CODE");
      for (const bad of [{ persistenceVerified: true }, { verificationUri: "http://owned.example.test" }, { expiresAt: -1 }, { clientId: "f".repeat(36) }, { clientId: 5 }, { errorCode: "owned-private-error" }]) {
        onStatus = message => reply(message, bad); fail(await read(id), "invalid_result");
      }
      onStatus = null;
      assert.equal(ok(await cancel(id)).state, "cancelled"); assert.equal(ok(await read(id)).persistence_verified, false);
      let browserStart;
      onStart = message => { browserStart = message; reply(message); };
      const browser = ok(await begin({ open_browser: true })); onStart = null;
      assert.equal(browserStart.openBrowser, true); assert.notEqual(browser.flow_id, id);
      native.set(browser.flow_id, { ...base({ flowId: browser.flow_id }), state: "succeeded", persistenceVerified: true, tokenStorageMayHaveChanged: true, browserAccepted: false });
      assert.equal(ok(await read(browser.flow_id)).persistence_verified, true);
      onCancel = message => reply(message, { cancellationRequested: false });
      assert.equal(ok(await cancel(browser.flow_id)).state, "succeeded"); onCancel = null;
      for (const code of ["unsupported_feature", "not_configured", "conflict", "native_busy", "profile_locked"]) {
        onStart = message => reply(message, { ok: false, code });
        fail(await begin(), code === "profile_locked" ? "locked_or_cancelled" : code);
      }
      onStart = null;
      const expiry = ok(await begin());
      const expiryTimer = b.timers.filter(timer => timer.delay === 21 * 60 * 1000 && !timer.cancelled).at(-1);
      assert.ok(expiryTimer); expiryTimer.fn(); fail(await read(expiry.flow_id), "not_found");
      let held;
      const heldStart = new Promise(resolve => { onStart = message => { held = message; resolve(); }; });
      const cancelledBegin = begin({}, owner, 8000); await heldStart;
      await rpc("notifications/cancelled", { requestId: 8000 }); fail(await cancelledBegin, "cancelled");
      assert.ok(b.messages.some(message => message.cmd === "graph_mcp_cancel" && message.flowId === held.flowId));
      reply(held); onStart = null; await tick();
      const modalFlow = ok(await begin());
      b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-sync").click(); await tick();
      const draft = b.w.document.querySelector("#briefkasten-url"), password = b.w.document.querySelector("#briefkasten-kennwort");
      draft.value = "https://owned-unsaved.example.test"; password.value = "owned-unsaved-secret";
      fail(await begin(), "dialog_busy");
      let heldRead;
      const reading = new Promise(resolve => { onStatus = message => { heldRead = message; resolve(); }; });
      const cancelledRead = read(modalFlow.flow_id, owner, 8100); await reading;
      await rpc("notifications/cancelled", { requestId: 8100 }); fail(await cancelledRead, "cancelled");
      const refreshes = b.messages.filter(message => message.cmd === "eds_status").length, toast = b.w.document.querySelector("#zettel").textContent;
      reply(heldRead); onStatus = null; await tick();
      assert.equal(draft.value, "https://owned-unsaved.example.test"); assert.equal(password.value, "owned-unsaved-secret");
      assert.equal(b.w.document.querySelector("#zettel").textContent, toast); assert.equal(b.messages.filter(message => message.cmd === "eds_status").length, refreshes);
      ok(await cancel(modalFlow.flow_id)); b.w.document.querySelector("#einstellungen-zu").click();
      const closeStarted = new Promise(resolve => { onStart = message => { held = message; resolve(); }; });
      const closing = begin({}, owner, 8200); await closeStarted;
      b.w.App.mcpClose(owner); assert.equal(await closing, null);
      assert.ok(b.messages.some(message => message.cmd === "graph_mcp_cancel" && message.flowId === held.flowId));
      reply(held); onStart = null; await tick();
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saveCount);
      assert.ok(!b.messages.some(message => ["graph_anmelden", "graph_abmelden", "sync", "sync_start"].includes(message.cmd)));
      console.log("MCP MICROSOFT SIGN-IN PASS: owner-bound asynchronous begin/read/cancel, private-token projection, cancellation/TTL/session-close and silent late replies " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
