"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP DAV metadata timed out"); process.exit(1); }, 15000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      let sequence = 0, onRead, onWrite, onTest, onMailbox, onGraph, onGraphChange;
      const nativeWrites = [];
      const metadata = { kontoArt: "nextcloud", davAktiv: true, briefkastenAktiv: false, url: "https://owned.example.test", benutzer: "owned-reader",
        kennwortVorhanden: true, revision: "e".repeat(64), zustand: "bereit", fehler: "", fehlerCode: "none" };
      const reply = (message, extra = {}) => b.w.App.baumBriefkastenStatus({ ...metadata, ...extra, requestId: message.requestId || "",
        application_password: "owned-private-password", authorization: "owned-private-authorization", protectedCredential: "owned-private-protected-blob" });
      const replySave = (message, extra = {}) => b.w.App.baumBriefkastenGespeichert({ ...metadata, requestId: message.requestId,
        ok: true, persisted: true, verified: true, revision: "f".repeat(64), kontoArt: message.kontoArt,
        davAktiv: message.davAktiv, briefkastenAktiv: message.briefkastenAktiv, url: message.url, benutzer: message.benutzer,
        kennwortVorhanden: message.kennwortLoeschen ? false : message.anwendungskennwort ? true : metadata.kennwortVorhanden,
        application_password: message.anwendungskennwort, protectedCredential: "owned-private-write-blob", ...extra });
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern") queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true }));
        if (message.cmd === "baum_briefkasten_status") {
          if (message.requestId && onRead) onRead(message); else queueMicrotask(() => reply(message));
        }
        if (message.cmd === "baum_briefkasten_speichern" && message.requestId) {
          nativeWrites.push(message); if (onWrite) onWrite(message); else queueMicrotask(() => replySave(message));
        }
        if (message.cmd === "baum_dav_pruefen") onTest(message);
        if (message.cmd === "baum_mailbox_schreibpruefen") onMailbox(message);
        if (message.cmd === "graph_konto_stand") onGraph(message);
        if (message.cmd === "graph_konto_aendern") onGraphChange(message);
      };
      async function rpc(method, params, explicitId) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
          ...(!method.startsWith("notifications/") ? { id: explicitId ?? sequence } : {}), ...(params === undefined ? {} : { params }) } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
      }
      const read = async id => (await rpc("tools/call", { name: "organizer_dav_account_read" }, id)).result;
      const test = async id => (await rpc("tools/call", { name: "organizer_dav_connection_test", arguments: { expected_revision: metadata.revision } }, id)).result;
      const mailboxTest = async id => (await rpc("tools/call", { name: "organizer_mailbox_write_test", arguments: { expected_revision: metadata.revision } }, id)).result;
      const graphRead = async id => (await rpc("tools/call", { name: "organizer_microsoft_account_read" }, id)).result;
      const replyGraph = (message, extra = {}) => b.w.App.graphKontoStand({ requestId: message.requestId, ok: true,
        clientId: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", configured: true, tokenFilePresent: true, signInPending: false, revision: "e".repeat(64),
        refreshToken: "owned-private-refresh-token", protectedToken: "owned-private-protected-token", ...extra });
      const graphChange = async (args = {}, id) => (await rpc("tools/call", { name: "organizer_microsoft_account_action", arguments: { action: "configure", expected_revision: "e".repeat(64), client_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", ...args } }, id)).result;
      const replyGraphChange = (message, extra = {}) => b.w.App.graphKontoGeaendert({ requestId: message.requestId, ok: true, persisted: true, verified: true,
        clientId: message.clientId, configured: !!message.clientId, tokenFilePresent: false, signInPending: false, revision: "f".repeat(64), refreshToken: "owned-private-change-token", ...extra });
      const replyMailbox = (message, extra = {}) => b.w.App.baumMailboxSchreibpruefung({ requestId: message.requestId, ok: true, revision: metadata.revision,
        passed: true, deleteAcknowledged: true, errorCode: "none", password: "owned-private-mailbox-secret", ...extra });
      const replyTest = (message, extra = {}) => b.w.App.baumDavPruefung({ requestId: message.requestId, ok: true, revision: metadata.revision,
        reachable: true, partial: false, errorCode: "none", calendars: 2, addressBooks: 1, password: "owned-private-test-secret", ...extra });
      const write = async (fields = {}, id) => (await rpc("tools/call", { name: "organizer_dav_account_update", arguments: {
        expected_revision: metadata.revision, account_type: "nextcloud", dav_enabled: false, mailbox_enabled: false,
        server: metadata.url, user: metadata.benutzer, ...fields } }, id)).result;
      const ok = result => { assert.equal(result.isError, false, JSON.stringify(result)); return result.structuredContent; };
      const fail = (result, code) => { assert.equal(result.isError, true, JSON.stringify(result)); assert.equal(result.structuredContent.code, code); };
      await rpc("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "owned-dav-reader", version: "1" } });
      await rpc("notifications/initialized");
      const before = JSON.stringify(b.t.daten()), saveCount = b.saves().length;
      onGraph = message => replyGraph(message);
      const graph = ok(await graphRead()); assert.equal(graph.configured, true); assert.equal(graph.token_file_present, true);
      assert.equal(graph.revision, "e".repeat(64));
      assert.equal(graph.authentication_verified, false); assert.equal(graph.connectivity_checked, false);
      assert.ok(!JSON.stringify(graph).includes("owned-private"));
      onGraph = message => replyGraph(message, { signInPending: true }); assert.equal(ok(await graphRead()).sign_in_pending, true);
      onGraph = message => replyGraph(message, { clientId: "", configured: false, tokenFilePresent: false }); assert.equal(ok(await graphRead()).configured, false);
      onGraph = message => replyGraph(message, { clientId: "invalid" }); fail(await graphRead(), "invalid_result");
      onGraph = message => replyGraph(message, { configured: false }); fail(await graphRead(), "invalid_result");
      onGraph = message => replyGraph(message, { ok: false, code: "unsupported_feature" }); fail(await graphRead(), "unsupported_feature");
      onGraph = message => replyGraph(message, { ok: false, code: "profile_locked" }); fail(await graphRead(), "locked_or_cancelled");
      let graphChangedMessage, graphChangeComplete = false;
      const graphChangeStarted = new Promise(resolve => { onGraphChange = message => { graphChangedMessage = message; resolve(); }; });
      const graphChanging = graphChange().then(result => { graphChangeComplete = true; return result; }); await graphChangeStarted;
      assert.equal(graphChangedMessage.expectedRevision, "e".repeat(64)); assert.equal(graphChangedMessage.action, "configure");
      replyGraphChange({ ...graphChangedMessage, requestId: "wrong-graph-change" }); await tick(); assert.equal(graphChangeComplete, false);
      replyGraphChange(graphChangedMessage); const graphChanged = ok(await graphChanging); assert.equal(graphChanged.persisted, true); assert.ok(!JSON.stringify(graphChanged).includes("owned-private"));
      onGraphChange = message => replyGraphChange(message);
      assert.equal(ok(await graphChange({ client_id: "" })).configured, false); assert.equal(ok(await graphChange({ action: "sign_out" })).token_file_present, false);
      for (const bad of [{ persisted: false }, { verified: false }, { revision: "invalid" }]) {
        onGraphChange = message => replyGraphChange(message, bad); fail(await graphChange(), "invalid_result");
      }
      onGraphChange = message => replyGraphChange(message, { tokenFilePresent: true }); fail(await graphChange({ action: "sign_out" }), "invalid_result");
      for (const code of ["conflict", "native_busy", "unsupported_feature", "profile_locked"]) {
        onGraphChange = message => replyGraphChange(message, { ok: false, code }); fail(await graphChange(), code === "profile_locked" ? "locked_or_cancelled" : code);
      }
      let mailboxMessage, mailboxComplete = false;
      const mailboxStarted = new Promise(resolve => { onMailbox = message => { mailboxMessage = message; resolve(); }; });
      const mailboxPending = mailboxTest().then(result => { mailboxComplete = true; return result; }); await mailboxStarted;
      assert.equal(mailboxMessage.expectedRevision, metadata.revision);
      replyMailbox({ ...mailboxMessage, requestId: "wrong-mailbox-request" }); await tick(); assert.equal(mailboxComplete, false);
      replyMailbox(mailboxMessage); const mailboxResult = ok(await mailboxPending);
      assert.equal(mailboxResult.write_test_passed, true); assert.equal(mailboxResult.probe_delete_acknowledged, true);
      assert.equal(mailboxResult.remote_state_may_have_changed, true); assert.equal(mailboxResult.delivery_confirmed, false);
      assert.ok(!JSON.stringify(mailboxResult).includes("owned-private"));
      onMailbox = message => replyMailbox(message, { passed: false, deleteAcknowledged: false, errorCode: "http_403" });
      assert.equal(ok(await mailboxTest()).write_test_passed, false);
      onMailbox = message => replyMailbox(message, { deleteAcknowledged: false }); fail(await mailboxTest(), "invalid_result");
      onMailbox = message => replyMailbox(message, { passed: false, deleteAcknowledged: false }); fail(await mailboxTest(), "invalid_result");
      onMailbox = message => replyMailbox(message, { revision: "f".repeat(64) }); fail(await mailboxTest(), "invalid_result");
      for (const code of ["conflict", "not_active", "native_busy", "profile_locked"]) {
        onMailbox = message => replyMailbox(message, { ok: false, code }); fail(await mailboxTest(), code === "profile_locked" ? "locked_or_cancelled" : code);
      }
      let testMessage, testComplete = false;
      const testStarted = new Promise(resolve => { onTest = message => { testMessage = message; resolve(); }; });
      const testing = test().then(result => { testComplete = true; return result; }); await testStarted;
      assert.equal(testMessage.expectedRevision, metadata.revision);
      replyTest({ ...testMessage, requestId: "wrong-test-request" }); await tick(); assert.equal(testComplete, false);
      replyTest(testMessage); const tested = ok(await testing);
      assert.equal(tested.calendar_count, 2); assert.equal(tested.mailbox_tested, false); assert.equal(tested.connectivity_checked, true);
      assert.ok(!JSON.stringify(tested).includes("owned-private-"));
      onTest = message => replyTest(message, { reachable: false, calendars: 0, addressBooks: 0, errorCode: "http_401" });
      assert.equal(ok(await test()).error_code, "http_401");
      onTest = message => replyTest(message, { partial: true, errorCode: "partial_discovery" }); assert.equal(ok(await test()).partial, true);
      onTest = message => replyTest(message, { errorCode: "owned-private-error" }); assert.equal(ok(await test()).error_code, "native_operation_failed");
      onTest = message => replyTest(message, { revision: "f".repeat(64) }); fail(await test(), "invalid_result");
      onTest = message => replyTest(message, { calendars: -1 }); fail(await test(), "invalid_result");
      for (const code of ["conflict", "not_active", "native_busy", "profile_locked"]) {
        onTest = message => replyTest(message, { ok: false, code }); fail(await test(), code === "profile_locked" ? "locked_or_cancelled" : code);
      }
      let native, completed = false;
      const started = new Promise(resolve => { onRead = message => { native = message; resolve(); }; });
      const pending = read().then(result => { completed = true; return result; });
      await started; reply({ ...native, requestId: "wrong-request" }); await tick(); assert.equal(completed, false);
      reply(native); onRead = null; const first = ok(await pending);
      assert.equal(first.settings.account_type, "nextcloud"); assert.equal(first.settings.server, metadata.url);
      assert.equal(first.credential_present, true); assert.equal(first.revision, metadata.revision); assert.equal(first.connectivity_checked, false);
      assert.ok(!JSON.stringify(first).includes("owned-private-"));
      onRead = message => reply(message, { kontoArt: "generic-dav", briefkastenAktiv: false, zustand: "aus" });
      assert.equal(ok(await read()).settings.account_type, "generic-dav");
      onRead = message => reply(message, { url: "", benutzer: "", davAktiv: false, briefkastenAktiv: false, kennwortVorhanden: false, zustand: "nicht_eingerichtet" });
      const empty = ok(await read()); assert.equal(empty.settings.configured, false); assert.equal(empty.credential_present, false);
      onRead = message => reply(message, { revision: null, fehler: "owned-private-native-error", fehlerCode: "secret_service_unavailable", zustand: "fehler", kennwortVorhanden: false });
      const unavailable = ok(await read()); assert.equal(unavailable.revision, null); assert.equal(unavailable.credential_present, null); assert.equal(unavailable.error_present, true);
      assert.ok(!JSON.stringify(unavailable).includes("owned-private-"));
      onRead = message => reply(message, { revision: null }); fail(await read(), "invalid_result");
      onRead = message => reply(message, { revision: undefined }); fail(await read(), "invalid_result");
      onRead = message => reply(message, { kennwortVorhanden: "yes" }); fail(await read(), "invalid_result");
      onRead = message => reply(message, { ok: false, code: "native_busy" }); fail(await read(), "native_busy");
      onRead = message => reply(message, { ok: false, code: "profile_locked" }); fail(await read(), "locked_or_cancelled");
      onRead = null;
      let saveMessage, saveCompleted = false;
      const saveStarted = new Promise(resolve => { onWrite = message => { saveMessage = message; resolve(); }; });
      const saving = write({ application_password: "owned-typed-credential" }).then(result => { saveCompleted = true; return result; });
      await saveStarted; assert.equal(saveCompleted, false); assert.equal(saveMessage.expectedRevision, metadata.revision);
      assert.equal(saveMessage.anwendungskennwort, "owned-typed-credential"); replySave(saveMessage);
      const saved = ok(await saving); assert.equal(saved.persisted, true); assert.equal(saved.verified, true); assert.equal(saved.connectivity_checked, false);
      assert.ok(!JSON.stringify(saved).includes("owned-typed-credential") && !JSON.stringify(saved).includes("owned-private-"));
      onWrite = null; assert.equal(ok(await write({ clear_password: true })).credential_present, false);
      const writeCount = nativeWrites.length;
      fail(await write({ clear_password: true, dav_enabled: true }), "invalid_settings");
      fail(await write({ clear_password: true, application_password: "owned-conflicting" }), "invalid_settings");
      fail(await write({ account_type: "generic-dav", mailbox_enabled: true }), "invalid_settings"); assert.equal(nativeWrites.length, writeCount);
      onWrite = message => replySave(message, { ok: false, code: "conflict", fehler: "owned-private-error" });
      const stale = await write(); fail(stale, "conflict"); assert.ok(!JSON.stringify(stale).includes("owned-private-"));
      onWrite = message => replySave(message, { ok: false, code: "verification_failed" }); fail(await write(), "verification_failed");
      onWrite = message => replySave(message, { persisted: undefined }); fail(await write(), "invalid_result");
      onWrite = message => replySave(message, { verified: false }); fail(await write(), "invalid_result");
      onWrite = message => replySave(message, { davAktiv: true }); fail(await write(), "invalid_result");
      onWrite = message => replySave(message, { kennwortVorhanden: false }); fail(await write({ application_password: "owned-not-stored" }), "invalid_result");
      onWrite = null;
      const lateMailboxStarted = new Promise(resolve => { onMailbox = message => { mailboxMessage = message; resolve(); }; });
      const lateMailbox = mailboxTest(7800); await lateMailboxStarted;
      const lateGraphWriteStarted = new Promise(resolve => { onGraphChange = message => { graphChangedMessage = message; resolve(); }; });
      const lateGraphWrite = graphChange({}, 7750); await lateGraphWriteStarted;
      b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-sync").click(); await tick();
      await rpc("notifications/cancelled", { requestId: 7750 }); fail(await lateGraphWrite, "cancelled");
      const graphWriteRefreshes = b.messages.filter(message => message.cmd === "eds_status").length;
      replyGraphChange(graphChangedMessage); await tick(); assert.equal(b.messages.filter(message => message.cmd === "eds_status").length, graphWriteRefreshes);
      fail(await mailboxTest(), "dialog_busy");
      await rpc("notifications/cancelled", { requestId: 7800 }); fail(await lateMailbox, "cancelled");
      const mailboxRefreshCount = b.messages.filter(message => message.cmd === "eds_status").length;
      replyMailbox(mailboxMessage); await tick();
      assert.equal(b.messages.filter(message => message.cmd === "eds_status").length, mailboxRefreshCount);
      fail(await write(), "dialog_busy");
      const field = b.w.document.querySelector("#briefkasten-url"); assert.ok(field);
      field.value = "https://owned-draft.example.test"; field.dispatchEvent(new b.w.Event("input"));
      const password = b.w.document.querySelector("#briefkasten-kennwort"); assert.ok(password); password.value = "owned-unsaved-credential";
      fail(await graphChange(), "dialog_busy");
      let graphMessage;
      const graphStarted = new Promise(resolve => { onGraph = message => { graphMessage = message; resolve(); }; });
      const graphPending = graphRead(7850); await graphStarted;
      replyGraph({ ...graphMessage, requestId: "wrong-graph-request" }); await tick();
      await rpc("notifications/cancelled", { requestId: 7850 }); fail(await graphPending, "cancelled");
      const graphRefreshCount = b.messages.filter(message => message.cmd === "eds_status").length;
      replyGraph(graphMessage); await tick(); assert.equal(b.messages.filter(message => message.cmd === "eds_status").length, graphRefreshCount);
      const lateTestStarted = new Promise(resolve => { onTest = message => { testMessage = message; resolve(); }; });
      const lateTest = test(7900); await lateTestStarted;
      await rpc("notifications/cancelled", { requestId: 7900 }); fail(await lateTest, "cancelled");
      const testRequestsBeforeLate = b.messages.filter(message => message.cmd === "eds_status").length;
      replyTest(testMessage); await tick();
      assert.equal(b.messages.filter(message => message.cmd === "eds_status").length, testRequestsBeforeLate);
      onRead = message => reply(message, { url: "https://fresh-native.example.test" });
      const fresh = ok(await read()); assert.equal(fresh.settings.server, "https://fresh-native.example.test");
      assert.equal(b.w.document.querySelector("#briefkasten-url"), field); assert.equal(field.value, "https://owned-draft.example.test");
      assert.equal(b.w.document.querySelector("#briefkasten-kennwort"), password); assert.equal(password.value, "owned-unsaved-credential"); assert.ok(!JSON.stringify(fresh).includes("owned-unsaved-credential"));
      const cancelStarted = new Promise(resolve => { onRead = message => { native = message; resolve(); }; });
      const cancelled = read(8000); await cancelStarted;
      await rpc("notifications/cancelled", { requestId: 8000 }); fail(await cancelled, "cancelled");
      const toast = b.w.document.querySelector("#zettel").textContent;
      reply(native, { url: "https://late-native.example.test" }); onRead = null; await tick();
      assert.equal(b.w.document.querySelector("#briefkasten-url"), field); assert.equal(field.value, "https://owned-draft.example.test");
      assert.equal(b.w.document.querySelector("#briefkasten-kennwort"), password); assert.equal(password.value, "owned-unsaved-credential");
      assert.equal(b.w.document.querySelector("#zettel").textContent, toast);
      b.w.document.querySelector("#einstellungen-zu").click();
      const writeCancelStarted = new Promise(resolve => { onWrite = message => { saveMessage = message; resolve(); }; });
      const cancelledWrite = write({ application_password: "owned-cancel-secret" }, 8500); await writeCancelStarted;
      b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-sync").click(); await tick();
      const lateField = b.w.document.querySelector("#briefkasten-url"), latePassword = b.w.document.querySelector("#briefkasten-kennwort");
      lateField.value = "https://owned-late-draft.example.test"; lateField.dispatchEvent(new b.w.Event("input")); latePassword.value = "owned-late-draft-secret";
      await rpc("notifications/cancelled", { requestId: 8500 }); fail(await cancelledWrite, "cancelled");
      const requestsBeforeLate = b.messages.filter(message => message.cmd === "eds_status").length;
      replySave(saveMessage); onWrite = null; await tick();
      assert.equal(b.w.document.querySelector("#briefkasten-url"), lateField); assert.equal(lateField.value, "https://owned-late-draft.example.test");
      assert.equal(b.w.document.querySelector("#briefkasten-kennwort"), latePassword); assert.equal(latePassword.value, "owned-late-draft-secret");
      assert.equal(b.messages.filter(message => message.cmd === "eds_status").length, requestsBeforeLate);
      b.w.document.querySelector("#einstellungen-zu").click();
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saveCount);
      assert.ok(!b.messages.some(message => ["baum_briefkasten_pruefen", "sync", "sync_start", "graph_anmelden"].includes(message.cmd)));
      console.log("MCP DAV ACCOUNT PASS: correlated actual-state projection, secret stripping, unreadable states and unchanged GUI drafts/book " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
