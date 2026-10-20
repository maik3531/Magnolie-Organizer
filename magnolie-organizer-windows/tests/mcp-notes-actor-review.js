"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve)), plain = value => JSON.parse(JSON.stringify(value));
const watchdog = setTimeout(() => { console.error("Notes actor review test timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) for (const scenario of ["success", "cancel_create", "cancel_read", "source_changed", "session_closed", "bad_digest", "bad_offset", "outside_scope", "draft", "stale", "capacity",
    "commit", "commit_remote", "commit_save_failed", "commit_checkpoint_failed", "commit_stale", "commit_deletions", "commit_stage_changed", "commit_cancel_save", "commit_late_draft", "decision_delete", "decision_restore", "decision_cancel"]) {
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
      if (scenario === "commit_deletions") projection.intents = [{ kind: "personal_sync.deletion_proposals", body: { run_id: actorId } }];
      const typedProposal = { proposal_id: "88888888-8888-4888-8888-888888888888", kind: "note", id: "phone-note", parent_id: "",
        clock: plain(incoming.clock), prior_hash: incoming.hash, deleted_ms: incoming.modified_ms, label: "Native typed deletion" };
      if (scenario.startsWith("decision_")) projection.intents = [{ kind: "personal_sync.deletion_proposals", pending_message_id: "99999999-9999-4999-8999-999999999999",
        commit_token: "c".repeat(64), body: { run_id: actorId, proposals: [typedProposal] } }];
      const raw = Buffer.from(JSON.stringify(projection)), viewRevision = createHash("sha256").update(raw).digest("hex");
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
      let held = null, creates = 0, starts = 0, cancels = 0, savedSequence = 0, savedHash = "", plan = null, coreCommits = 0, heldSave = null, holdDecision = false;
      let signalDecisionRead;
      const decisionReadReady = new Promise(resolve => { signalDecisionRead = resolve; });
      const pendingCreates = [];
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      const answer = message => {
        const r = message.request; let response;
        if (r.action === "notes_actor_source") response = { sourceRevision: "b".repeat(64) };
        else if (r.action === "notes_actor_create") response = { actorId: scenario === "capacity" ? "44444444-4444-4444-8444-" + pendingCreates.indexOf(message).toString(16).padStart(12, "0") : actorId, ownerToken, bookSource: "" };
        else if (r.action === "notes_actor_start") response = { actor: { dispatch_started: true, persisted: false } };
        else if (r.action === "notes_actor_cancel") response = { actor: { phase: "cancelled" } };
        else if (r.action === "notes_actor_status") response = { actor: { phase: "receiving", packets: 3,
          phone_persisted: scenario === "commit_remote" && coreCommits === 1, book_persisted: coreCommits === 1,
          reply_queued: coreCommits === 1, completion_report_queued: scenario === "commit_remote" && coreCommits === 1 } };
        else if (r.action === "notes_actor_prepare_commit") {
          assert.ok(savedSequence > 0, "Native plan preceded actual baseline SaveACK");
          plan = { sequence: savedSequence, hash: r.bookSha256 };
          response = { actor: { claim_token: "e".repeat(64), after_sha256: plan.hash, view_revision: viewRevision, book_persisted: false } };
        } else if (r.action === "notes_actor_commit") {
          assert.ok(savedSequence > plan.sequence, "Core commit preceded a new actual native SaveACK");
          assert.equal(savedHash, plan.hash); assert.equal(r.claimToken, "e".repeat(64));
          if (scenario === "commit_stage_changed") { b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: false, code: "source_changed" }); return; }
          coreCommits++; response = { actor: { book_persisted: true, core_committed: true, phone_persisted: false, book_sha256: savedHash, save_sequence: savedSequence } };
        } else if (r.action === "notes_actor_reply") {
          assert.equal(coreCommits, 1, "Reply queued before the actual native core commit");
          assert.equal(r.claimToken, "e".repeat(64));
          assert.ok(r.batches.flatMap(batch => batch.records).some(record => record.kind === "note" && record.value.text === "Incoming Grüße 🌸"));
          response = { actor: { reply_queued: true, message_count: r.batches.length, book_persisted: true, phone_persisted: false, delivery_confirmed: false } };
        }
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
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern") {
          const isActor = JSON.parse(message.text).notizen.some(note => note.id === "phone-note" && note.text === "Incoming Grüße 🌸");
          const ok = !(scenario === "commit_save_failed" && isActor);
          if (ok) { savedSequence++; savedHash = createHash("sha256").update(message.text).digest("hex"); }
          const ack = () => {
            b.w.App.gespeichert({ id: message.id, ok, standSha256: savedHash });
            if (scenario === "commit_late_draft" && isActor) { b.t.oeffneTerminBlatt(null, "2026-10-19"); b.input("#tb-titel", "Late commit draft"); }
          };
          if (scenario === "commit_cancel_save" && isActor) heldSave = ack;
          else queueMicrotask(ack);
          return;
        }
        if (message.cmd === "mutations_snapshot") { queueMicrotask(() => b.w.App.mutationsSnapshot({ token: message.token, ok: scenario !== "commit_checkpoint_failed" })); return; }
        if (message.cmd !== "telefon_mcp") return;
        const action = message.request.action;
        if (action === "notes_actor_create") creates++;
        if (action === "notes_actor_start") starts++;
        if (action === "notes_actor_cancel") cancels++;
        if (scenario === "capacity" && action === "notes_actor_create") { pendingCreates.push(message); return; }
        if (holdDecision && action === "notes_actor_read" && message.request.limit === 1) { held = message; signalDecisionRead(); return; }
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
      if (scenario === "success" || scenario.startsWith("commit") || scenario.startsWith("decision_")) {
        assert.equal(state.phase, "review", JSON.stringify(state)); assert.equal(state.summary.attachments, 1); assert.equal(state.summary.conflicts, 0);
        const review = b.t.mcpNotesActorReview(owner, id);
        assert.equal(review.book.notizen.find(note => note.id === "phone-note").text, "Incoming Grüße 🌸");
        assert.equal(review.book.notizen.find(note => note.id === "desktop-only").text, "Never send this");
        const reply = review.batches.flatMap(batch => batch.records);
        assert.equal(reply.find(record => record.kind === "note").value.text, "Incoming Grüße 🌸");
        assert.ok(!reply.some(record => record.id === "desktop-only")); assert.equal(review.sources.length, 1);
        assert.ok(!JSON.stringify(state).includes(ownerToken));
        if (scenario.startsWith("decision_")) {
          const choice = { proposal_id: typedProposal.proposal_id, decision: scenario === "decision_delete" ? "delete" : "restore",
            expected_clock: plain(typedProposal.clock), allow_conflict: true };
          await assert.rejects(b.t.mcpNotesActorDecide("z".repeat(48), id, state.review_revision, [choice]), error => error.code === "not_found");
          await assert.rejects(b.t.mcpNotesActorDecide(owner, id, state.review_revision, [{ ...choice, expected_clock: [] }]), error => error.code === "conflict");
          await assert.rejects(b.t.mcpNotesActorDecide(owner, id, state.review_revision, [choice, choice]), error => error.code === "invalid_argument");
          if (scenario === "decision_cancel") {
            holdDecision = true;
            const decision = b.t.mcpNotesActorDecide(owner, id, state.review_revision, [choice]).then(() => null, error => error);
            await Promise.race([decisionReadReady, decision.then(error => { throw error || Error("Typed decision finished before its held native recheck"); })]);
            assert.ok(held); b.t.mcpNotesActorCancel(owner, id);
            b.t.oeffneTerminBlatt(null, "2026-10-19"); b.input("#tb-titel", "Late typed deletion draft");
            answer(held); held = null;
            assert.equal((await decision).code, "cancelled");
            assert.equal(b.w.document.querySelector("#tb-titel").value, "Late typed deletion draft");
          } else {
            const decided = await b.t.mcpNotesActorDecide(owner, id, state.review_revision, [choice]);
            assert.notEqual(decided.review_revision, state.review_revision); assert.equal(decided.summary.reviewed_deletion_intents, 1);
            assert.equal(decided.summary.unapplied_deletion_intents, 1, "Private review bypassed native terminal deletion save gates");
            const typed = b.t.mcpNotesActorReview(owner, id);
            assert.equal(typed.book.notizen.some(note => note.id === "phone-note"), scenario === "decision_restore");
            assert.equal(typed.deletionPlan.choices[0].proposal_id, typedProposal.proposal_id);
            assert.throws(() => b.t.mcpNotesActorCommit(owner, id, state.review_revision), error => error.code === "conflict");
            assert.throws(() => b.t.mcpNotesActorCommit(owner, id, decided.review_revision), error => error.code === "unsupported_feature");
            if (scenario === "decision_delete") {
              const changed = await b.t.mcpNotesActorDecide(owner, id, decided.review_revision, [{ ...choice, decision: "restore" }]);
              const restored = b.t.mcpNotesActorReview(owner, id);
              assert.ok(restored.book.notizen.some(note => note.id === "phone-note"), "Changing review choice reused the already deleted preview");
              assert.equal(restored.book.papierkorb.filter(item => item.art === "note" && item.eintrag.id === "phone-note").length, 0);
              assert.notEqual(changed.review_revision, decided.review_revision);
            }
            b.t.mcpNotesActorCancel(owner, id);
          }
        } else if (scenario === "success") b.t.mcpNotesActorCancel(owner, id);
        else if (["commit_stale", "commit_deletions"].includes(scenario)) {
          assert.throws(() => b.t.mcpNotesActorCommit(owner, id, scenario === "commit_stale" ? "f".repeat(64) : state.review_revision));
          assert.equal(b.saves().length, saves); b.t.mcpNotesActorCancel(owner, id);
        } else {
          b.t.mcpNotesActorCommit(owner, id, state.review_revision);
          for (let n = 0; n < 400; n++) {
            await tick();
            if (heldSave) {
              b.t.mcpNotesActorCancel(owner, id); b.t.oeffneTerminBlatt(null, "2026-10-19"); b.input("#tb-titel", "Late commit draft");
              const ack = heldSave; heldSave = null; ack();
            }
            state = b.t.mcpNotesActorStatus(owner, id);
            if ([scenario === "commit_remote" ? "completed" : "committed", "failed"].includes(state.phase) || state.phase === "cancelled" && state.book_persisted) break;
          }
          assert.equal(state.phase, scenario === "commit_remote" ? "completed" : scenario === "commit" ? "committed" : scenario === "commit_cancel_save" ? "cancelled" : "failed", scenario + JSON.stringify(state));
          assert.equal(state.book_persisted, !["commit_save_failed", "commit_checkpoint_failed"].includes(scenario), scenario + JSON.stringify(state));
          assert.equal(coreCommits, ["commit", "commit_remote"].includes(scenario) ? 1 : 0);
          assert.equal(state.reply_queued, ["commit", "commit_remote"].includes(scenario));
          assert.equal(state.phone_persisted, scenario === "commit_remote");
          if (["commit_cancel_save", "commit_late_draft"].includes(scenario)) assert.equal(b.w.document.querySelector("#tb-titel").value, "Late commit draft");
          b.t.mcpNotesActorCancel(owner, id);
        }
      } else if (!closed) assert.equal(state.phase, scenario.startsWith("cancel_") ? "cancelled" : "failed", scenario + JSON.stringify(state));
      for (let n = 0; n < 30 && !cancels; n++) await tick();
      assert.equal(cancels, 1, scenario + ": native context was not retired exactly once");
      if (scenario === "cancel_create") assert.equal(starts, 0, "Cancelled late creation dispatched a snapshot start");
      if (scenario.startsWith("cancel_")) assert.equal(state.native_outcome_unknown, scenario === "cancel_read", "Cancellation falsely promised native recall");
      if (scenario.startsWith("cancel_")) assert.equal(b.w.document.querySelector("#tb-titel").value, "Owned late actor draft");
      if (!scenario.startsWith("commit") || ["commit_stale", "commit_deletions"].includes(scenario)) assert.equal(b.saves().length, saves, "Review preparation saved the actual book");
      if (scenario !== "source_changed" && (!scenario.startsWith("commit") || ["commit_stale", "commit_deletions", "commit_checkpoint_failed"].includes(scenario)))
        assert.equal(JSON.stringify(b.t.daten()), before, scenario + ": private review mutated actual data");
    } finally { b.close(); }
  }
  console.log("NOTES ACTOR REVIEW PASSED: native byte paging/digests, private merge/reply, owner isolation, cancellation/late create/drafts, session close and unchanged book on both frontends");
})().then(() => clearTimeout(watchdog), error => { clearTimeout(watchdog); console.error(error); process.exitCode = 1; });
