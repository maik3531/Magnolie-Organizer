"use strict";
// Actual actor/shared candidate/save handlers; synthetic native RPCs, not phone E2E.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve)), plain = value => JSON.parse(JSON.stringify(value)), hash = value => createHash("sha256").update(value).digest("hex");
let active = "";
const watchdog = setTimeout(() => { console.error("Original attachment probe timed out: " + active); process.exit(1); }, 60000);
(async () => {
  let passed = 0;
  for (const web of harness.exports.roots) for (const format of [3, 14]) for (const choice of ["delete", "restore"])
    for (const fault of ["none", "no-original", "descriptor", "clock", "missing-parent", "confirm-retry", "blob", "target-clock", "parent-restore", "parent-reversed", "parent-stale-trash", "parent-no-source", "parent-omitted-child"]) {
      if (process.env.MAGNOLIE_ATTACHMENT_CASE && fault !== process.env.MAGNOLIE_ATTACHMENT_CASE) continue;
      const parentRestore = fault.startsWith("parent-");
      active = [web, format, choice, fault].join(" / ");
      const removedBytes = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 1]), keepBytes = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 2]);
      const url = value => "data:image/png;base64," + value.toString("base64");
      const b = await harness.exports.boot(web, { personalSync: { actor_id: "11111111-1111-4111-8111-111111111111" }, notizen: [
        { id: "parent-note", titel: "Original parent", text: "Original text", ursprungApp: "notes", anhaenge: [
          { id: "removed-image", name: "removed.png", art: "image", daten: url(removedBytes) }, { id: "keep-image", name: "keep.png", art: "image", daten: url(keepBytes) }] },
        { id: "private-note", titel: "Private", text: "Never change" }] });
      try {
        if (b.saves().length) b.ack(); await tick(); b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
        const data = b.t.daten(), owner = "a".repeat(48), peer = "22222222-2222-4222-8222-222222222222", actor = "44444444-4444-4444-8444-444444444444";
        const selection = { notes: new b.w.Set(["parent-note"]), tasks: new b.w.Set() };
        const original = plain((await b.t.personalSyncSnapshot(["notes"], format, peer, { selection, independentRemovals: true })).find(value => value.kind === "note"));
        const descriptor = original.value.attachments.find(value => value.name === "removed.png"), key = "attachment\0" + original.id + "\0" + descriptor.attachment_id;
        data.personalSync.entities[key].acknowledged_by_peer = true;
        if (parentRestore) data.personalSync.entities["note\0" + original.id].acknowledged_by_peer = true;
        const parent = data.notizen.find(value => value.id === "parent-note");
        parent.anhaenge = parent.anhaenge.filter(value => value.id !== "removed-image"); parent.text = "Local newer text must survive";
        let historicalPiece = null;
        await b.t.personalSyncSnapshot(["notes"], format, peer, { selection, independentRemovals: true, propagateSelectedDeletions: true });
        if (parentRestore) {
          data.personalSync.entities["note\0" + original.id].acknowledged_by_peer = true;
          b.t.inDenPapierkorb("note", parent, "Original parent restore");
          if (["parent-stale-trash", "parent-omitted-child"].includes(fault)) data.papierkorb.find(value => value.art === "note" && value.eintrag.id === "parent-note").eintrag.anhaenge.push({ id: "removed-image", name: "removed.png", art: "image", daten: url(removedBytes) });
          if (fault === "parent-stale-trash") {
            historicalPiece = plain(data.papierkorb.find(value => value.art === "note" && value.eintrag.id === "parent-note"));
            historicalPiece.id = "historical-trash-piece"; historicalPiece.name = "Unrelated older trash snapshot";
            data.papierkorb.unshift(plain(historicalPiece));
          }
          data.notizen = data.notizen.filter(value => value.id !== "parent-note");
          await b.t.personalSyncSnapshot(["notes"], format, peer, { selection, independentRemovals: true, propagateSelectedDeletions: true });
        }
        const meta = plain(data.personalSync.entities[key]); assert.ok(meta.proposal_id); assert.equal(meta.prior_hash, await b.t.personalSyncHash(descriptor));
        const parentMeta = parentRestore ? plain(data.personalSync.entities["note\0" + original.id]) : null;
        if (parentMeta) assert.ok(parentMeta.proposal_id);
        const proposalIds = fault === "parent-omitted-child" ? [parentMeta.proposal_id] : [meta.proposal_id, ...(parentMeta ? [parentMeta.proposal_id] : [])].sort();
        if (fault === "missing-parent") data.notizen = data.notizen.filter(value => value.id !== "parent-note");
        const source = plain(original);
        if (fault === "descriptor") { source.value.attachments.find(value => value.name === "removed.png").name = "CHANGED.png"; source.hash = await b.t.personalSyncHash(source.value); }
        if (fault === "clock") source.clock.push({ actor_id: peer, counter: 99 });
        const records = ["no-original", "parent-no-source"].includes(fault) ? [] : [source], members = { notes: [original.id], tasks: [] };
        const scope = { format: 10, epoch: "55555555-5555-4555-8555-555555555555", revision: 1, members, scope_hash: await b.t.personalSyncHash(members) };
        const projection = { request: { format, run_id: actor, trigger: "manual", modules: ["notes"] }, content_scope: scope, intents: [],
          batch: { records, records_hash: await b.t.personalSyncHash(records), commit_token: "77777777-7777-4777-8777-777777777777" } };
        const raw = Buffer.from(JSON.stringify(projection)), revision = hash(raw), frame = "88888888-8888-4888-8888-888888888888";
        let sequence = 0, savedHash = "", ordinary, claim, lateRaw, lateHash, prepares = 0, confirms = 0, checkpoints = 0, core = 0, ready = false;
        const post = b.w.webkit.messageHandlers.regression.postMessage;
        b.w.webkit.messageHandlers.regression.postMessage = text => {
          post(text); const message = JSON.parse(text);
          if (message.cmd === "speichern") { sequence++; savedHash = hash(message.text); queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true, standSha256: savedHash })); }
          else if (message.cmd === "mutations_snapshot") { checkpoints++; queueMicrotask(() => b.w.App.mutationsSnapshot({ token: message.token, ok: true })); }
          else if (message.cmd === "telefon_mcp") queueMicrotask(() => {
            const r = message.request; let response;
            switch (r.action) {
              case "notes_actor_source": response = { sourceRevision: "b".repeat(64) }; break;
              case "notes_actor_scope": response = { scopePage: { scope: { scope_epoch: scope.epoch, scope_revision: 1, scope_hash: scope.scope_hash }, offset: 0,
                total: 1, notes_total: 1, tasks_total: 0, next_offset: null, members, sourceRevision: "b".repeat(64), baseline: { record_format: format, propagate_deletions: true } } }; break;
              case "notes_actor_create": response = { actorId: actor, ownerToken: "d".repeat(64), bookSource: "" }; break;
              case "notes_actor_produce": response = { actor: { producer_staged: true, late_decision_phase: 1, proposal_count: proposalIds.length, message_count: 1,
                proposal_ids: proposalIds, book_sha256: savedHash, save_sequence: sequence } }; break;
              case "notes_actor_dispatch_proposals": response = { actor: { dispatch_started: true, message_count: 1, delivery_confirmed: false } }; break;
              case "notes_actor_start": case "notes_actor_cancel": response = { actor: {} }; break;
              case "notes_actor_read": {
                const bytes = r.attachmentSha256 ? r.attachmentSha256 === hash(removedBytes) && fault !== "blob" ? removedBytes : keepBytes : raw, end = Math.min(bytes.length, r.offset + r.limit);
                response = { actor: { batch_ready: true, revision, total_bytes: bytes.length, offset: r.offset, next_offset: end < bytes.length ? end : null,
                  data_base64: bytes.subarray(r.offset, end).toString("base64"), ...(r.attachmentSha256 ? { attachment_sha256: r.attachmentSha256, mime: "image/png" } : {}) } }; break;
              }
              case "notes_actor_prepare_commit": ordinary = { hash: r.bookSha256 }; response = { actor: { claim_token: "e".repeat(64), after_sha256: ordinary.hash, view_revision: revision, book_persisted: false } }; break;
              case "notes_actor_commit": core++; assert.equal(savedHash, ordinary.hash); ordinary.sequence = sequence;
                response = { actor: { core_committed: true, book_persisted: true, phone_persisted: false, book_sha256: savedHash, save_sequence: sequence } }; break;
              case "notes_actor_reply": response = { actor: { reply_queued: true, message_count: r.batches.length, book_persisted: true, phone_persisted: false, delivery_confirmed: false } }; break;
              case "notes_actor_status": response = { actor: { phase: "decision_review", packets: 4, phone_data_persisted: true, phone_persisted: false, book_persisted: true, reply_queued: true, completion_report_queued: true } }; break;
              case "notes_actor_late_review": {
                if (!ready) { ready = true; response = { actor: { review_ready: false, expected_proposals: proposalIds.length } }; break; }
                if (!lateRaw) {
                  lateRaw = Buffer.from(JSON.stringify({ targets: [{ proposal_id: meta.proposal_id, kind: "attachment", id: descriptor.attachment_id, parent_id: original.id,
                    prior_hash: meta.prior_hash, clock: meta.clock }], decisions: [{ proposal_id: meta.proposal_id, decision: choice, expected_clock: meta.clock }],
                    decision_message_ids: [frame], content_scope: scope, data_saved_book: { book_source: "c".repeat(64), sha256: ordinary.hash, sequence: ordinary.sequence }, review_revision: "9".repeat(64) }));
                  if (fault === "target-clock") { const changed = JSON.parse(lateRaw); changed.decisions[0].expected_clock[0].counter++; lateRaw = Buffer.from(JSON.stringify(changed)); }
                  if (parentMeta) {
                    const changed = JSON.parse(lateRaw);
                    changed.targets.unshift({ proposal_id: parentMeta.proposal_id, kind: "note", id: original.id, parent_id: "", prior_hash: parentMeta.prior_hash, clock: parentMeta.clock });
                    changed.decisions.unshift({ proposal_id: parentMeta.proposal_id, decision: "restore", expected_clock: parentMeta.clock });
                    if (fault === "parent-omitted-child") { changed.targets.pop(); changed.decisions.pop(); }
                    if (fault === "parent-reversed") { changed.targets.reverse(); changed.decisions.reverse(); }
                    lateRaw = Buffer.from(JSON.stringify(changed));
                  }
                  lateHash = hash(lateRaw);
                }
                const end = Math.min(lateRaw.length, r.offset + 113);
                response = { actor: { review_ready: true, expected_proposals: proposalIds.length, revision: lateHash, review_revision: "9".repeat(64), total_bytes: lateRaw.length, offset: r.offset,
                  next_offset: end < lateRaw.length ? end : null, data_base64: lateRaw.subarray(r.offset, end).toString("base64"), deletion_book_persisted: false, phone_persisted: false } }; break;
              }
              case "notes_actor_prepare_late_save": prepares++; claim = { claim_token: "8".repeat(64), revision: r.reviewRevision, after_sha256: r.bookSha256,
                before_sequence: ordinary.sequence, book_source: "c".repeat(64), book_persisted: false, deletion_book_persisted: false, phone_persisted: false }; response = { actor: claim }; break;
              case "notes_actor_confirm_late_save": confirms++; assert.equal(savedHash, claim.after_sha256);
                if (fault === "confirm-retry" && confirms === 1) { b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: false, code: "native_operation_failed" }); return; }
                response = { actor: { deletion_book_persisted: true, completion_started: true, book_sha256: savedHash, save_sequence: sequence, phone_persisted: false } }; break;
              case "notes_actor_advance_completion": response = { actor: { phase: "completed", book_persisted: true, deletion_book_persisted: true, phone_data_persisted: true,
                phone_persisted: true, reply_queued: true, completion_report_queued: true, deletion_completion: { expected: 1, received: 1, saved: 1, rejected: 0 } } }; break;
              default: throw Error("Unexpected action " + r.action);
            }
            b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: true, ...response });
          });
        };
        const start = await b.t.mcpNotesActorStart(owner, { peer_id: peer, fingerprint: "ABCD-1234-5678-90EF", expected_book_revision: await b.t.personalSyncHash(JSON.stringify(data)) }, new b.w.AbortController().signal);
        const status = () => b.t.mcpNotesActorStatus(owner, start.operation_id);
        const wait = async phases => {
          for (let n = 0; n < 600; n++) {
            await tick(); for (const timer of b.timers.filter(value => value.delay === 250 && !value.cancelled)) { timer.cancelled = true; timer.fn(); }
            if (phases.includes(status().phase)) return status();
          }
          throw Error("Stalled " + active + ": " + JSON.stringify(status()));
        };
        const initial = await wait(["review", "failed"]);
        if (fault === "blob") { assert.equal(initial.phase, "failed"); assert.equal(initial.error_code, "invalid_result"); assert.equal(sequence, 1); assert.equal(core, 0); assert.equal(prepares, 0); passed++; continue; }
        assert.equal(initial.phase, "review", active + ": " + JSON.stringify(initial));
        b.t.mcpNotesActorCommit(owner, start.operation_id, status().review_revision);
        const late = await wait(["late_review", "failed"]), rejected = ["target-clock", "parent-omitted-child"].includes(fault) || choice === "restore" && ["no-original", "descriptor", "missing-parent", "parent-no-source"].includes(fault);
        if (rejected) {
          assert.equal(late.phase, "failed", active); assert.equal(sequence, 2); assert.equal(prepares, 0);
          if (parentRestore) assert.ok(!data.notizen.some(value => value.id === "parent-note"), "Child failure leaked the partially restored parent candidate into the active book");
          passed++; continue;
        }
        assert.equal(late.phase, "late_review", active + ": " + JSON.stringify(late));
        assert.equal(data.notizen.find(value => value.id === "parent-note")?.anhaenge.some(value => value.id === "removed-image") || false, false,
          "Ordinary data phase resurrected pending attachment before the late review: " + active);
        const parentFields = value => value ? JSON.stringify(Object.fromEntries(Object.entries(value).filter(([key]) => key !== "anhaenge"))) : null;
        const beforeLateParent = parentFields(data.notizen.find(value => value.id === "parent-note"));
        b.t.mcpNotesActorCommit(owner, start.operation_id, late.review_revision);
        let done = await wait(["completed", "failed", "late_metadata_pending"]);
        if (fault === "confirm-retry") { assert.equal(done.phase, "late_metadata_pending"); b.t.mcpNotesActorCommit(owner, start.operation_id, done.review_revision); done = await wait(["completed", "failed"]); }
        assert.equal(done.phase, "completed", active + ": " + JSON.stringify(done)); assert.equal(sequence, 3); assert.equal(core, 1); assert.equal(prepares, 1); assert.equal(checkpoints, 2);
        const current = data.notizen.find(value => value.id === "parent-note");
        if (!parentMeta) assert.equal(parentFields(current), beforeLateParent, "Attachment restore replayed original parent fields instead of restoring only the exact child");
        if (current) {
          if (fault !== "clock") assert.equal(current.text, "Local newer text must survive");
          assert.equal(current.anhaenge.find(value => value.id === "keep-image").daten, url(keepBytes));
          assert.equal(current.anhaenge.some(value => value.id === "removed-image"), choice === "restore");
          if (choice === "restore") assert.equal(current.anhaenge.find(value => value.id === "removed-image").daten, url(removedBytes));
        }
        assert.equal(data.notizen.find(value => value.id === "private-note").text, "Never change"); passed++;
        if (historicalPiece) assert.deepEqual(plain(data.papierkorb.find(value => value.id === historicalPiece.id)), historicalPiece, "Coordination changed an older unrelated trash snapshot");
      } finally { b.close(); }
    }
  console.log("Original attachment actor: " + passed + " cases passed");
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
