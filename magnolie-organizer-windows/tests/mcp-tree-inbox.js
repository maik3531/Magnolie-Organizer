"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict"), crypto = require("node:crypto");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP tree inbox timed out"); process.exit(1); }, 45000);
(async () => {
  for (const web of harness.exports.roots) {
    for (const mode of ["aufgabe", "termin", "kontakt", "notiz", "notiz_sync", "stale_book", "bad_digest", "wrong_peer", "snapshot_failed", "changed_at_snapshot", "save_failed", "consume_conflict", "invalid_offer", "cancel",
      "contact_merge", "contact_replace", "contact_keep", "contact_new", "contact_skip", "contact_auto_new", "contact_auto_conflict", "contact_newer", "contact_missing_decision", "contact_invalid_list", "delete_contact", "delete_without_permission"]) {
      const contactReview = mode.startsWith("contact_"), deletion = mode.startsWith("delete_");
      const b = await harness.exports.boot(web, contactReview || deletion ? { kontakte: [{ id: "local", uid: "stable-local-uid", vorname: "Local", nachname: "Contact", notiz: "Local note", telefone: [{ wert: "+49305550123", typen: ["CELL"] }],
        baumKontakt: { freigabeId: "owned-remote-contact", partner: ["owned-peer"], version: 1, quelle: "owned-peer" } }] } : {});
      try {
        if (b.saves().length) b.ack(); await tick();
        b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
        const revision = "a".repeat(64), fingerprint = "B".repeat(64), kind = contactReview ? "kontakt_sync" : deletion ? "kontakt_loeschen" : ["aufgabe", "termin", "kontakt", "notiz", "notiz_sync"].includes(mode) ? mode : "aufgabe";
        const item = { id: "owned-inbox", von: "owned-peer", inhalt: { art: kind, id: "owned-remote-task", herkunft: "owned-peer", titel: mode === "invalid_offer" ? "" : "Owned 🌸 entry", notiz: "Body", text: "Note body", html: "<p>Note body</p>",
          freigabeId: "owned-remote-note", quelle: "owned-peer", version: 1, anhaenge: [], datum: "2026-10-18", vorname: "Owned", nachname: "Contact" } };
        if (contactReview || deletion) Object.assign(item.inhalt, { freigabeId: "owned-remote-contact", version: 2, fassung: 2, kontakt: { vorname: "Remote", nachname: "Contact", notiz: "Remote note", telefone: [{ wert: "+49305550124", art: "mobile" }], emailEintraege: [], anschriften: [] } });
        if (mode === "contact_auto_new") { item.inhalt.freigabeId = "separate-share"; item.inhalt.kontakt.nachname = "Separate"; }
        const raw = Buffer.from(JSON.stringify(item)), digest = crypto.createHash("sha256").update(raw).digest("hex");
        const state = { revision, moeglich: true, an: true, kennung: "owned-root", port: 8737, partner: [{ kennung: "owned-peer", fingerabdruck: fingerprint, port: 8737, bestaetigt: true, kontaktLoeschen: mode !== "delete_without_permission" }] };
        let sequence = 0, saved = false, consumed = false, checkpoint = false, snapshotMessage, notifySnapshot;
        const post = b.w.webkit.messageHandlers.regression.postMessage;
        b.w.webkit.messageHandlers.regression.postMessage = text => {
          post(text); const message = JSON.parse(text);
          if (message.cmd === "speichern") queueMicrotask(() => { saved = mode !== "save_failed" || !checkpoint; b.w.App.gespeichert({ id: message.id, ok: saved }); });
          if (message.cmd === "mutations_snapshot") {
            checkpoint = true; snapshotMessage = message;
            if (mode === "cancel") { notifySnapshot(); return; }
            queueMicrotask(() => {
              if (mode === "changed_at_snapshot") b.t.daten().notizen.push({ id: "concurrent", titel: "Concurrent edit", text: "Concurrent edit" });
              b.w.App.mutationsSnapshot({ token: message.token, ok: mode !== "snapshot_failed" });
            });
          }
          if (message.cmd === "baum_mcp") {
            const request = message.request;
            if (request.action === "inbox_read") {
              // Multiple UTF-8 boundaries even for small test offers.
              const offset = request.offset || 0, chunk = raw.subarray(offset, offset + 7);
              b.w.App.baumMcpErgebnis({ requestId: message.requestId, ok: true, id: item.id, sha256: request.expectedSha256, bytes: raw.length, offset,
                dataBase64: chunk.toString("base64"), nextOffset: offset + chunk.length === raw.length ? null : offset + chunk.length }); return;
            }
            if (request.action === "consume_inbox") { assert.equal(saved, true); assert.equal(checkpoint, true); consumed = true; assert.equal(request.expectedSha256, digest); }
            b.w.App.baumMcpErgebnis({ requestId: message.requestId, ok: !(request.action === "consume_inbox" && mode === "consume_conflict"), code: "conflict", status: state, action: request.action, localVerified: true, deliveryConfirmed: false });
          }
        };
        async function rpc(method, params, id) {
          const invocation = (++sequence).toString(16).padStart(48, "0");
          await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
            ...(!method.startsWith("notifications/") ? { id: id ?? sequence } : {}), params } });
          return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
        }
        const call = async (name, args, id) => (await rpc("tools/call", { name, arguments: args }, id)).result;
        const ok = result => { assert.equal(result?.isError, false, mode + JSON.stringify(result)); return result.structuredContent; };
        await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-tree-inbox", version: "1" } }); await rpc("notifications/initialized", {});
        const book = ok(await call("organizer_book_revision_read", {})), before = JSON.stringify(b.t.daten());
        const waiting = new Promise(resolve => { notifySnapshot = resolve; });
        const decision = mode === "contact_invalid_list" ? "merge" : mode.startsWith("contact_auto") ? "auto" : mode.slice("contact_".length);
        const choices = contactReview && mode !== "contact_missing_decision" ? { contact_decision: decision, ...(!["new", "skip", "auto"].includes(decision) ? { contact_id: "local" } : {}),
          ...(decision === "merge" ? { field_choices: [{ field: "vorname", choice: "incoming" }], list_choices: [{ field: "telefone", incoming_index: mode === "contact_invalid_list" ? 99 : 0, choice: "replace", existing_index: 0 }] } : {}) } : deletion ? { contact_decision: "delete" } : {};
        const pending = call("organizer_tree_inbox_apply", { id: item.id, expected_sha256: mode === "bad_digest" ? "0".repeat(64) : digest,
          expected_book_revision: mode === "stale_book" ? "0".repeat(64) : book.revision, expected_tree_revision: revision, sender_fingerprint: mode === "wrong_peer" ? "C".repeat(64) : fingerprint, ...choices }, 9000);
        if (mode === "cancel") { await waiting; await rpc("notifications/cancelled", { requestId: 9000 }); b.w.App.mutationsSnapshot({ token: snapshotMessage.token, ok: true }); }
        const result = await pending;
        const failure = { stale_book: "conflict", bad_digest: "invalid_result", wrong_peer: "conflict", snapshot_failed: "snapshot_failed", changed_at_snapshot: "conflict", save_failed: "save_failed", consume_conflict: "conflict", invalid_offer: "conflict", cancel: "cancelled",
          contact_newer: "conflict", contact_auto_conflict: "conflict", contact_missing_decision: "invalid_selection", contact_invalid_list: "invalid_selection", delete_without_permission: "invalid_selection" }[mode];
        if (failure) {
          assert.equal(result.isError, true, mode + JSON.stringify(result)); assert.equal(result.structuredContent.code, failure, mode + JSON.stringify(result));
          assert.equal(consumed, mode === "consume_conflict");
          if (!["changed_at_snapshot", "save_failed", "consume_conflict"].includes(mode)) assert.equal(JSON.stringify(b.t.daten()), before, mode);
        } else {
          const receipt = ok(result); assert.equal(receipt.persisted, true); assert.equal(receipt.inbox_removed, true); assert.equal(consumed, true);
          if (contactReview) {
            const local = b.t.daten().kontakte.find(contact => contact.id === "local");
            assert.equal(local.uid, "stable-local-uid");
            assert.equal(local.vorname, ["contact_keep", "contact_new", "contact_auto_new", "contact_skip"].includes(mode) ? "Local" : "Remote");
            if (["contact_new", "contact_auto_new"].includes(mode)) assert.equal(b.t.daten().kontakte.length, 2);
            else if (mode === "contact_skip") { assert.equal(local.baumKontakt.version, 1); assert.equal(b.t.daten().baumKontaktAblehnungen.length, 1); }
            else { assert.equal(local.baumKontakt.version, 2); assert.equal(local.telefone[0].wert, mode === "contact_keep" ? "+49305550123" : "+49305550124"); }
          } else if (deletion) { assert.equal(b.t.daten().kontakte.length, 0); assert.equal(b.t.daten().baumKontaktLoeschStaende.length, 1); }
          else {
            const section = ({ aufgabe: "aufgaben", termin: "termine", kontakt: "kontakte", notiz: "notizen", notiz_sync: "notizen" })[kind];
            assert.ok(b.t.daten()[section].some(record => record.titel === "Owned 🌸 entry" || record.vorname === "Owned"));
          }
        }
        assert.ok(!b.messages.some(message => message.cmd === "baum_eingang_geleert"), "MCP must not fire-and-forget GUI inbox cleanup");
      } finally { b.close(); }
    }
    console.log("MCP TREE INBOX PASS: actual offer handlers, UTF-8 chunks/digest, draft isolation, checkpoint/SaveACK/consumption ordering, CAS/failure/cancel gates " + web);
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
