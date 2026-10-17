"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve)), clone = value => JSON.parse(JSON.stringify(value));
const watchdog = setTimeout(() => { console.error("MCP sync run timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    for (const mode of ["success", "commit_rejected", "provider_error", "save_failed", "native_failure", "queued_abort", "preparing_save_failed", "selection_changed", "source_changed", "late_modal", ...(web.endsWith("/magnolie-organizer/web") ? ["no_journal"] : [])]) {
      const b = await harness.exports.boot(web, { einstellungen: { sync: { kalenderUids: ["owned-calendar"], kalenderUid: "owned-calendar", adressbuchUid: "", erfolgsmeldungen: true } } });
      try {
        if (b.saves().length) b.ack(); await tick();
        b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
        let sequence = 0, syncMessage, commitMessage, owner = "a".repeat(48);
        const saves = [];
        const post = b.w.webkit.messageHandlers.regression.postMessage;
        b.w.webkit.messageHandlers.regression.postMessage = text => {
          post(text); const message = JSON.parse(text);
          if (message.cmd === "speichern") saves.push(message);
          if (message.cmd === "baum_briefkasten_status") queueMicrotask(() => b.w.App.baumBriefkastenStatus({ requestId: message.requestId || "", kontoArt: "nextcloud", davAktiv: false,
            briefkastenAktiv: false, url: "https://owned.example.test", benutzer: "owned-reader", kennwortVorhanden: false, zustand: "inaktiv", fehler: "", fehlerCode: "none" }));
          if (message.cmd === "sync") syncMessage = message;
          if (["sync_commit", "sync_bestaetigen"].includes(message.cmd)) commitMessage = message;
        };
        async function rpc(method, params) {
          const invocation = (++sequence).toString(16).padStart(48, "0");
          await b.w.App.mcpRequest({ session: owner, invocation, message: { jsonrpc: "2.0", method,
            ...(!method.startsWith("notifications/") ? { id: sequence } : {}), ...(params === undefined ? {} : { params }) } });
          return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
        }
        const tool = async (name, args = {}) => (await rpc("tools/call", { name, arguments: args })).result;
        const ok = result => { assert.equal(result?.isError, false, JSON.stringify(result)); return result.structuredContent; };
        const status = async id => ok(await tool("organizer_sync_status", id ? { run_id: id } : {}));
        const revision = async () => ok(await tool("organizer_book_revision_read")).revision;
        async function ack(success = true) {
          const next = saves.shift(); assert.ok(next, "Expected actual product save request");
          b.w.App.gespeichert({ id: next.id, ok: success }); await tick();
        }
        await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-sync-run", version: "1" } }); await rpc("notifications/initialized", {});
        assert.equal((await status()).job, null);
        const stale = await tool("organizer_sync_start", { expected_book_revision: "0".repeat(64) }); assert.equal(stale.structuredContent.code, "conflict"); assert.equal(syncMessage, undefined);
        const started = ok(await tool("organizer_sync_start", { expected_book_revision: await revision() }));
        assert.equal(started.job.phase, "preparing"); assert.equal(started.job.data_saved, false); assert.equal(syncMessage, undefined);
        const id = started.job.run_id;
        if (mode === "preparing_save_failed") {
          await ack(false); const failed = await status(id); assert.equal(failed.job.phase, "failed"); assert.equal(failed.job.error_code, "save_failed"); assert.equal(syncMessage, undefined); continue;
        }
        if (mode === "selection_changed") {
          b.t.daten().einstellungen.sync.kalenderUid = "owned-new-choice";
          await ack(); const failed = await status(id); assert.equal(failed.job.phase, "failed"); assert.equal(failed.job.error_code, "conflict"); assert.equal(syncMessage, undefined); continue;
        }
        for (let i = 0; !syncMessage && i < 10; i++) { if (saves.length) await ack(); else await tick(); }
        assert.ok(syncMessage, "The actual shared GUI workflow did not dispatch sync after SaveACK"); assert.equal(syncMessage.mcp, true);
        assert.equal((await status(id)).job.phase, "dispatching"); assert.equal((await status(id)).job.native_started, false);
        if (mode === "queued_abort") {
          b.w.App.syncMcpFehler({ nativeId: syncMessage.requestId || syncMessage.transactionId, code: "source_changed" });
          const rejected = await status(id); assert.equal(rejected.job.phase, "failed"); assert.equal(rejected.job.native_started, false);
          assert.equal(rejected.job.provider_finished, true); assert.equal(rejected.job.error_code, "source_changed"); continue;
        }
        b.w.App.syncMcpGestartet({ nativeId: syncMessage.requestId || syncMessage.transactionId });
        assert.equal((await status(id)).job.phase, "running"); assert.equal((await status(id)).job.native_started, true);
        const busy = await tool("organizer_sync_start", { expected_book_revision: await revision() }); assert.equal(busy.structuredContent.code, "native_busy");
        const nativeId = syncMessage.requestId || syncMessage.transactionId;
        b.w.App.syncMcpFehler({ nativeId: "unrelated", code: "native_operation_failed" }); assert.equal((await status(id)).job.phase, "running");
        if (mode === "native_failure") {
          b.w.App.syncMcpFehler({ nativeId, code: "owned-private-error" });
          const failed = await status(id); assert.equal(failed.job.phase, "failed"); assert.equal(failed.job.provider_finished, true); assert.equal(failed.job.data_saved, false);
          assert.equal(failed.job.error_code, "native_operation_failed"); assert.ok(!JSON.stringify(failed).includes("owned-private"));
          continue;
        }
        const transactionId = mode === "no_journal" ? "" : syncMessage.transactionId || "e".repeat(64);
        const payload = { ok: mode !== "provider_error", requestId: syncMessage.requestId, ...(transactionId ? { transactionId } : {}),
          termine: [{ id: "owned-native-result", uid: "owned-native-event", titel: "Native provider result", datum: "2026-11-01", ganztag: true, syncKalenderUid: "owned-calendar" }],
          aufgaben: clone(b.t.daten().aufgaben), kontakte: clone(b.t.daten().kontakte), jahrestage: clone(b.t.daten().jahrestage), geloescht: clone(b.t.daten().geloescht),
          syncMetadaten: clone(b.t.daten().syncMetadaten), letzterSync: Date.now(), letzteSyncs: clone(b.t.daten().letzteSyncs),
          bericht: "owned-private-provider-report", fehler: mode === "provider_error" ? "owned-private-provider-error" : "" };
        if (mode === "source_changed") {
          b.w.App.init({ daten: clone(b.t.daten()), neu: false }); await tick();
          const newBook = JSON.stringify(b.t.daten());
          b.w.App.syncFertig(payload); await tick(); assert.equal(JSON.stringify(b.t.daten()), newBook); assert.equal(commitMessage, undefined);
          const changed = await tool("organizer_sync_status", { run_id: id }); assert.equal(changed.structuredContent.code, "source_changed");
          assert.equal((await status()).job, null); assert.equal((await status()).running, false); continue;
        }
        let draft, secret;
        if (mode === "late_modal") {
          b.w.App.mcpClose(owner); owner = "b".repeat(48);
          await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-followup-client", version: "1" } }); await rpc("notifications/initialized", {});
          b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-sync").click(); await tick();
          draft = b.w.document.querySelector("#briefkasten-url"); secret = b.w.document.querySelector("#briefkasten-kennwort");
          draft.value = "https://owned-draft.example.test"; secret.value = "owned-unsaved-secret";
        }
        const toast = b.w.document.querySelector("#zettel").textContent;
        b.w.App.syncFertig(payload); await tick();
        const adopting = await status(id); assert.equal(adopting.job.phase, "saving"); assert.equal(adopting.job.data_saved, false); assert.equal(commitMessage, undefined);
        assert.ok(b.t.daten().termine.some(item => item.uid === "owned-native-event")); assert.equal(b.w.document.querySelector("#zettel").textContent, toast);
        if (mode === "save_failed") {
          await ack(false); const failed = await status(id); assert.equal(failed.job.phase, "failed"); assert.equal(failed.job.error_code, "save_failed"); assert.equal(commitMessage, undefined); continue;
        }
        for (let i = 0; i < 10 && (await status(id)).job.phase === "saving"; i++) { if (saves.length) await ack(); else await tick(); }
        if (mode === "provider_error") {
          const failed = await status(id); assert.equal(failed.job.phase, "failed"); assert.equal(failed.job.data_saved, true); assert.equal(failed.job.provider_success, false);
          assert.equal(commitMessage, undefined); assert.ok(!JSON.stringify(failed).includes("owned-private")); continue;
        }
        if (mode === "no_journal") {
          const finished = await status(id); assert.equal(finished.job.phase, "completed"); assert.equal(finished.job.commit_required, false); assert.equal(commitMessage, undefined); continue;
        }
        assert.ok(commitMessage); assert.equal(commitMessage.transactionId, transactionId);
        const committing = await status(id); assert.equal(committing.job.phase, "committing"); assert.equal(committing.job.data_saved, true); assert.equal(committing.job.native_commit_confirmed, false);
        const callback = commitMessage.cmd === "sync_commit" ? "syncCommitErgebnis" : "syncBestaetigt";
        b.w.App[callback]({ requestId: "unrelated", transactionId, ok: true }); await tick(); assert.equal((await status(id)).job.phase, "committing");
        b.w.App[callback]({ requestId: commitMessage.requestId, transactionId, ok: mode !== "commit_rejected" }); await tick();
        const finished = await status(id);
        assert.equal(finished.job.phase, mode === "commit_rejected" ? "failed" : "completed"); assert.equal(finished.job.native_commit_confirmed, mode !== "commit_rejected");
        assert.match(finished.job.saved_book_revision, /^[a-f0-9]{64}$/); assert.ok(!JSON.stringify(finished).includes("owned-private"));
        if (mode === "late_modal") {
          assert.equal(b.w.document.querySelector("#briefkasten-url"), draft); assert.equal(draft.value, "https://owned-draft.example.test");
          assert.equal(b.w.document.querySelector("#briefkasten-kennwort"), secret); assert.equal(secret.value, "owned-unsaved-secret");
        }
        b.w.App.syncFertig(payload); await tick(); assert.equal((await status(id)).job.phase, finished.job.phase);
      } finally { b.close(); }
    }
    console.log("MCP SYNC RUN PASS: shared workflow, real save barriers, native commit ACK, partial failures, correlation and duplicate/quiet results " + web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
