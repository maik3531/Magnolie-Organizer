"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP phone lifecycle timed out"); process.exit(1); }, 15000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const state = { revision: "a".repeat(64), available: true, enabled: false, listening: false, id: "owned-desktop", name: "Owned desktop", fingerprint: "B".repeat(64), port: 8741,
        pairing_open: true, binding_conflict: false, error_present: false, pairing_token: "owned-private-pairing-token", status: { private: "owned-private-cache" },
        capabilities: { device_status: { available: true, versions: [11], secret: "owned-private-capability" } }, editable_grants: ["selected_notifications_readonly", "personal_notes_sync"],
        bluetooth: { available: true, reason: "available", paired_devices_supported: true, devices: [{ address: "AA:BB:CC:DD:EE:FF", name: "Owned system-paired phone", secret: "owned-private-adapter-data" }] },
        peers: Array.from({ length: 125 }, (_, i) => ({ id: "owned-peer-" + i, name: "Owned phone " + i, fingerprint: "C".repeat(64), state: "paired", transport: "offline", online: false, bluetooth_enabled: false, bluetooth_address: "",
          local_grants: { selected_notifications_readonly: false }, remote_grants: { device_status: true }, remote_capabilities: { device_status: { available: true, versions: [11] } }, status: { private: "owned-private-peer-cache" } })),
        pending_pairings: Array.from({ length: 140 }, (_, i) => ({ attempt_id: "owned-attempt-" + i, id: "incoming-peer-" + i, name: "Incoming phone", code: "123456", fingerprint: "D".repeat(64), confirmation_required: true, decision_pending: true, token: "owned-private-pending-token" })) };
      let sequence = 0, onNative;
      const reply = (message, extra = {}) => b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: true, status: state, action: message.request.action,
        localVerified: true, persisted: !["pairing_begin", "pairing_confirm", "pairing_cancel"].includes(message.request.action), deliveryConfirmed: false, ...extra });
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "telefon_mcp") { if (onNative) onNative(message); else reply(message); }
      };
      async function rpc(method, params, id) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
          ...(!method.startsWith("notifications/") ? { id: id ?? sequence } : {}), params } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
      }
      const read = async (args = {}, id) => (await rpc("tools/call", { name: "organizer_phone_connection_read", arguments: args }, id)).result;
      const action = async args => (await rpc("tools/call", { name: "organizer_phone_connection_action", arguments: { expected_revision: state.revision, ...args } })).result;
      const ok = result => { assert.equal(result?.isError, false, JSON.stringify(result)); return result.structuredContent; };
      const fail = (result, code) => { assert.equal(result?.isError, true, JSON.stringify(result)); assert.equal(result.structuredContent.code, code); };
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-phone-lifecycle", version: "1" } }); await rpc("notifications/initialized", {});
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
      const initial = ok(await read()); assert.equal(initial.peer_total, 125); assert.equal(initial.peers.length, 100); assert.equal(initial.pending_total, 140); assert.equal(initial.pending_pairings.length, 100);
      assert.equal(initial.next_offset, 100); assert.ok(!JSON.stringify(initial).includes("owned-private")); assert.equal(initial.capabilities.device_status.versions[0], 11);
      const later = ok(await read({ offset: 130, limit: 7 })); assert.equal(later.peers.length, 0); assert.equal(later.pending_pairings[0].attempt_id, "owned-attempt-130"); assert.equal(later.next_offset, 137);
      const target = { peer_id: "owned-peer-0", fingerprint: "C".repeat(64) };
      for (const args of [{ action: "settings", enabled: false }, { action: "pairing_begin" }, { action: "pairing_confirm", ...target, attempt_id: "owned-attempt-0", accept: true },
        { action: "pairing_cancel", ...target, attempt_id: "owned-attempt-0" }, { action: "remove", ...target },
        { action: "grant", ...target, permission: "selected_notifications_readonly", enabled: true }, { action: "bluetooth", ...target, enabled: false },
        { action: "bluetooth", ...target, enabled: true, address: "AA:BB:CC:DD:EE:FF" }]) {
        let seen; onNative = message => { seen = message; reply(message); };
        const result = ok(await action(args)); assert.equal(result.action, args.action); assert.equal(result.delivery_confirmed, false); assert.equal(result.local_verified, true);
        assert.equal(seen.request.expectedRevision, state.revision);
        if (args.peer_id) { assert.equal(seen.request.peerId, args.peer_id); assert.equal(seen.request.fingerprint, args.fingerprint); }
        if (args.attempt_id) assert.equal(seen.request.attemptId, args.attempt_id);
        if (args.permission) assert.equal(seen.request.name, args.permission);
        assert.equal(result.persisted, !args.action.startsWith("pairing_"));
      }
      onNative = message => reply(message, { persisted: false }); fail(await action({ action: "settings", enabled: false }), "invalid_result");
      onNative = message => reply(message, { persisted: true }); fail(await action({ action: "pairing_begin" }), "invalid_result");
      onNative = message => reply(message, { deliveryConfirmed: true }); fail(await action({ action: "settings", enabled: false }), "invalid_result");
      for (const code of ["profile_locked", "native_busy", "unsupported_feature", "conflict"]) { onNative = message => reply(message, { ok: false, code }); fail(await read(), code); }
      onNative = message => reply(message, { status: { ...state, revision: "bad" } }); fail(await read(), "invalid_result");
      onNative = message => reply(message, { status: { ...state, capabilities: { device_status: { available: true, versions: ["11"] } } } }); fail(await read(), "invalid_result");
      const mediaTarget = { expected_revision: state.revision, ...target };
      const mediaState = { peer_id: target.peer_id, fingerprint: target.fingerprint, supported: true, activation_required: false,
        photos_enabled: false, videos_enabled: true, video_supported: true, automatic_wifi: false, busy: false,
        shared_settings_present: true, shared_settings_agreed: false, persisted: false, transfer_started: false };
      const media = async (args = mediaTarget, id) => (await rpc("tools/call", { name: "organizer_phone_media_status_read", arguments: args }, id)).result;
      let mediaRequest;
      onNative = message => { mediaRequest = message; reply(message, { mediaStatus: mediaState }); };
      const currentMedia = ok(await media());
      assert.equal(currentMedia.videos_enabled, true); assert.equal(currentMedia.photos_enabled, false);
      assert.deepEqual(JSON.parse(JSON.stringify(mediaRequest.request)), { action: "media_status_read", expectedRevision: state.revision,
        peerId: target.peer_id, fingerprint: target.fingerprint });
      const unknown = { ...mediaState, supported: false, photos_enabled: null, videos_enabled: null, video_supported: null,
        automatic_wifi: null, busy: null, shared_settings_present: null, shared_settings_agreed: null };
      onNative = message => reply(message, { mediaStatus: unknown }); assert.equal(ok(await media()).photos_enabled, null);
      for (const changes of [{ path: "private" }, { transfer_started: true }, { persisted: true }, { videos_enabled: "true" }]) {
        onNative = message => reply(message, { mediaStatus: { ...mediaState, ...changes } }); fail(await media(), "invalid_result");
      }
      for (const changes of [{ peer_id: "foreign" }, { fingerprint: "foreign" }]) {
        onNative = message => reply(message, { mediaStatus: { ...mediaState, ...changes } }); fail(await media(), "source_changed");
      }
      for (const code of ["profile_locked", "native_busy", "conflict", "source_changed", "invalid_selection"]) {
        onNative = message => reply(message, { ok: false, code }); fail(await media(), code);
      }
      const requestsBeforeBadArguments = b.messages.length;
      const badMedia = await rpc("tools/call", { name: "organizer_phone_media_status_read", arguments: { ...mediaTarget, enabled: true } });
      assert.equal(badMedia.error.code, -32602);
      assert(!b.messages.slice(requestsBeforeBadArguments).some(message => message.cmd === "telefon_mcp"));
      let held;
      const waiting = new Promise(resolve => { onNative = message => { held = message; resolve(); }; });
      const pending = media(mediaTarget, 9000); await waiting;
      b.t.oeffneEinstellungen(); await tick();
      fail(await action({ action: "settings", enabled: false }), "dialog_busy");
      const toast = b.w.document.querySelector("#zettel").textContent;
      await rpc("notifications/cancelled", { requestId: 9000 }); fail(await pending, "cancelled"); reply(held); await tick();
      assert.equal(b.w.document.querySelector("#zettel").textContent, toast); assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves);
      console.log("MCP PHONE LIFECYCLE PASS: typed public pages, native action/identity/attempt mapping, runtime versus store receipts, modal/cancel/error/late guards " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
