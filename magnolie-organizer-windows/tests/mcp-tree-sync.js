"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP tree sync timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    for (const mode of ["success", "introduced", "save_failed", "queue_failed", "source_changed", "cancel", "too_large", "stale", "contact_modern", "contact_legacy", "contact_incompatible", "contact_empty"]) {
      const contacts = mode.startsWith("contact_");
      const huge = mode === "too_large" ? "x".repeat(360000) : "Owned body";
      const b = await harness.exports.boot(web, { notizen: [{ id: "owned-note", titel: "Owned note", text: huge, html: "<p>" + huge + "</p>", anhaenge: [],
        ...(mode === "introduced" ? { baumFreigabe: { id: "sponsor:note", partner: ["sponsor"], anhangPartner: ["sponsor"] } } : {}) },
        ...(mode === "introduced" ? [{ id: "excluded-note", titel: "Excluded", text: "Private", html: "<p>Private</p>", anhaenge: [] }] : [])],
        aufgaben: [{ id: "owned-task", titel: "Owned task", delegiertAn: mode === "introduced" ? "sponsor" : "" },
          { id: "foreign-task", titel: "Foreign task", fremdId: "remote", herkunft: "other" }],
        kontakte: mode === "contact_empty" ? [] : [{ id: "owned-contact", uid: "stable-owned-contact", vorname: "Owned", nachname: "Contact", ...(mode === "contact_incompatible" ? { anzeigename: "Incompatible nickname" } : {}) }] });
      try {
        if (b.saves().length) b.ack(); await tick();
        b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
        const revision = "a".repeat(64), fingerprint = "B".repeat(64), messages = [];
        const state = { revision, moeglich: true, an: true, kennung: "owned-root", port: 8737, partner: [{ kennung: "peer", fingerabdruck: fingerprint, port: 8737, bestaetigt: true,
          ...(mode === "introduced" ? { weitergabeVon: "sponsor", weitergabeQuelle: "sponsor" } : {}),
          ...(mode === "contact_modern" ? { kontaktFaehigkeiten: { kontakt_sync: [1, 2, 3] } } : {}) }] };
        let sequence = 0, saved = false, held;
        const post = b.w.webkit.messageHandlers.regression.postMessage;
        const reply = message => b.w.App.baumMcpErgebnis({ requestId: message.requestId, ok: true, status: state, action: message.request.action, localVerified: true, queuedVerified: mode !== "queue_failed", deliveryConfirmed: false });
        b.w.webkit.messageHandlers.regression.postMessage = text => {
          post(text); const message = JSON.parse(text);
          if (message.cmd === "speichern") queueMicrotask(() => { saved = mode !== "save_failed"; b.w.App.gespeichert({ id: message.id, ok: saved }); });
          if (message.cmd === "baum_mcp") {
            if (message.request.action === "send") {
              assert.equal(saved, true, "metadata must be saved before any outgoing content"); messages.push(message.request);
              if (mode === "cancel") { held = message; return; }
              if (mode === "source_changed") b.t.daten().aufgaben[0].titel = "Concurrent edit";
            }
            reply(message);
          }
        };
        async function rpc(method, params) {
          const invocation = (++sequence).toString(16).padStart(48, "0");
          await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
            ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
          return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
        }
        const call = async (name, args) => (await rpc("tools/call", { name, arguments: args })).result;
        const ok = result => { assert.equal(result?.isError, false, mode + JSON.stringify(result)); return result.structuredContent; };
        await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-tree-sync", version: "1" } }); await rpc("notifications/initialized", {});
        const book = ok(await call("organizer_book_revision_read", {})), before = JSON.stringify(b.t.daten());
        const result = await call("organizer_tree_sync_start", { expected_book_revision: mode === "stale" ? "0".repeat(64) : book.revision, expected_tree_revision: revision, peer_id: "peer", fingerprint, ...(contacts ? { scope: "contacts" } : {}) });
        if (["stale", "contact_empty"].includes(mode)) { assert.equal(result.isError, true); assert.equal(result.structuredContent.code, mode === "stale" ? "conflict" : "invalid_selection"); assert.equal(messages.length, 0); continue; }
        let status = ok(result), run_id = status.run_id;
        for (let i = 0; i < 100 && !["completed", "failed", "cancelled"].includes(status.phase); i++) {
          await tick();
          if (mode === "cancel" && held) { ok(await call("organizer_tree_sync_cancel", { run_id })); reply(held); held = null; }
          status = ok(await call("organizer_tree_sync_status", { run_id }));
        }
        assert.equal(status.delivery_confirmed, false);
        if (["contact_modern", "contact_legacy"].includes(mode)) {
          assert.equal(status.phase, "completed", JSON.stringify(status)); assert.equal(status.metadata_persisted, true); assert.equal(status.scope, "contacts");
          assert.equal(status.queued_verified, mode === "contact_modern" ? 1 : 2); assert.equal(messages.at(-1).kind, "kontakt_sync");
          const local = b.t.daten().kontakte[0], sent = messages.at(-1).content;
          assert.equal(local.uid, "stable-owned-contact"); assert.equal(local.baumKontakt.freigabeId, "owned-root:owned-contact"); assert.ok(local.baumKontakt.partner.includes("peer"));
          assert.equal(sent.fassung, mode === "contact_modern" ? 3 : 1); assert.equal(sent.kontakt.vorname, "Owned"); assert.equal(b.t.daten().baumKontaktErfolgreich.peer, false, "queue acceptance is not successful remote synchronization");
        } else if (["success", "introduced"].includes(mode)) {
          assert.equal(status.phase, "completed", JSON.stringify(status)); assert.equal(status.metadata_persisted, true); assert.equal(status.queued_verified, 3); assert.equal(status.messages_total, 3);
          assert.deepEqual(messages.map(message => message.kind), ["notiz", "aufgabe", "sync_anfrage"]);
          assert.equal(messages[1].content.herkunft, "owned-root"); assert.ok(!JSON.stringify(messages).includes("Foreign task") && !JSON.stringify(messages).includes("Excluded"));
          assert.ok(b.t.daten().notizen[0].baumFreigabe.partner.includes("peer"));
        } else {
          assert.equal(status.phase, mode === "cancel" ? "cancelled" : "failed", JSON.stringify(status));
          assert.equal(status.error_code, ({ save_failed: "save_failed", queue_failed: "invalid_result", source_changed: "source_changed", cancel: "cancelled", too_large: "content_too_large", contact_incompatible: "native_operation_failed" })[mode]);
          assert.equal(messages.length, ["save_failed", "too_large", "contact_incompatible"].includes(mode) ? 0 : 1);
          if (["too_large", "contact_incompatible"].includes(mode)) assert.equal(JSON.stringify(b.t.daten()), before);
        }
      } finally { b.close(); }
    }
    console.log("MCP TREE SYNC PASS: shared GUI selection/source restriction, complete preflight, asynchronous status/cancel, durable metadata before queue, partial/race/error receipts " + web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
