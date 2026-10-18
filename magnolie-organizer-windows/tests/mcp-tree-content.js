"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP tree content timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    for (const mode of ["delegate_task", "share_note", "share_appointment", "share_contact", "task_status", "stale_record", "stale_tree", "wrong_peer", "save_failed", "queue_failed", "changed_during_save"]) {
      const b = await harness.exports.boot(web, { aufgaben: [{ id: "task", titel: "Owned task", notiz: "Task note", fremdId: "remote-task", herkunft: "peer-124", erledigt: true }],
        notizen: [{ id: "note", titel: "Owned 🌸 note", text: "Note body", html: "<p>Note body</p>", anhaenge: [] }],
        termine: [{ id: "appointment", titel: "Owned appointment", datum: "2026-10-18", notiz: "Appointment body", syncQuellen: { secret: "provider-private" } }],
        kontakte: [{ id: "contact", uid: "private-contact-uid", vorname: "Owned", nachname: "Contact", syncQuellen: { owned: { id: "private-provider-binding" } }, foto: "private-contact-photo", kontaktpersonen: [{ name: "Other", foto: "private-person-photo" }] }] });
      try {
        if (b.saves().length) b.ack(); await tick();
        b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
        const revision = "a".repeat(64), fingerprint = "B".repeat(64);
        const state = { revision, moeglich: true, an: true, kennung: "owned-root", port: 8737,
          partner: Array.from({ length: 125 }, (_, i) => ({ kennung: "peer-" + i, fingerabdruck: fingerprint, port: 8737, bestaetigt: true })) };
        let sequence = 0, saved = false, sent;
        const post = b.w.webkit.messageHandlers.regression.postMessage;
        b.w.webkit.messageHandlers.regression.postMessage = text => {
          post(text); const message = JSON.parse(text);
          if (message.cmd === "speichern") queueMicrotask(() => {
            saved = mode !== "save_failed";
            if (mode === "changed_during_save") b.t.daten().aufgaben[0].titel = "Concurrent edit";
            b.w.App.gespeichert({ id: message.id, ok: saved });
          });
          if (message.cmd === "baum_mcp") {
            if (message.request.action === "send") { sent = message.request; if (["delegate_task", "share_note"].includes(mode)) assert.equal(saved, true, "send must follow durable metadata ACK"); }
            b.w.App.baumMcpErgebnis({ requestId: message.requestId, ok: true, status: state, action: message.request.action,
              localVerified: true, queuedVerified: mode !== "queue_failed", deliveryConfirmed: false });
          }
        };
        async function rpc(method, params) {
          const invocation = (++sequence).toString(16).padStart(48, "0");
          await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
            ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
          return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
        }
        const call = async (name, args) => (await rpc("tools/call", { name, arguments: args })).result;
        const ok = result => { assert.equal(result?.isError, false, JSON.stringify(result)); return result.structuredContent; };
        await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-tree-content", version: "1" } }); await rpc("notifications/initialized", {});
        const action = ["share_note", "share_appointment", "share_contact", "task_status"].includes(mode) ? mode : "delegate_task";
        const id = action === "share_note" ? "note" : action === "share_appointment" ? "appointment" : action === "share_contact" ? "contact" : "task";
        const view = ok(await call(({ share_note: "organizer_note_read", share_appointment: "organizer_appointment_read", share_contact: "organizer_contact_read" })[action] || "organizer_task_read", { id }));
        const result = await call("organizer_tree_content_send", { action, id, expected_record_revision: mode === "stale_record" ? "0".repeat(64) : view.revision,
          expected_tree_revision: mode === "stale_tree" ? "0".repeat(64) : revision, peer_id: "peer-124", fingerprint: mode === "wrong_peer" ? "C".repeat(64) : fingerprint });
        if (["stale_record", "stale_tree", "wrong_peer", "changed_during_save", "save_failed", "queue_failed"].includes(mode)) {
          assert.equal(result.isError, true, mode + JSON.stringify(result));
          assert.equal(result.structuredContent.code, mode === "save_failed" ? "save_failed" : mode === "queue_failed" ? "invalid_result" : "conflict");
          if (mode !== "queue_failed") assert.equal(sent, undefined);
        } else {
          const receipt = ok(result); assert.equal(receipt.delivery_confirmed, false); assert.equal(receipt.queue_persisted, true);
          assert.equal(receipt.metadata_persisted, ["share_note", "delegate_task"].includes(action));
          assert.equal(sent.peerId, "peer-124"); assert.equal(sent.fingerprint, fingerprint);
          if (action === "share_note") { assert.equal(sent.content.freigabeId, "owned-root:note"); assert.equal(sent.content.quelle, "owned-root"); assert.deepEqual(Array.from(b.t.daten().notizen[0].baumFreigabe.partner), ["peer-124"]); }
          if (action === "delegate_task") { assert.equal(sent.content.herkunft, "peer-124"); assert.equal(b.t.daten().aufgaben[0].delegiertAn, "peer-124"); }
          if (action === "task_status") { assert.equal(sent.kind, "stand"); assert.equal(sent.content.id, "remote-task"); assert.equal(sent.content.erledigt, true); }
          if (action === "share_appointment") { assert.equal(sent.kind, "termin"); assert.ok(!JSON.stringify(sent.content).includes("provider-private")); }
          if (action === "share_contact") { assert.equal(sent.kind, "kontakt"); assert.equal(sent.content.vorname, "Owned"); assert.ok(!JSON.stringify(sent.content).includes("private-")); }
        }
      } finally { b.close(); }
    }
    console.log("MCP TREE CONTENT PASS: domain payloads, paged recipient, record/tree CAS, metadata SaveACK before queue, save/race/receipt failures " + web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
