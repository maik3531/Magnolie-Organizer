"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP tree actions timed out"); process.exit(1); }, 15000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const revision = "a".repeat(64), fingerprint = "B".repeat(64);
      const inbox = Buffer.from(JSON.stringify({ id: "owned-inbox", inhalt: { text: "Owned 🌸 é inbox" } }));
      const state = { revision, moeglich: true, an: false, laeuft: false, name: "Owned tree", kennung: "owned-root", fingerabdruck: fingerprint, port: 8737,
        error_present: false, post: 2, postOffen: 1, inbox_count: 1, inbox_ids: ["owned-inbox"], privat: "owned-private-key", eingang: [{ inhalt: "owned-private-inbox" }],
        weitergabeAngebote: [{ id: "owned-offer", von: "owned-peer", name: "Offer", fingerabdruck: fingerprint }],
        partner: Array.from({ length: 125 }, (_, i) => ({ kennung: "owned-peer-" + i, name: "Peer " + i, adresse: "127.0.0.1", port: 8737, fingerabdruck: fingerprint,
          bestaetigt: true, vertraut: false, kontakte: false, kontaktLoeschen: false, code: "123456", privat: "owned-private-peer-key" })) };
      let sequence = 0, onNative;
      const reply = (message, extra = {}) => {
        if (message.request.action === "inbox_read") {
          const offset = message.request.offset || 0, limit = message.request.limit || 65536, chunk = inbox.subarray(offset, offset + limit);
          b.w.App.baumMcpErgebnis({ requestId: message.requestId, ok: true, id: "owned-inbox", sha256: "c".repeat(64), bytes: inbox.length, offset,
            dataBase64: chunk.toString("base64"), nextOffset: offset + chunk.length < inbox.length ? offset + chunk.length : null, ...extra }); return;
        }
        b.w.App.baumMcpErgebnis({ requestId: message.requestId, ok: true, status: state, action: message.request.action,
          document: { format: "owned-pairing-fixture", gueltigBis: 1900000000 }, localVerified: true, deliveryConfirmed: false, publicAddress: "203.0.113.77",
          ...(message.request.path ? { file: { path: message.request.path, bytes: 128, sha256: "d".repeat(64) } } : {}),
          ...(message.request.format === "qr_svg" ? { qrImage: "data:image/svg+xml;base64," + Buffer.from("<svg xmlns='http://www.w3.org/2000/svg'/>").toString("base64") } : {}),
          discovery: { nachbarn: [{ kennung: "found", name: "Found", adresse: "127.0.0.1", port: 8737, fingerabdruck: fingerprint }] }, ...extra });
      };
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "baum_mcp") { if (onNative) onNative(message); else reply(message); }
      };
      async function rpc(method, params, id) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
          ...(!method.startsWith("notifications/") ? { id: id ?? sequence } : {}), ...(params === undefined ? {} : { params }) } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
      }
      const call = async (name, args = {}, id) => (await rpc("tools/call", { name, arguments: args }, id)).result;
      const read = args => call("organizer_tree_status", args);
      const action = (args, id) => call("organizer_tree_action", { expected_revision: revision, ...args }, id);
      const ok = result => { assert.equal(result?.isError, false, JSON.stringify(result)); return result.structuredContent; };
      const fail = (result, code) => { assert.equal(result?.isError, true, JSON.stringify(result)); assert.equal(result.structuredContent.code, code); };
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-tree-probe", version: "1" } }); await rpc("notifications/initialized", {});
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
      const initial = ok(await read()); assert.equal(initial.peer_total, 125); assert.equal(initial.peers.length, 100); assert.equal(initial.next_offset, 100);
      assert.equal(initial.introductions[0].id, "owned-offer"); assert.equal(initial.inbox_ids[0], "owned-inbox"); assert.ok(!JSON.stringify(initial).includes("owned-private"));
      assert.equal(ok(await read({ offset: 120, limit: 2 })).peers.length, 2);
      const document = ok(await call("organizer_tree_pairing_document", { action: "create", expected_revision: revision, address: "127.0.0.1", port: 8737 }));
      assert.equal(JSON.parse(document.document_json).format, "owned-pairing-fixture"); assert.equal(document.local_verified, true);
      assert.equal(ok(await call("organizer_tree_pairing_document", { action: "import", expected_revision: revision, document_json: document.document_json })).document_json, null);
      const exported = ok(await call("organizer_tree_pairing_document", { action: "create", expected_revision: revision, address: "127.0.0.1", port: 8737, path: "/owned/pairing.json" }));
      assert.equal(exported.file.path, "/owned/pairing.json"); assert.equal(exported.file.sha256, "d".repeat(64));
      const qr = ok(await call("organizer_tree_pairing_document", { action: "create", expected_revision: revision, address: "127.0.0.1", port: 8737, format: "qr_svg", path: "/owned/pairing.svg" }));
      assert.ok(qr.qr_image.startsWith("data:image/svg+xml;base64,"));
      const inspected = ok(await call("organizer_tree_pairing_document", { action: "read_file", expected_revision: revision, path: "/owned/pairing.json" }));
      assert.equal(inspected.document_json, document.document_json); assert.equal(inspected.file.sha256, "d".repeat(64));
      assert.equal(ok(await call("organizer_tree_pairing_document", { action: "import_file", expected_revision: revision, path: "/owned/pairing.json", expected_file_sha256: inspected.file.sha256 })).document_json, null);
      let offset = 0, chunks = [], chunk;
      do {
        chunk = ok(await call("organizer_tree_inbox_read", { id: "owned-inbox", offset, limit: 7, ...(offset ? { expected_sha256: "c".repeat(64) } : {}) }));
        chunks.push(Buffer.from(chunk.data_base64, "base64")); offset = chunk.next_offset;
      } while (offset !== null);
      assert.equal(JSON.parse(Buffer.concat(chunks).toString("utf8")).inhalt.text, "Owned 🌸 é inbox");
      fail(await call("organizer_tree_inbox_read", { id: "owned-inbox", offset: 7 }), "conflict");
      const originalInbox = state.inbox_ids, originalOffers = state.weitergabeAngebote;
      state.inbox_ids = Array.from({ length: 140 }, (_, i) => "inbox-" + i); state.inbox_count = 140;
      state.weitergabeAngebote = Array.from({ length: 130 }, (_, i) => ({ id: "offer-" + i }));
      const later = ok(await read({ offset: 130, limit: 7 }));
      assert.equal(later.inbox_ids[0], "inbox-130"); assert.equal(later.inbox_ids.length, 7); assert.equal(later.introductions.length, 0); assert.equal(later.introduction_total, 130); assert.equal(later.next_offset, 137);
      state.inbox_ids = originalInbox; state.inbox_count = 1; state.weitergabeAngebote = originalOffers;
      const peer = { peer_id: "owned-peer-0", fingerprint };
      for (const args of [
        { action: "settings", enabled: false, name: "New name" }, { action: "search" }, { action: "public_address" },
        { action: "pair", address: "127.0.0.1", port: 8737, fingerprint, request_only: true },
        { action: "confirm", ...peer, accept: true }, { action: "remove", ...peer },
        { action: "partner_settings", ...peer, trusted: false, contacts: true, contact_deletions: false, remote_address: "", remote_port: 8737 },
        { action: "sharing_permission", ...peer, allowed: true },
        { action: "introduce", ...peer, recipient_id: "owned-peer-1", recipient_fingerprint: fingerprint },
        { action: "accept_introduction", offer_id: "owned-offer", accept: false }, { action: "clear_inbox", ids: ["owned-inbox"] }
      ]) {
        let seen;
        onNative = message => { seen = message; reply(message); };
        const result = ok(await action(args)); assert.equal(seen.request.action, args.action); assert.equal(seen.request.expectedRevision, revision);
        assert.equal(result.local_verified, true); assert.equal(result.delivery_confirmed, false); assert.ok(!JSON.stringify(result).includes("owned-private"));
      }
      for (const code of ["conflict", "native_busy", "verification_failed", "profile_locked", "cancelled"]) {
        onNative = message => reply(message, { ok: false, code }); fail(await action({ action: "settings", enabled: false }), code);
      }
      onNative = message => reply(message, { deliveryConfirmed: true }); fail(await action({ action: "search" }), "invalid_result");
      let held;
      const started = new Promise(resolve => { onNative = message => { held = message; resolve(); }; });
      const pending = action({ action: "settings", enabled: false }, 9000); await started;
      b.t.oeffneEinstellungen(); await tick();
      fail(await action({ action: "settings", enabled: false }), "dialog_busy");
      await rpc("notifications/cancelled", { requestId: 9000 }); fail(await pending, "cancelled");
      const toast = b.w.document.querySelector("#zettel").textContent;
      reply(held); await tick(); assert.equal(b.w.document.querySelector("#zettel").textContent, toast);
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves);
      console.log("MCP TREE ACTIONS PASS: bounded public projection, action mapping, native receipts, errors and silent late replies " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
