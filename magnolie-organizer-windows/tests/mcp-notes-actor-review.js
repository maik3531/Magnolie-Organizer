"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve)), plain = value => JSON.parse(JSON.stringify(value));
const watchdog = setTimeout(() => { console.error("Notes actor review test timed out"); process.exit(1); }, 30000);
(async () => {
  let passed = 0;
  for (const web of harness.exports.roots) for (const recordFormat of [3, 14]) for (const scenario of ["success", "outgoing_pending", "outgoing_bad_dispatch", "producer_bad_hash", "producer_bad_count", "producer_bad_ids", "producer_duplicate_ids", "producer_bad_sequence", "producer_not_staged", "cancel_create", "cancel_read", "source_changed", "session_closed", "bad_digest", "bad_offset", "outside_scope", "draft", "stale", "capacity",
    "malformed_intent_null", "malformed_decisions_null", "malformed_decisions_object", "malformed_decision_null",
    "commit", "commit_remote", "commit_save_failed", "commit_checkpoint_failed", "commit_stale", "commit_deletions", "commit_stage_changed", "commit_cancel_save", "commit_late_draft", "decision_delete", "decision_restore", "decision_cancel",
    "commit_decision_delete", "commit_decision_restore", "commit_decision_receipt_failed", "commit_decision_cancel", "commit_decision_late_draft", "commit_decision_save_failed", "commit_decision_stage_changed", "commit_decision_checkpoint_failed"]) {
    const b = await harness.exports.boot(web, { personalSync: { actor_id: "11111111-1111-4111-8111-111111111111" },
      notizen: [{ id: "phone-note", titel: "Owned", text: "Original", ursprungApp: "notes" }, { id: "desktop-only", titel: "Private", text: "Never send this" }] });
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const owner = "a".repeat(48), target = { peer_id: "22222222-2222-4222-8222-222222222222", fingerprint: "ABCD-1234-5678-90EF" };
      const actorId = "44444444-4444-4444-8444-444444444444", ownerToken = "d".repeat(64);
      const typedCommit = scenario.startsWith("commit_decision_"), typedDelete = scenario === "commit_decision_delete";
      const selection = { notes: new b.w.Set(["phone-note"]), tasks: new b.w.Set() };
      const local = (await b.t.personalSyncSnapshot(["notes"], recordFormat, target.peer_id, { selection, independentRemovals: true })).find(record => record.kind === "note");
      const incoming = plain(local), image = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3]);
      const imageHash = createHash("sha256").update(image).digest("hex");
      incoming.value.text = "Incoming Grüße 🌸"; incoming.value.modified_ms++;
      incoming.value.attachments = [{ attachment_id: "phone-image", name: "phone.png", kind: "image", mime: "image/png", size: image.length, sha256: imageHash }];
      incoming.hash = await b.t.personalSyncHash(incoming.value);
      incoming.modified_ms = incoming.value.modified_ms; incoming.clock.push({ actor_id: target.peer_id, counter: 1 });
      incoming.clock.sort((a, z) => a.actor_id.localeCompare(z.actor_id));
      if (scenario === "outside_scope") incoming.id = "outside-scope";
      const members = { notes: ["phone-note"], tasks: [] };
      const projection = { request: { format: recordFormat, run_id: actorId, trigger: "manual", modules: ["notes"] },
        content_scope: { format: 10, epoch: "55555555-5555-4555-8555-555555555555", revision: 1,
          scope_hash: await b.t.personalSyncHash(members), members }, intents: [],
        batch: { message_id: "66666666-6666-4666-8666-666666666666", commit_token: "77777777-7777-4777-8777-777777777777",
          records: [incoming], records_hash: await b.t.personalSyncHash([incoming]) } };
      if (scenario === "commit_deletions") projection.intents = [{ kind: "personal_sync.deletion_proposals", body: { run_id: actorId } }];
      const typedProposal = { proposal_id: "88888888-8888-4888-8888-888888888888", kind: "note", id: "phone-note", parent_id: "",
        clock: plain(incoming.clock), prior_hash: incoming.hash, deleted_ms: incoming.modified_ms, label: "Native typed deletion" };
      if (scenario.startsWith("decision_") || typedCommit) projection.intents = [{ kind: "personal_sync.deletion_proposals", pending_message_id: "99999999-9999-4999-8999-999999999999",
        commit_token: "c".repeat(64), body: { format: 1, run_id: actorId, proposal_batch_id: "88888888-8888-4888-8888-888888888887", sequence: 0, last: true, proposals: [typedProposal] } }];
      if (scenario.startsWith("malformed_")) projection.intents = scenario === "malformed_intent_null" ? [null] : [{
        kind: "personal_sync.deletion_decision", body: { decisions: scenario === "malformed_decisions_null" ? null :
          scenario === "malformed_decisions_object" ? {} : [null] } }];
      const raw = Buffer.from(JSON.stringify(projection)), viewRevision = createHash("sha256").update(raw).digest("hex");
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
      let held = null, creates = 0, starts = 0, cancels = 0, savedSequence = 0, savedHash = "", plan = null, coreCommits = 0, heldSave = null, holdDecision = false;
      let terminalBegins = 0, terminalAdvances = 0, heldTerminal = null, actorSaves = 0;
      let signalDecisionRead;
      const decisionReadReady = new Promise(resolve => { signalDecisionRead = resolve; });
      const pendingCreates = [];
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      const answer = message => {
        const r = message.request; let response;
        if (r.action === "notes_actor_source") response = { sourceRevision: "b".repeat(64) };
        else if (r.action === "notes_actor_scope") {
          assert.equal(r.sourceRevision, "b".repeat(64)); assert.equal(r.offset, 0); assert.equal(r.limit, 128);
          response = { scopePage: { scope: { scope_epoch: projection.content_scope.epoch, scope_revision: projection.content_scope.revision,
            scope_hash: projection.content_scope.scope_hash }, offset: 0, total: 1, notes_total: 1, tasks_total: 0,
            next_offset: null, members: plain(members), sourceRevision: "b".repeat(64) } };
          response.scopePage.baseline = { record_format: recordFormat, propagate_deletions: true };
        }
        else if (r.action === "notes_actor_create") response = { actorId: scenario === "capacity" ? "44444444-4444-4444-8444-" + pendingCreates.indexOf(message).toString(16).padStart(12, "0") : actorId, ownerToken, bookSource: "" };
        else if (r.action === "notes_actor_produce") {
          assert.ok(savedSequence > 0, "Native producer preceded actual baseline SaveACK");
          response = { actor: { producer_staged: true, book_sha256: savedHash, save_sequence: savedSequence,
            message_count: scenario.startsWith("outgoing_") ? 1 : 0, proposal_count: scenario.startsWith("outgoing_") ? 1 : 0,
            proposal_ids: scenario.startsWith("outgoing_") ? ["88888888-8888-4888-8888-888888888881"] : [] } };
          if (scenario === "producer_bad_hash") response.actor.book_sha256 = "f".repeat(64);
          if (scenario === "producer_bad_count") response.actor.message_count = 2;
          if (scenario === "producer_bad_ids") Object.assign(response.actor, { message_count: 1, proposal_count: 1, proposal_ids: ["not-a-proposal"] });
          if (scenario === "producer_duplicate_ids") Object.assign(response.actor, { message_count: 1, proposal_count: 2, proposal_ids: Array(2).fill("88888888-8888-4888-8888-888888888881") });
          if (scenario === "producer_bad_sequence") response.actor.save_sequence = true;
          if (scenario === "producer_not_staged") response.actor.producer_staged = false;
        }
        else if (r.action === "notes_actor_dispatch_proposals") {
          assert.equal(starts, 1, "Proposal dispatch preceded the native START action");
          response = { actor: { dispatch_started: true, message_count: 1, delivery_confirmed: scenario === "outgoing_bad_dispatch" } };
        }
        else if (r.action === "notes_actor_start") response = { actor: { dispatch_started: true, persisted: false } };
        else if (r.action === "notes_actor_cancel") response = { actor: { phase: "cancelled" } };
        else if (r.action === "notes_actor_status") response = { actor: { phase: "receiving", packets: 3,
          phone_persisted: scenario === "commit_remote" && coreCommits === 1, book_persisted: coreCommits === 1,
          phone_data_persisted: typedCommit && coreCommits === 1,
          reply_queued: coreCommits === 1, completion_report_queued: (scenario === "commit_remote" || typedCommit) && coreCommits === 1 } };
        else if (r.action === "notes_actor_begin_completion" || r.action === "notes_actor_advance_completion") {
          assert.equal(coreCommits, 1, "Terminal controller preceded native core commit");
          assert.equal(savedHash, plan.hash);
          if (r.action === "notes_actor_begin_completion") { terminalBegins++; assert.equal(r.claimToken, "e".repeat(64)); }
          else terminalAdvances++;
          const complete = r.action === "notes_actor_advance_completion", badReceipt = scenario === "commit_decision_receipt_failed";
          response = { actor: { phase: complete && !badReceipt ? "completed" : "completion", packets: 4,
            phone_data_persisted: true, phone_persisted: complete, book_persisted: true, reply_queued: true, completion_report_queued: true,
            deletion_completion: { expected: 1, received: complete && !badReceipt ? 1 : 0, saved: complete && !badReceipt ? 1 : 0, rejected: 0 } } };
          if (complete && scenario === "commit_decision_late_draft") {
            b.t.oeffneTerminBlatt(null, "2026-10-19"); b.input("#tb-titel", "Late terminal draft");
          }
        }
        else if (r.action === "notes_actor_prepare_commit") {
          assert.ok(savedSequence > 0, "Native plan preceded actual baseline SaveACK");
          if (typedCommit) {
            assert.deepEqual(plain(r.deletionPlan.intents), projection.intents.map(intent => ({ kind: intent.kind, message_id: intent.pending_message_id, commit_token: intent.commit_token })));
            assert.equal(r.deletionPlan.choices[0].decision, typedDelete ? "delete" : "restore");
            assert.deepEqual(plain(r.deletionPlan.choices[0].expected_clock), typedProposal.clock);
          }
          plan = { sequence: savedSequence, hash: r.bookSha256 };
          response = { actor: { claim_token: "e".repeat(64), after_sha256: plan.hash, view_revision: viewRevision, book_persisted: false } };
        } else if (r.action === "notes_actor_commit") {
          assert.ok(savedSequence > plan.sequence, "Core commit preceded a new actual native SaveACK");
          assert.equal(savedHash, plan.hash); assert.equal(r.claimToken, "e".repeat(64));
          if (["commit_stage_changed", "commit_decision_stage_changed"].includes(scenario)) { b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: false, code: "source_changed" }); return; }
          coreCommits++; response = { actor: { book_persisted: true, core_committed: true, phone_persisted: false, book_sha256: savedHash, save_sequence: savedSequence } };
        } else if (r.action === "notes_actor_reply") {
          assert.equal(coreCommits, 1, "Reply queued before the actual native core commit");
          assert.equal(r.claimToken, "e".repeat(64));
          assert.ok(r.batches.every(batch => batch.format === recordFormat), "Actor reply changed its negotiated format");
          if (recordFormat === 14) assert.ok(r.batches.flatMap(batch => batch.records).filter(record => record.kind === "note").every(record => record.value.origin_app === "notes"));
          if (typedDelete) { assert.ok(!r.batches.flatMap(batch => batch.records).some(record => record.id === "phone-note")); assert.equal(r.sources.length, 0); }
          else assert.ok(r.batches.flatMap(batch => batch.records).some(record => record.kind === "note" && record.value.text === "Incoming Grüße 🌸"));
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
          const isActor = plan !== null;
          if (isActor) actorSaves++;
          const ok = !(["commit_save_failed", "commit_decision_save_failed"].includes(scenario) && isActor);
          if (ok) { savedSequence++; savedHash = createHash("sha256").update(message.text).digest("hex"); }
          const ack = () => {
            b.w.App.gespeichert({ id: message.id, ok, standSha256: savedHash });
            if (scenario === "commit_late_draft" && isActor) { b.t.oeffneTerminBlatt(null, "2026-10-19"); b.input("#tb-titel", "Late commit draft"); }
          };
          if (scenario === "commit_cancel_save" && isActor) heldSave = ack;
          else queueMicrotask(ack);
          return;
        }
        if (message.cmd === "mutations_snapshot") { queueMicrotask(() => b.w.App.mutationsSnapshot({ token: message.token, ok: !["commit_checkpoint_failed", "commit_decision_checkpoint_failed"].includes(scenario) })); return; }
        if (message.cmd !== "telefon_mcp") return;
        const action = message.request.action;
        if (action === "notes_actor_create") creates++;
        if (action === "notes_actor_start") starts++;
        if (action === "notes_actor_cancel") cancels++;
        if (scenario === "commit_decision_cancel" && action === "notes_actor_advance_completion") { heldTerminal = message; return; }
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
        // Scope collection now precedes creation. Reach all held create calls
        // before cancellation to keep testing late native-owner cleanup here.
        for (let n = 0; n < 50 && pendingCreates.length < 4; n++) await tick();
        assert.equal(pendingCreates.length, 4);
        for (const result of results.filter(result => result.status === "fulfilled")) b.t.mcpNotesActorCancel(owner, result.value.operation_id);
        pendingCreates.forEach(answer);
        for (let n = 0; n < 50 && cancels < 4; n++) await tick();
        assert.equal(cancels, 4); assert.equal(starts, 0);
        assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves + 4); continue;
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
      if (scenario === "success" || scenario === "outgoing_pending" || scenario.startsWith("commit") || scenario.startsWith("decision_")) {
        assert.equal(state.phase, "review", JSON.stringify(state)); assert.equal(state.summary.attachments, 1); assert.equal(state.summary.conflicts, 0);
        const review = b.t.mcpNotesActorReview(owner, id);
        assert.equal(review.book.notizen.find(note => note.id === "phone-note").text, "Incoming Grüße 🌸");
        assert.equal(review.book.notizen.find(note => note.id === "desktop-only").text, "Never send this");
        const reply = review.batches.flatMap(batch => batch.records);
        assert.equal(reply.find(record => record.kind === "note").value.text, "Incoming Grüße 🌸");
        assert.ok(!reply.some(record => record.id === "desktop-only")); assert.equal(review.sources.length, 1);
        assert.ok(!JSON.stringify(state).includes(ownerToken));
        if (scenario === "outgoing_pending") {
          assert.equal(state.summary.outgoing_proposals, 1);
          assert.throws(() => b.t.mcpNotesActorCommit(owner, id, state.review_revision), error => error.code === "unsupported_feature");
          assert.equal(coreCommits, 0); assert.equal(actorSaves, 0);
          b.t.mcpNotesActorCancel(owner, id);
        } else if (typedCommit) {
          const choice = { proposal_id: typedProposal.proposal_id, decision: typedDelete ? "delete" : "restore", expected_clock: plain(typedProposal.clock), allow_conflict: true };
          const decided = await b.t.mcpNotesActorDecide(owner, id, state.review_revision, [choice]);
          b.t.mcpNotesActorCommit(owner, id, decided.review_revision);
          for (let n = 0; n < 600; n++) {
            await tick();
            if (heldTerminal) {
              b.t.mcpNotesActorCancel(owner, id); b.t.oeffneTerminBlatt(null, "2026-10-19"); b.input("#tb-titel", "Late terminal draft");
              const message = heldTerminal; heldTerminal = null; answer(message);
            }
            state = b.t.mcpNotesActorStatus(owner, id);
            if (["completed", "failed", "cancelled"].includes(state.phase)) break;
          }
          const positive = ["commit_decision_delete", "commit_decision_restore"].includes(scenario);
          assert.equal(state.phase, positive ? "completed" : scenario === "commit_decision_cancel" ? "cancelled" : "failed", scenario + JSON.stringify(state));
          const persisted = !["commit_decision_save_failed", "commit_decision_checkpoint_failed"].includes(scenario);
          const core = persisted && scenario !== "commit_decision_stage_changed";
          assert.equal(state.book_persisted, persisted); assert.equal(coreCommits, core ? 1 : 0); assert.equal(state.reply_queued, core);
          assert.equal(state.phone_persisted, positive); assert.equal(actorSaves, scenario === "commit_decision_checkpoint_failed" ? 0 : 1);
          assert.equal(terminalBegins, core ? 1 : 0); assert.equal(terminalAdvances, core ? 1 : 0);
          if (persisted) {
            assert.equal(b.t.daten().notizen.some(note => note.id === "phone-note"), !typedDelete);
            assert.equal(b.t.daten().notizen.find(note => note.id === "desktop-only").text, "Never send this");
            assert.equal(b.t.daten().papierkorb.filter(item => item.art === "note" && item.eintrag.id === "phone-note").length, typedDelete ? 1 : 0);
          }
          if (["commit_decision_cancel", "commit_decision_late_draft"].includes(scenario)) assert.equal(b.w.document.querySelector("#tb-titel").value, "Late terminal draft");
          b.t.mcpNotesActorCancel(owner, id);
        } else if (scenario.startsWith("decision_")) {
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
            assert.equal(typed.deletionPlan.intents.length, 1, "Private preview lost its exact native adoption plan");
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
          assert.equal(b.saves().length, saves + 1); b.t.mcpNotesActorCancel(owner, id);
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
      if (scenario.startsWith("producer_")) assert.equal(starts, 0, "Unverified native producer receipt dispatched START");
      if (scenario.startsWith("cancel_")) assert.equal(state.native_outcome_unknown, scenario === "cancel_read", "Cancellation falsely promised native recall");
      if (scenario.startsWith("cancel_")) assert.equal(b.w.document.querySelector("#tb-titel").value, "Owned late actor draft");
           if (!scenario.startsWith("commit") || ["commit_stale", "commit_deletions"].includes(scenario)) assert.equal(b.saves().length, saves + 1, "Review wrote beyond its explicit native baseline");
      if (scenario !== "source_changed" && (!scenario.startsWith("commit") || ["commit_stale", "commit_deletions", "commit_checkpoint_failed"].includes(scenario)))
        assert.equal(JSON.stringify(b.t.daten()), before, scenario + ": private review mutated actual data");
    } finally { b.close(); passed++; }
  }
  console.log("NOTES ACTOR REVIEW PASSED: " + passed + " cases; native producer/dispatch receipts, scope/byte paging, private merge/reply, owner isolation, cancellation/drafts and terminal fences on both frontends");
})().then(() => clearTimeout(watchdog), error => { clearTimeout(watchdog); console.error(error); process.exitCode = 1; });
