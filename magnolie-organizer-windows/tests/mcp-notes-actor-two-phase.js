"use strict";
// Real frontend/checkpoint/SaveACK handlers, synthetic private native RPCs.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve)), plain = value => JSON.parse(JSON.stringify(value));
const digest = text => createHash("sha256").update(text).digest("hex");
const originalImage = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3]), originalImageUrl = "data:image/png;base64," + originalImage.toString("base64");
let activeCase = "", activeStage = "";
const watchdog = setTimeout(() => { console.error("Two-phase Notes test timed out: " + activeCase + " / " + activeStage); process.exit(1); }, 90000);
(async () => {
  let passed = 0;
  for (const web of harness.exports.roots) for (const format of [3, 14]) for (const kind of ["note", "task"]) for (const choice of ["delete", "restore"])
    for (const scenario of ["success", "confirm_retry", "ack_retry", "bad_digest", "foreign_target", "wrong_clock", "bad_frames", "bad_receipt", "bad_scope", "mixed", "checkpoint", "save_failed", "draft",
      "premature_receipt", "bad_claim", "bad_confirm", "bad_completion", "cancel_review", "cancel_save", "late_draft",
      "mixed_success", "mixed_initial_restore", "mixed_confirm_retry", "mixed_bad_fixed_target", "mixed_bad_fixed_clock", "mixed_bad_fixed_choice", "mixed_bad_fixed_frames",
      "mixed_scope_omits_fixed", "mixed_missing_fixed", "mixed_bad_completion_count",
      "original_restore", "original_restore_no_record", "original_restore_bad_hash", "original_restore_newer_clock", "original_restore_disabled_trash", "original_restore_attachment",
      "original_restore_missing_parent", "original_restore_missing_notebook"]) {
      if (process.env.MAGNOLIE_ACTOR_CASE && scenario !== process.env.MAGNOLIE_ACTOR_CASE) continue;
      activeCase = [web, format, kind, choice, scenario].join(" / "); activeStage = "boot";
      const mixed = scenario.startsWith("mixed_"), initialDelete = scenario !== "mixed_initial_restore";
      const originalRestore = scenario.startsWith("original_restore");
      if (scenario === "original_restore_attachment" && kind !== "note") continue;
      if (scenario === "original_restore_missing_parent" && kind !== "task" || scenario === "original_restore_missing_notebook" && kind !== "note") continue;
      const b = await harness.exports.boot(web, { personalSync: { actor_id: "11111111-1111-4111-8111-111111111111" },
        notizen: [{ id: "local-note", titel: "Synthetic original", text: "Preserve Grüße 🌸", ursprungApp: "notes",
          ...(scenario === "original_restore_missing_notebook" ? { notizbuchId: "original-book" } : {}),
          ...(scenario === "original_restore_attachment" ? { anhaenge: [{ id: "original-image", name: "original.png", art: "image", daten: originalImageUrl }] } : {}) }, { id: "private-note", titel: "Private", text: "Never mutate" }],
        ...(scenario === "original_restore_missing_notebook" ? { notizbuecher: [{ id: "original-book", name: "Original native notebook", gruppeId: "standard" }] } : {}),
        aufgaben: [{ id: "local-task", titel: "Synthetic task", faellig: "2026-11-01", erledigt: false,
          ...(scenario === "original_restore_missing_parent" ? { uid: "original-child-uid", elternUid: "original-parent-uid" } : {}) },
          ...(scenario === "original_restore_missing_parent" ? [{ id: "original-parent-task", uid: "original-parent-uid", titel: "Original parent" }] : [])] });
      try {
        if (b.saves().length) b.ack(); await tick();
        b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
        const peer = "22222222-2222-4222-8222-222222222222", actor = "44444444-4444-4444-8444-444444444444", frame = "88888888-8888-4888-8888-888888888888";
        const localId = kind === "note" ? "local-note" : "local-task", list = kind === "note" ? "notizen" : "aufgaben";
        const selection = { notes: new b.w.Set(kind === "note" || mixed ? ["local-note"] : []), tasks: new b.w.Set(kind === "task" || mixed ? ["local-task"] : []) }, data = b.t.daten();
        const initialRecords = await b.t.personalSyncSnapshot(["notes", "tasks"], format, peer, { selection, independentRemovals: true });
        const original = initialRecords.find(value => value.kind === kind), fixedRecord = mixed ? initialRecords.find(value => value.kind !== kind && ["note", "task"].includes(value.kind)) : null;
        const fixedKind = kind === "note" ? "task" : "note", fixedList = fixedKind === "note" ? "notizen" : "aufgaben";
        const fixedProposal = fixedRecord ? { proposal_id: "99999999-9999-4999-8999-999999999991", kind: fixedKind, id: fixedRecord.id, parent_id: "",
          prior_hash: fixedRecord.hash, clock: plain(fixedRecord.clock), deleted_ms: 2, label: "Original fixed typed target" } : null;
        const fixedFrameId = "99999999-9999-4999-8999-999999999992";
        data.personalSync.entities[kind + "\0" + original.id].acknowledged_by_peer = true;
        b.t.inDenPapierkorb(kind, data[list].find(value => value.id === localId), "Synthetic original");
        data[list] = data[list].filter(value => value.id !== localId);
        await b.t.personalSyncSnapshot(["notes", "tasks"], format, peer, { selection, independentRemovals: true, propagateSelectedDeletions: true });
        const meta = plain(data.personalSync.entities[kind + "\0" + original.id]); assert.ok(meta.proposal_id);
        if (originalRestore) {
          data.papierkorb = data.papierkorb.filter(value => !(value.art === kind && value.eintrag.id === localId));
          if (scenario === "original_restore_disabled_trash") data.einstellungen.papierkorb.an = false;
          if (scenario === "original_restore_missing_parent") data.aufgaben = data.aufgaben.filter(value => value.id !== "original-parent-task");
          if (scenario === "original_restore_missing_notebook") data.notizbuecher = data.notizbuecher.filter(value => value.id !== "original-book");
        }
        const members = { notes: initialRecords.filter(value => value.kind === "note").map(value => value.id), tasks: initialRecords.filter(value => value.kind === "task").map(value => value.id) }, scope = { format: 10, epoch: "55555555-5555-4555-8555-555555555555", revision: 1, members, scope_hash: await b.t.personalSyncHash(members) };
        const projection = { request: { format, run_id: actor, trigger: "manual", modules: ["notes", "tasks"] }, content_scope: scope,
          batch: { records: [], records_hash: await b.t.personalSyncHash([]), commit_token: "77777777-7777-4777-8777-777777777777" },
          intents: mixed ? [{ kind: "personal_sync.deletion_proposals", pending_message_id: fixedFrameId, commit_token: "f".repeat(64),
            body: { format: 1, run_id: actor, proposal_batch_id: actor, sequence: 0, last: true, proposals: [fixedProposal] } }] : scenario === "mixed" ? [{ kind: "personal_sync.deletion_proposals", body: { run_id: actor } }] : [] };
        if (originalRestore && scenario !== "original_restore_no_record") {
          const source = plain(original);
          if (scenario === "original_restore_bad_hash") { source.value.title += " CHANGED"; source.hash = await b.t.personalSyncHash(source.value); }
          if (scenario === "original_restore_newer_clock") source.clock.push({ actor_id: peer, counter: 99 });
          projection.batch.records = [source]; projection.batch.records_hash = await b.t.personalSyncHash([source]);
        }
        const raw = Buffer.from(JSON.stringify(projection)), revision = digest(raw), owner = "a".repeat(48), initialSaves = b.saves().length;
        let seq = 0, savedHash = "", ordinary, lateClaim, lateRaw, lateHash, core = 0, checkpoints = 0, confirms = 0, advances = 0, prepares = 0;
        let latePhase = false, failed = false, lateReady = false;
        let heldSave, operation;
        const post = b.w.webkit.messageHandlers.regression.postMessage;
        const answer = message => {
          const r = message.request; activeStage = r.action; let value;
          if (r.action === "notes_actor_source") value = { sourceRevision: "b".repeat(64) };
          else if (r.action === "notes_actor_scope") value = { scopePage: { scope: { scope_epoch: scope.epoch, scope_revision: 1, scope_hash: scope.scope_hash },
            offset: 0, total: members.notes.length + members.tasks.length, notes_total: members.notes.length, tasks_total: members.tasks.length, next_offset: null, members, sourceRevision: "b".repeat(64), baseline: { record_format: format, propagate_deletions: true } } };
          else if (r.action === "notes_actor_create") value = { actorId: actor, ownerToken: "d".repeat(64), bookSource: "" };
          else if (r.action === "notes_actor_produce") value = { actor: { producer_staged: true, late_decision_phase: 1, book_sha256: savedHash, save_sequence: seq,
            ...(mixed ? { mixed_decision_phase: 1 } : {}),
            proposal_count: 1, message_count: 1, proposal_ids: [meta.proposal_id] } };
          else if (r.action === "notes_actor_dispatch_proposals") value = { actor: { dispatch_started: true, message_count: 1, delivery_confirmed: false } };
          else if (r.action === "notes_actor_start" || r.action === "notes_actor_cancel") value = { actor: {} };
          else if (r.action === "notes_actor_read") {
            const bytes = r.attachmentSha256 ? originalImage : raw, end = Math.min(bytes.length, r.offset + r.limit);
            value = { actor: { batch_ready: true, revision, total_bytes: bytes.length, offset: r.offset, next_offset: end < bytes.length ? end : null, data_base64: bytes.subarray(r.offset, end).toString("base64"),
              ...(r.attachmentSha256 ? { attachment_sha256: r.attachmentSha256, mime: "image/png" } : {}) } };
          } else if (r.action === "notes_actor_prepare_commit") {
            assert.equal(seq, 1, "Ordinary checkpoint repeated the unchanged baseline save");
            if (mixed) assert.equal(r.deletionPlan.choices[0].proposal_id, fixedProposal.proposal_id);
            ordinary = { hash: r.bookSha256 }; value = { actor: { claim_token: "e".repeat(64), after_sha256: ordinary.hash, view_revision: revision, book_persisted: false } };
          } else if (r.action === "notes_actor_commit") {
            assert.equal(seq, 2); assert.equal(savedHash, ordinary.hash); core++;
            ordinary.sequence = seq;
            value = { actor: { core_committed: true, book_persisted: true, book_sha256: savedHash, save_sequence: seq, phone_persisted: false } };
          } else if (r.action === "notes_actor_reply") {
            assert.equal(core, 1); assert.ok(!r.batches.flatMap(batch => batch.records).some(record => record.id === original.id));
            value = { actor: { reply_queued: true, message_count: r.batches.length, book_persisted: true, phone_persisted: false, delivery_confirmed: false } };
          } else if (r.action === "notes_actor_status") value = { actor: { phase: "decision_review", packets: 4, phone_data_persisted: true, phone_persisted: scenario === "premature_receipt",
            book_persisted: true, reply_queued: true, completion_report_queued: true } };
          else if (r.action === "notes_actor_late_review") {
            assert.equal(seq, 2); assert.equal(core, 1); latePhase = true;
            if (!lateReady) { lateReady = true; value = { actor: { review_ready: false, expected_proposals: 1 } }; }
            else {
              if (!lateRaw) {
                const afterMembers = plain(members);
                if (choice === "delete") afterMembers[kind === "note" ? "notes" : "tasks"] = [];
                if (mixed && initialDelete && scenario !== "mixed_scope_omits_fixed") afterMembers[fixedKind === "note" ? "notes" : "tasks"] = [];
                const afterScope = JSON.stringify(afterMembers) !== JSON.stringify(members) ? { ...scope, epoch: actor, revision: 2, members: afterMembers, scope_hash: digest(JSON.stringify(afterMembers)) } : scope;
                const late = { targets: [{ proposal_id: meta.proposal_id, kind, id: original.id, parent_id: "", clock: plain(meta.clock), prior_hash: meta.prior_hash }],
                  decisions: [{ proposal_id: meta.proposal_id, decision: choice, expected_clock: plain(meta.clock) }], decision_message_ids: [frame], content_scope: afterScope,
                  data_saved_book: { book_source: "c".repeat(64), sequence: ordinary.sequence, sha256: ordinary.hash }, review_revision: "9".repeat(64) };
                if (mixed) {
                  late.fixed_targets = [Object.fromEntries(["proposal_id", "kind", "id", "parent_id", "prior_hash", "clock"].map(key => [key, fixedProposal[key]]))];
                  late.fixed_decisions = [{ proposal_id: fixedProposal.proposal_id, decision: initialDelete ? "delete" : "restore", expected_clock: plain(fixedProposal.clock) }];
                  late.fixed_decision_message_ids = [fixedFrameId];
                  if (scenario === "mixed_bad_fixed_target") late.fixed_targets[0].prior_hash = "f".repeat(64);
                  if (scenario === "mixed_bad_fixed_clock") late.fixed_decisions[0].expected_clock[0].counter++;
                  if (scenario === "mixed_bad_fixed_choice") late.fixed_decisions[0].decision = "restore";
                  if (scenario === "mixed_bad_fixed_frames") late.fixed_decision_message_ids = [frame];
                  if (scenario === "mixed_missing_fixed") delete late.fixed_targets;
                }
                if (scenario === "foreign_target") late.targets[0].id = "private-note";
                if (scenario === "wrong_clock") late.decisions[0].expected_clock[0].counter++;
                if (scenario === "bad_frames") late.decision_message_ids.push(frame);
                if (scenario === "bad_receipt") late.data_saved_book.sequence++;
                if (scenario === "bad_scope") late.content_scope = scope;
                lateRaw = Buffer.from(JSON.stringify(late)); lateHash = digest(lateRaw);
              }
              const end = Math.min(lateRaw.length, r.offset + 113);
              value = { actor: { review_ready: true, expected_proposals: 1, revision: scenario === "bad_digest" ? "f".repeat(64) : lateHash,
                review_revision: "9".repeat(64), total_bytes: lateRaw.length, offset: r.offset, next_offset: end < lateRaw.length ? end : null,
                data_base64: lateRaw.subarray(r.offset, end).toString("base64"), deletion_book_persisted: false, phone_persisted: false } };
            }
          } else if (r.action === "notes_actor_prepare_late_save") {
            prepares++; assert.equal(seq, 2, "Late checkpoint repeated an unchanged ordinary save");
            lateClaim = { claim_token: "8".repeat(64), revision: r.reviewRevision, after_sha256: r.bookSha256, before_sequence: ordinary.sequence,
              book_source: "c".repeat(64), book_persisted: false, deletion_book_persisted: false, phone_persisted: false };
            if (scenario === "bad_claim") lateClaim.before_sequence++;
            value = { actor: lateClaim };
          } else if (r.action === "notes_actor_confirm_late_save") {
            confirms++; assert.equal(seq, 3); assert.equal(savedHash, lateClaim.after_sha256); assert.equal(r.claimToken, lateClaim.claim_token);
            if (["confirm_retry", "mixed_confirm_retry"].includes(scenario) && !failed) { failed = true; b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: false, code: "native_operation_failed" }); return; }
            value = { actor: { deletion_book_persisted: true, completion_started: true, book_sha256: savedHash, save_sequence: seq, phone_persisted: false } };
            if (scenario === "bad_confirm" && !failed) { failed = true; value.actor.book_sha256 = "f".repeat(64); }
          } else if (r.action === "notes_actor_advance_completion") {
            advances++;
            if (scenario === "ack_retry" && !failed) { failed = true; b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: false, code: "native_operation_failed" }); return; }
            value = { actor: { phase: "completed", book_persisted: true, deletion_book_persisted: true, phone_data_persisted: true, phone_persisted: true,
              reply_queued: true, completion_report_queued: true, deletion_completion: { expected: mixed ? 2 : 1, received: mixed ? 2 : 1, saved: mixed ? 2 : 1, rejected: 0 } } };
            if (scenario === "bad_completion" && !failed) { failed = true; value.actor.deletion_completion.expected = 2; }
            if (scenario === "mixed_bad_completion_count" && !failed) { failed = true; value.actor.deletion_completion.expected = 1; }
          } else throw Error("Unexpected action " + r.action);
          b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: true, ...value });
        };
        b.w.webkit.messageHandlers.regression.postMessage = text => {
          post(text); const message = JSON.parse(text);
          if (message.cmd === "speichern") {
            const ok = !(scenario === "save_failed" && latePhase);
            if (ok) { seq++; savedHash = digest(message.text); }
            const ack = () => {
              b.w.App.gespeichert({ id: message.id, ok, standSha256: savedHash });
              if (scenario === "late_draft" && latePhase) { b.t.oeffneTerminBlatt(null, "2026-11-01"); b.input("#tb-titel", "Draft after actual late save"); }
            };
            if (scenario === "cancel_save" && latePhase) { heldSave = ack; b.t.mcpNotesActorCancel(owner, operation); }
            else queueMicrotask(ack);
          } else if (message.cmd === "mutations_snapshot") {
            checkpoints++; queueMicrotask(() => b.w.App.mutationsSnapshot({ token: message.token, ok: !(scenario === "checkpoint" && latePhase) }));
          } else if (message.cmd === "telefon_mcp") queueMicrotask(() => answer(message));
        };
        const start = await b.t.mcpNotesActorStart(owner, { peer_id: peer, fingerprint: "ABCD-1234-5678-90EF", expected_book_revision: await b.t.personalSyncHash(JSON.stringify(data)) }, new b.w.AbortController().signal);
        operation = start.operation_id;
        const status = () => b.t.mcpNotesActorStatus(owner, start.operation_id);
        async function wait(phases) {
          for (let i = 0; i < 400; i++) {
            await tick(); for (const timer of b.timers.filter(timer => timer.delay === 250 && !timer.cancelled)) { timer.cancelled = true; timer.fn(); }
            const state = status(); if (phases.includes(state.phase)) return state;
          }
          throw Error("Stalled " + scenario + ": " + JSON.stringify(status()));
        }
        await wait(["review"]);
        if (mixed) {
          activeStage = "typed mixed decision";
          await b.t.mcpNotesActorDecide(owner, operation, status().review_revision, [{ proposal_id: fixedProposal.proposal_id, decision: initialDelete ? "delete" : "restore",
            expected_clock: plain(fixedProposal.clock), allow_conflict: true }]);
          activeStage = "typed mixed decision ready";
        }
        if (scenario === "mixed") {
          assert.throws(() => b.t.mcpNotesActorCommit(owner, start.operation_id, status().review_revision), error => error.code === "unsupported_feature");
          assert.equal(seq, 1); assert.equal(checkpoints, 0); b.t.mcpNotesActorCancel(owner, start.operation_id); passed++; continue;
        }
        b.t.mcpNotesActorCommit(owner, start.operation_id, status().review_revision);
        const state = await wait(["late_review", "failed"]);
        const malformed = ["bad_digest", "foreign_target", "wrong_clock", "bad_frames", "bad_receipt", "premature_receipt", "mixed_bad_fixed_target", "mixed_bad_fixed_clock", "mixed_bad_fixed_choice", "mixed_bad_fixed_frames", "mixed_scope_omits_fixed", "mixed_missing_fixed"].includes(scenario) || scenario === "bad_scope" && choice === "delete" ||
          choice === "restore" && ["original_restore_no_record", "original_restore_bad_hash", "original_restore_newer_clock", "original_restore_missing_parent", "original_restore_missing_notebook"].includes(scenario);
        if (malformed) { assert.equal(state.phase, "failed"); assert.equal(seq, 2); passed++; continue; }
        assert.equal(state.phase, "late_review", scenario + ": " + JSON.stringify(state)); assert.equal(state.book_persisted, true); assert.equal(state.deletion_book_persisted, false); assert.equal(state.phone_persisted, false);
        assert.ok(!b.t.daten()[list].some(value => value.id === localId), "Late review mutated active book before explicit commit");
        const fixedAfterOrdinary = mixed ? JSON.stringify(b.t.daten()[fixedList]) : null;
        if (mixed) assert.equal(b.t.daten()[fixedList].some(value => value.id === (fixedKind === "note" ? "local-note" : "local-task")), !initialDelete);
        if (scenario === "draft") {
          b.t.oeffneTerminBlatt(null, "2026-11-01"); b.input("#tb-titel", "Owned late draft");
          assert.throws(() => b.t.mcpNotesActorCommit(owner, start.operation_id, state.review_revision));
          assert.equal(seq, 2); assert.equal(prepares, 0); passed++; continue;
        }
        if (scenario === "cancel_review") {
          b.t.mcpNotesActorCancel(owner, operation); assert.equal(status().phase, "cancelled"); assert.equal(seq, 2); assert.equal(prepares, 0); passed++; continue;
        }
        assert.throws(() => b.t.mcpNotesActorCommit(owner, start.operation_id, "0".repeat(64)), error => error.code === "conflict");
        b.t.mcpNotesActorCommit(owner, start.operation_id, state.review_revision);
        let done = await wait(["completed", "late_metadata_pending", "failed", "cancelled"]);
        if (scenario === "cancel_save") {
          assert.equal(done.phase, "cancelled"); assert.ok(heldSave); heldSave(); await tick();
          assert.equal(confirms, 0); assert.equal(advances, 0); assert.equal(status().phase, "cancelled"); passed++; continue;
        }
        if (scenario === "late_draft") {
          assert.equal(done.phase, "failed"); assert.equal(seq, 3); assert.equal(confirms, 0);
          assert.equal(b.w.document.querySelector("#tb-titel").value, "Draft after actual late save"); passed++; continue;
        }
        if (["checkpoint", "save_failed", "bad_claim"].includes(scenario)) {
          assert.equal(done.phase, "failed"); assert.equal(done.deletion_book_persisted, false); assert.equal(confirms, 0); passed++; continue;
        }
        if (["confirm_retry", "ack_retry", "bad_confirm", "bad_completion", "mixed_confirm_retry", "mixed_bad_completion_count"].includes(scenario)) {
          assert.equal(done.phase, "late_metadata_pending"); assert.equal(done.deletion_book_persisted, true);
          b.t.mcpNotesActorCommit(owner, start.operation_id, done.review_revision); done = await wait(["completed", "failed"]);
        }
        assert.equal(done.phase, "completed"); assert.equal(done.phone_persisted, true); assert.equal(seq, 3); assert.equal(prepares, 1); assert.equal(checkpoints, 2); assert.equal(core, 1);
        assert.equal(b.saves().length, initialSaves + 3, "Not exactly baseline + ordinary + separate late save");
        assert.equal(b.t.daten()[list].some(value => value.id === localId), choice === "restore");
        if (originalRestore && choice === "restore") {
          const restored = b.t.daten()[list].find(value => value.id === localId);
          assert.equal(restored.titel, original.value.title);
          if (original.value.origin_app) assert.equal(restored.ursprungApp, original.value.origin_app);
          if (kind === "task") {
            assert.equal(restored.faellig, original.value.due); assert.equal(restored.erledigt, original.value.completed);
            if (original.value.uid) assert.equal(restored.uid, original.value.uid);
          }
          assert.equal(b.t.daten().papierkorb.filter(value => value.art === kind && value.eintrag.id === localId).length, 0);
          if (scenario === "original_restore_attachment") assert.equal(restored.anhaenge[0].daten, originalImageUrl);
          if (scenario === "original_restore_disabled_trash") assert.equal(b.t.daten().einstellungen.papierkorb.an, false);
        }
        if (mixed) assert.equal(JSON.stringify(b.t.daten()[fixedList]), fixedAfterOrdinary, "Late save repeated an initial ordinary document mutation");
        assert.equal(b.t.daten().notizen.find(value => value.id === "private-note").text, "Never mutate");
        passed++;
      } finally { b.close(); }
    }
  console.log("Notes two-phase frontend: " + passed + " cases passed");
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
