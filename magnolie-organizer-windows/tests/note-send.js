"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict"), { createHash } = require("node:crypto");
const vm = require("node:vm");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const plain = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setImmediate(resolve));
async function until(predicate) { const deadline = Date.now() + 3000; while (!predicate()) { assert.ok(Date.now() < deadline, "Owned note-send fixture timed out"); await new Promise(resolve => setTimeout(resolve, 2)); } }
const watchdog = setTimeout(() => { console.error("Note send timed out"); process.exit(1); }, 40000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { notizen: [
      { id: "owned-note", titel: "Owned selected note", text: "SELECTED OWNED BODY", html: "SELECTED OWNED BODY" },
      { id: "unselected-note", titel: "Unselected", text: "UNSELECTED MUST NOT BE SENT", html: "UNSELECTED MUST NOT BE SENT" }],
      kontakte: [{ id: "owned-recipient", vorname: "Owned", nachname: "Recipient", emails: ["owned@example.test"],
        telefone: [{ wert: "+49305550123", typen: ["FAX"] }, { wert: "+49305550124", typen: ["CELL"] },
          { wert: "+49305550125", typen: ["HOMEFAX"] }, { wert: "+49305550126", typen: ["WORKFAX"] }] }] });
    try {
      const labels = ["Cancel sending", "Document handed to the selected application or fax server. Delivery is not confirmed.",
        "Enter a HylaFAX server hostname, optionally followed by :port.", "Enter recipient manually", "Fax",
        "Fax requires a configured HylaFAX server and installed sendfax. Email uses a supported installed mail client. A handoff is not delivery confirmation.",
        "HylaFAX server (Linux)", "No configured mail or fax adapter is available.", "Preparing selected notes…", "Recipient", "Select a recipient.",
        "Send notes by email or fax", "Sending cancelled.", "Sending is disabled.", "Sending is not available.", "Show Send in note print options", "Subject",
        "The document could not be handed off.", "The handoff has already started and cannot be recalled here.",
        "The handoff outcome is unknown. Check the external application before trying again.",
        "Waiting for the mail or fax application. Closing this window does not recall the handoff."];
      for (const file of fs.readdirSync(path.join(web, "i18n")).filter(name => name.endsWith(".js"))) {
        let catalog;
        vm.runInNewContext(fs.readFileSync(path.join(web, "i18n", file), "utf8"), { window: { MagnolieI18n: { registerCatalog: (_locale, value) => { catalog = value.messages; } } } });
        for (const label of labels) assert.ok(catalog[label] && (label === "Fax" || catalog[label] !== label), file + ": missing note-send translation " + label);
      }
      if (b.saves().length) b.ack();
      const contactsBefore = JSON.stringify(b.t.daten().kontakte);
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      let nativeSettings = plain(b.t.daten().einstellungen.versand), ackSaves = true, holdRead = false, rejectBegin = false;
      const nativeJobs = new Map(), requests = [], held = [];
      const revision = () => createHash("sha256").update(JSON.stringify(nativeSettings)).digest("hex");
      const state = () => ({ settings: plain(nativeSettings), revision: revision(), capabilities: { enabled: nativeSettings.enabled,
        email: { supported: true, available: true, client: "Owned synthetic mail" }, fax: { supported: true, available: !!nativeSettings.faxServer, configured: !!nativeSettings.faxServer } } });
      const reply = (message, result) => b.w.App.noteSendErgebnis({ requestId: message.requestId, ok: true, ...result });
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern" && ackSaves) queueMicrotask(() => { nativeSettings = JSON.parse(message.text).einstellungen.versand; b.w.App.gespeichert({ id: message.id, ok: true }); });
        if (message.cmd !== "notiz_versand") return;
        requests.push(message.request); const request = message.request;
        queueMicrotask(() => {
          if (request.action === "read") { if (holdRead) held.push(message); else reply(message, { state: state() }); return; }
          if (request.action === "begin") {
            if (rejectBegin) { b.w.App.noteSendErgebnis({ requestId: message.requestId, ok: false, code: "native_unavailable", nativeOutcomeUnknown: false }); return; }
            if (!nativeSettings.enabled || request.expectedRevision !== revision()) { b.w.App.noteSendErgebnis({ requestId: message.requestId, ok: false, code: "conflict", nativeOutcomeUnknown: false }); return; }
            assert.ok(request.html.includes("SELECTED OWNED BODY") && !request.html.includes("UNSELECTED MUST NOT BE SENT"));
            nativeJobs.set(request.operationId, { operation_id: request.operationId, phase: "preparing", error_code: "none", native_outcome_unknown: false,
              cancel_requested: false, can_cancel: true, handed_off: false, delivery_confirmed: false, adapter: null, document: null });
          }
          const job = nativeJobs.get(request.operationId);
          assert.ok(job, request.action + ": unknown synthetic job");
          if (request.action === "cancel") {
            const accepted = job.can_cancel;
            if (accepted) Object.assign(job, { phase: "cancelled", cancel_requested: true, can_cancel: false });
            reply(message, { job: { ...plain(job), cancel_accepted: accepted } });
          } else reply(message, { job: plain(job) });
        });
      };
      assert.equal(b.t.daten().einstellungen.versand.enabled, false);
      let preview = b.t.oeffneDruckvorschau(b.t.daten().notizen[0], "notizen");
      assert.ok(!preview.querySelector("#notiz-versand-oeffnen"), "sending must be absent by default");
      preview.querySelector('button[title="Close"]').click();
      b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-allgemein").click();
      const master = b.w.document.querySelector("#notiz-versand-aktiv"); assert.ok(!master.checked); master.click();
      const server = b.input("#notiz-versand-faxserver", "FAX.EXAMPLE.TEST:04559");
      [...server.closest("details").querySelectorAll("button")].find(button => button.textContent === "Save").click();
      assert.equal(b.t.daten().einstellungen.versand.faxServer, "fax.example.test:4559");
      master.click(); assert.equal(b.t.daten().einstellungen.versand.enabled, false); assert.equal(b.t.daten().einstellungen.versand.faxServer, "fax.example.test:4559");
      master.click(); b.t.schliesseEinstellungen();
      preview = b.t.oeffneDruckvorschau(b.t.daten().notizen[0], "notizen");
      assert.equal(preview.querySelectorAll("#notiz-versand-oeffnen").length, 1);
      const beforePrint = requests.length;
      [...preview.querySelectorAll(".druck-fuss button")].find(button => button.getAttribute("aria-label") === "Print now" || button.title === "Print now").click();
      assert.equal(requests.length, beforePrint, "printing must never dispatch note sending");
      preview = b.t.oeffneDruckvorschau(b.t.daten().notizen[0], "notizen"); preview.querySelector("#notiz-versand-oeffnen").click();
      await until(() => b.w.document.querySelector("#notiz-versand-art")?.options.length === 2);
      assert.equal(b.w.document.querySelector("#notiz-versand-start").disabled, true, "recipient must be selected explicitly");
      const kind = b.w.document.querySelector("#notiz-versand-art"); kind.value = "fax"; kind.dispatchEvent(new b.w.Event("change"));
      const recipients = b.w.document.querySelector("#notiz-versand-kontakt");
      assert.equal(recipients.options.length, 4, "FAX/HOMEFAX/WORKFAX use the existing fax phone type, without ordinary mobile targets");
      assert.ok(!recipients.textContent.includes("+49305550124")); recipients.value = "1"; recipients.dispatchEvent(new b.w.Event("change"));
      b.w.document.querySelector("#notiz-versand-start").click();
      await until(() => nativeJobs.size === 1);
      const guiJob = [...nativeJobs.values()][0];
      Object.assign(guiJob, { phase: "handed_off", can_cancel: false, handed_off: true, adapter: "hylafax-sendfax", document: { bytes: 64, sha256: "a".repeat(64) } });
      b.timers.filter(timer => timer.delay === 400 && !timer.cancelled).at(-1).fn();
      await until(() => b.w.document.querySelector("#notiz-versand-status").textContent.includes("Delivery is not confirmed"));
      [...b.w.document.querySelectorAll("#notiz-versand button")].find(button => button.textContent === "Close").click();
      holdRead = true; preview.querySelector("#notiz-versand-oeffnen").click(); await until(() => held.length === 1);
      [...b.w.document.querySelectorAll("#notiz-versand button")].find(button => button.textContent === "Cancel").click();
      reply(held.pop(), { state: state() }); await tick(); assert.ok(!b.w.document.querySelector("#notiz-versand"), "late native replies must not reopen closed send dialogs");
      holdRead = false; preview.querySelector('button[title="Close"]').click();
      let sequence = 0;
      async function rpc(method, params, session = "a".repeat(48)) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session, invocation, message: { jsonrpc: "2.0", method, ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
      }
      const call = async (name, args = {}, session) => (await rpc("tools/call", { name, arguments: args }, session)).result;
      const ok = result => { assert.equal(result?.isError, false, JSON.stringify(result)); return result.structuredContent; };
      const initialize = async session => { await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-note-send", version: "1" } }, session); await rpc("notifications/initialized", {}, session); };
      await initialize();
      const native = ok(await call("organizer_note_send_state_read"));
      const book = ok(await call("organizer_book_revision_read"));
      const begun = ok(await call("organizer_note_send_start", { expected_book_revision: book.revision, expected_state_revision: native.revision,
        ids: ["owned-note"], kind: "email", recipient: "owned@example.test", contact_id: "owned-recipient" }));
      assert.equal(begun.phase, "saving"); await until(() => nativeJobs.has(begun.operation_id));
      const pending = ok(await call("organizer_note_send_status", { operation_id: begun.operation_id })); assert.equal(pending.phase, "preparing");
      const foreign = "b".repeat(48); await initialize(foreign);
      const rejected = await call("organizer_note_send_status", { operation_id: begun.operation_id }, foreign); assert.equal(rejected.structuredContent.code, "not_found");
      const cancelled = ok(await call("organizer_note_send_cancel", { operation_id: begun.operation_id })); assert.equal(cancelled.cancel_accepted, true); assert.equal(cancelled.handed_off, false);
      const cancelledNative = plain(nativeJobs.get(begun.operation_id));
      Object.assign(nativeJobs.get(begun.operation_id), { phase: "handed_off", handed_off: true, adapter: "hylafax-sendfax", document: { bytes: 64, sha256: "a".repeat(64) } });
      const wrongRoute = await call("organizer_note_send_status", { operation_id: begun.operation_id });
      assert.equal(wrongRoute.structuredContent.code, "invalid_result", "a fax receipt must never satisfy an email operation");
      nativeJobs.set(begun.operation_id, cancelledNative);
      const beforeCancelled = requests.filter(request => request.action === "begin").length;
      b.t.daten().notizen[0].text += " Owned pending save";
      const dirtyBook = ok(await call("organizer_book_revision_read")), saveCount = b.saves().length;
      ackSaves = false;
      const early = ok(await call("organizer_note_send_start", { expected_book_revision: dirtyBook.revision, expected_state_revision: native.revision, ids: ["owned-note"], kind: "email", recipient: "owned@example.test" }));
      const earlyCancel = ok(await call("organizer_note_send_cancel", { operation_id: early.operation_id })); assert.equal(earlyCancel.cancel_accepted, true);
      await until(() => b.saves().length > saveCount); b.ack(); ackSaves = true; await tick();
      assert.equal(requests.filter(request => request.action === "begin").length, beforeCancelled, "cancel before SaveACK must prevent native dispatch");
      rejectBegin = true;
      const rejectedStart = ok(await call("organizer_note_send_start", { expected_book_revision: dirtyBook.revision, expected_state_revision: native.revision, ids: ["owned-note"], kind: "email", recipient: "owned@example.test" }));
      let rejectedState;
      for (let attempt = 0; attempt < 50; attempt++) {
        rejectedState = ok(await call("organizer_note_send_status", { operation_id: rejectedStart.operation_id }));
        if (rejectedState.phase === "failed") break;
        await tick();
      }
      assert.equal(rejectedState.phase, "failed"); assert.equal(rejectedState.error_code, "native_unavailable"); assert.equal(rejectedState.native_outcome_unknown, false);
      rejectBegin = false;
      const config = ok(await call("organizer_note_send_settings_read"));
      ok(await call("organizer_note_send_settings_update", { expected_revision: config.revision, enabled: false }));
      const disabled = await call("organizer_note_send_start", { expected_book_revision: book.revision, expected_state_revision: native.revision, ids: ["owned-note"], kind: "email", recipient: "owned@example.test" });
      assert.equal(disabled.structuredContent.code, "feature_disabled");
      assert.equal(JSON.stringify(b.t.daten().kontakte), contactsBefore, "sending must not rewrite existing fax types or other contact fields");
      console.log("NOTE SEND PASS: default-off/single print entry, separate printing, actual GUI fax recipients, selected content, late replies, MCP owner jobs/SaveACK/cancel and honest receipts " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
