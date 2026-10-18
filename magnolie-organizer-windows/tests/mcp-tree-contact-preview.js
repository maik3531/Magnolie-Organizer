"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP tree contact preview timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    for (const mode of ["success", "no_success", "no_permission", "bound_drop", "too_many", "stale", "unknown_share"]) {
      const b = await harness.exports.boot(web, { kontakte: Array.from({ length: 16 }, (_, i) => ({ id: "owned-" + i, uid: "owned-uid-" + i, vorname: "Owned", nachname: "Person " + i,
        telefone: [{ wert: "+49305550123", typen: ["CELL"] }], baumKontakt: { freigabeId: "owned-share-" + i, partner: ["peer"], version: 1, quelle: "owned-root" } })),
        baumKontaktErfolgreich: { peer: mode !== "no_success" }, baumKontaktBestand: { peer: mode === "bound_drop" ? 40 : 16 },
        baumKontaktGeloescht: Array.from({ length: mode === "too_many" ? 2 : 1 }, (_, i) => ({ freigabeId: "deleted-share-" + i, version: 2, quelle: "owned-root", geaendert: 1792281600000, name: "Deleted person", partner: ["peer"] })) });
      try {
        if (b.saves().length) b.ack(); await tick();
        b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
        const revision = "a".repeat(64), fingerprint = "B".repeat(64);
        const state = { revision, moeglich: true, an: true, kennung: "owned-root", port: 8737, partner: [{ kennung: "peer", fingerabdruck: fingerprint, port: 8737, bestaetigt: true, kontaktLoeschen: mode !== "no_permission", kontaktFaehigkeiten: { kontakt_sync: [2] } }] };
        let sequence = 0, sent;
        const post = b.w.webkit.messageHandlers.regression.postMessage;
        b.w.webkit.messageHandlers.regression.postMessage = text => {
          post(text); const message = JSON.parse(text);
          if (message.cmd === "baum_mcp") {
            if (message.request.action === "send") sent = message.request;
            b.w.App.baumMcpErgebnis({ requestId: message.requestId, ok: true, status: state, action: message.request.action, localVerified: true, queuedVerified: true, deliveryConfirmed: false });
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
        await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-tree-preview", version: "1" } }); await rpc("notifications/initialized", {});
        const before = JSON.stringify(b.t.daten()), saves = b.saves().length, common = { expected_tree_revision: revision, peer_id: "peer", fingerprint };
        const preview = ok(await call("organizer_tree_contact_preview", common));
        assert.equal(preview.contacts_total, 16); assert.equal(preview.bound_count, 16); assert.equal(preview.new_count, 0); assert.equal(preview.duplicate_total, 120); assert.equal(preview.duplicate_pairs.length, 100);
        assert.equal(ok(await call("organizer_tree_contact_preview", { ...common, offset: 100, limit: 7 })).duplicate_pairs.length, 7);
        assert.equal(preview.blocked_reason, ["bound_drop", "too_many"].includes(mode) ? "deletion_safety" : "none");
        assert.equal(preview.deletion_total, ["no_success", "no_permission", "bound_drop", "too_many"].includes(mode) ? 0 : 1);
        const result = await call("organizer_tree_contact_delete_proposal", { ...common, expected_book_revision: mode === "stale" ? "0".repeat(64) : preview.book_revision, share_id: mode === "unknown_share" ? "arbitrary-share" : "deleted-share-0" });
        if (mode === "success") {
          const receipt = ok(result); assert.equal(receipt.queue_persisted, true); assert.equal(receipt.delivery_confirmed, false); assert.equal(sent.kind, "kontakt_loeschen");
          assert.equal(sent.content.freigabeId, "deleted-share-0"); assert.equal(sent.content.version, 2); assert.equal(sent.content.quelle, "owned-root");
        } else { assert.equal(result.isError, true); assert.equal(result.structuredContent.code, "conflict"); assert.equal(sent, undefined); }
        assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves);
      } finally { b.close(); }
    }
    console.log("MCP TREE CONTACT PREVIEW PASS: shared counts/duplicates, bounded pages, unchanged bindings, stored tombstone selection, sync/permission/drop/count/CAS safeguards " + web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
