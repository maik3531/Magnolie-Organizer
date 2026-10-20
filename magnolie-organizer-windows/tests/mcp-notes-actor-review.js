"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve)), plain = value => JSON.parse(JSON.stringify(value));
const watchdog = setTimeout(() => { console.error("Notes actor review test timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) for (const scenario of ["success", "cancel_create", "cancel_read", "source_changed", "session_closed", "bad_digest", "bad_offset", "outside_scope", "draft", "stale", "capacity"]) {
    const b = await harness.exports.boot(web, { personalSync: { actor_id: "11111111-1111-4111-8111-111111111111" },
      notizen: [{ id: "phone-note", titel: "Owned", text: "Original" }, { id: "desktop-only", titel: "Private", text: "Never send this" }] });
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const owner = "a".repeat(48), target = { peer_id: "22222222-2222-4222-8222-222222222222", fingerprint: "ABCD-1234-5678-90EF" };
      const actorId = "44444444-4444-4444-8444-444444444444", ownerToken = "d".repeat(64);
      const selection = { notes: new b.w.Set(["phone-note"]), tasks: new b.w.Set() };
      const local = (await b.t.personalSyncSnapshot(["notes"], 3, target.peer_id, { selection, independentRemovals: true })).find(record => record.kind === "note");
      const incoming = plain(local), image = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3]);
      const imageHash = createHash("sha256").update(image).digest("hex");
      incoming.value.text = "Incoming Grüße 🌸"; incoming.value.modified_ms++;
      incoming.value.attachments = [{ attachment_id: "phone-image", name: "phone.png", kind: "image", mime: "image/png", size: image.length, sha256: imageHash }];
      incoming.hash = await b.t.personalSyncHash(incoming.value);
      incoming.modified_ms = incoming.value.modified_ms; incoming.clock.push({ actor_id: target.peer_id, counter: 1 });
      incoming.clock.sort((a, z) => a.actor_id.localeCompare(z.actor_id));
      if (scenario === "outside_scope") incoming.id = "outside-scope";
      const members = { notes: ["phone-note"], tasks: [] };
      const projection = { request: { format: 3, run_id: actorId, trigger: "manual", modules: ["notes"] },
        content_scope: { format: 10, epoch: "55555555-5555-4555-8555-555555555555", revision: 1,
          scope_hash: await b.t.personalSyncHash(members), members }, intents: [],
        batch: { message_id: "66666666-6666-4666-8666-666666666666", commit_token: "77777777-7777-4777-8777-777777777777",
          records: [incoming], records_hash: await b.t.personalSyncHash([incoming]) } };
      const raw = Buffer.from(JSON.stringify(projection)), viewRevision = createHash("sha256").update(raw).digest("hex");
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
      let held = null, creates = 0, starts = 0, cancels = 0; const pendingCreates = [];
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      const answer = message => {
        const r = message.request; let response;
        if (r.action === "notes_actor_source") response = { sourceRevision: "b".repeat(64) };
        else if (r.action === "notes_actor_create") response = { actorId: scenario === "capacity" ? "44444444-4444-4444-8444-" + pendingCreates.indexOf(message).toString(16).padStart(12, "0") : actorId, ownerToken, bookSource: "" };
        else if (r.action === "notes_actor_start") response = { actor: { dispatch_started: true, persisted: false } };
        else if (r.action === "notes_actor_cancel") response = { actor: { phase: "cancelled" } };
        else if (r.action === "notes_actor_status") response = { actor: { phase: "receiving", packets: 3 } };
        else if (r.action === "notes_actor_read") {
          const source = r.attachmentSha256 ? image : raw, limit = Math.min(r.limit, r.attachmentSha256 ? 7 : 37);
          if (r.expectedRevision) assert.equal(r.expectedRevision, scenario === "bad_digest" ? "f".repeat(64) : viewRevision);
          const end = Math.min(source.length, r.offset + limit);
          response = { actor: { revision: scenario === "bad_digest" ? "f".repeat(64) : viewRevision, batch_ready: true,
            offset: r.offset, total_bytes: source.length, next_offset: end < source.length ? end : null,
            data_base64: source.subarray(r.offset, end).toString("base64"),
            ...(r.attachmentSha256 ? { attachment_sha256: imageHash, mime: "image/png" } : {}) } };
          if (scenario === "bad_offset") response.actor.next_offset = 99999;
        } else throw Error("Unexpected native actor action " + r.action);
        b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: true, ...response });
      };
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text); if (message.cmd !== "telefon_mcp") return;
        const action = message.request.action;
        if (action === "notes_actor_create") creates++;
        if (action === "notes_actor_start") starts++;
        if (action === "notes_actor_cancel") cancels++;
        if (scenario === "capacity" && action === "notes_actor_create") { pendingCreates.push(message); return; }
        if (scenario === "cancel_create" && action === "notes_actor_create" || ["cancel_read", "source_changed", "session_closed"].includes(scenario) && action === "notes_actor_read") { held = message; return; }
        queueMicrotask(() => answer(message));
      };
      const args = { ...target, expected_book_revision: scenario === "stale" ? "0".repeat(64) : await b.t.personalSyncHash(before) };
      if (scenario === "capacity") {
        const results = await Promise.allSettled(Array.from({ length: 5 }, () => b.t.mcpNotesActorStart(owner, args, new b.w.AbortController().signal)));
        assert.equal(results.filter(result => result.status === "fulfilled").length, 4);
        assert.equal(results.find(result => result.status === "rejected").reason.code, "native_busy");
        for (const result of results.filter(result => result.status === "fulfilled")) b.t.mcpNotesActorCancel(owner, result.value.operation_id);
        for (let n = 0; n < 50 && pendingCreates.length < 4; n++) await tick();
        assert.equal(pendingCreates.length, 4); pendingCreates.forEach(answer);
        for (let n = 0; n < 50 && cancels < 4; n++) await tick();
        assert.equal(cancels, 4); assert.equal(starts, 0);
        assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves); continue;
      }
      if (scenario === "draft") { b.t.oeffneTerminBlatt(null, "2026-10-19"); b.input("#tb-titel", "Existing actor draft"); }
      if (["draft", "stale"].includes(scenario)) {
        await assert.rejects(b.t.mcpNotesActorStart(owner, args, new b.w.AbortController().signal));
        assert.equal(creates, 0); assert.equal(starts, 0); continue;
      }
      const initial = await b.t.mcpNotesActorStart(owner, args, new b.w.AbortController().signal), id = initial.operation_id;
      assert.throws(() => b.t.mcpNotesActorStatus("z".repeat(48), id), error => error.code === "not_found");
      let state = initial, closed = false;
      for (let n = 0; n < 600; n++) {
        await tick();
        if (held) {
          const message = held; held = null;
          if (scenario === "source_changed") b.t.daten().einstellungen.allgemein.concurrentOwnedChange = true;
          else if (scenario === "session_closed") { b.w.App.mcpClose(owner); closed = true; }
          else {
            b.t.mcpNotesActorCancel(owner, id);
            b.t.oeffneTerminBlatt(null, "2026-10-19"); b.input("#tb-titel", "Owned late actor draft");
          }
          answer(message);
        }
        if (closed) { assert.throws(() => b.t.mcpNotesActorStatus(owner, id)); if (cancels) break; continue; }
        state = b.t.mcpNotesActorStatus(owner, id);
        if (["review", "failed", "cancelled"].includes(state.phase)) break;
      }
      if (scenario === "success") {
        assert.equal(state.phase, "review", JSON.stringify(state)); assert.equal(state.summary.attachments, 1); assert.equal(state.summary.conflicts, 0);
        const review = b.t.mcpNotesActorReview(owner, id);
        assert.equal(review.book.notizen.find(note => note.id === "phone-note").text, "Incoming Grüße 🌸");
        assert.equal(review.book.notizen.find(note => note.id === "desktop-only").text, "Never send this");
        const reply = review.batches.flatMap(batch => batch.records);
        assert.equal(reply.find(record => record.kind === "note").value.text, "Incoming Grüße 🌸");
        assert.ok(!reply.some(record => record.id === "desktop-only")); assert.equal(review.sources.length, 1);
        assert.ok(!JSON.stringify(state).includes(ownerToken)); b.t.mcpNotesActorCancel(owner, id);
      } else if (!closed) assert.equal(state.phase, scenario.startsWith("cancel_") ? "cancelled" : "failed", scenario + JSON.stringify(state));
      for (let n = 0; n < 30 && !cancels; n++) await tick();
      assert.equal(cancels, 1, scenario + ": native context was not retired exactly once");
      if (scenario === "cancel_create") assert.equal(starts, 0, "Cancelled late creation dispatched a snapshot start");
      if (scenario.startsWith("cancel_")) assert.equal(state.native_outcome_unknown, scenario === "cancel_read", "Cancellation falsely promised native recall");
      if (scenario.startsWith("cancel_")) assert.equal(b.w.document.querySelector("#tb-titel").value, "Owned late actor draft");
      assert.equal(b.saves().length, saves, "Review preparation saved the actual book");
      if (scenario !== "source_changed") assert.equal(JSON.stringify(b.t.daten()), before, scenario + ": private review mutated actual data");
    } finally { b.close(); }
  }
  console.log("NOTES ACTOR REVIEW PASSED: native byte paging/digests, private merge/reply, owner isolation, cancellation/late create/drafts, session close and unchanged book on both frontends");
})().then(() => clearTimeout(watchdog), error => { clearTimeout(watchdog); console.error(error); process.exitCode = 1; });
