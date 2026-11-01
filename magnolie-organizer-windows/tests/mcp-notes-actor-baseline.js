"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict"), { createHash } = require("node:crypto");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve)), plain = value => JSON.parse(JSON.stringify(value));
const watchdog = setTimeout(() => { console.error("Notes baseline test timed out"); process.exit(1); }, 30000);
(async () => {
  let passed = 0;
  for (const web of harness.exports.roots) for (const format of [3, 14]) for (const scenario of ["allowed", "disabled", "historical", "save_failed", "cancel_save", "late_draft", "pre_source", "post_source"]) {
    const b = await harness.exports.boot(web, { personalSync: { actor_id: "11111111-1111-4111-8111-111111111111" },
      notizen: [{ id: "removed-note", titel: "Synthetic removal", text: "Prior shared content" }, { id: "private-note", titel: "Private", text: "Retain unrelated content" }] });
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const peer = "22222222-2222-4222-8222-222222222222", owner = "a".repeat(48), source = "b".repeat(64);
      await b.t.personalSyncSnapshot(["notes"], format, peer, { selection: { notes: new b.w.Set(["removed-note"]), tasks: new b.w.Set() }, independentRemovals: true });
      const data = b.t.daten(), key = "note\0removed-note";
      data.personalSync.entities[key].acknowledged_by_peer = true;
      data.notizen = data.notizen.filter(note => note.id !== "removed-note");
      const before = plain(data), previous = plain(data.personalSync.entities[key]);
      const members = { notes: scenario === "historical" ? [] : ["removed-note"], tasks: [] };
      const scopeHash = await b.t.personalSyncHash(members), saves = b.saves().length;
      let id = null, creates = 0, sourceReads = 0, writes = 0, acks = 0, heldSave = null;
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern") {
          writes++;
          const answer = () => {
            if (scenario !== "save_failed") acks++;
            b.w.App.gespeichert({ id: message.id, ok: scenario !== "save_failed", standSha256: createHash("sha256").update(message.text).digest("hex") });
            if (scenario === "late_draft") { b.t.oeffneTerminBlatt(null, "2026-11-01"); b.input("#tb-titel", "Late baseline draft"); }
          };
          if (scenario === "cancel_save") heldSave = answer; else queueMicrotask(answer);
          return;
        }
        if (message.cmd !== "telefon_mcp") return;
        queueMicrotask(() => {
          const r = message.request; let response;
          if (r.action === "notes_actor_source") {
            sourceReads++;
            response = { sourceRevision: (scenario === "pre_source" && sourceReads === 2 || scenario === "post_source" && sourceReads === 3) ? "c".repeat(64) : source };
          } else if (r.action === "notes_actor_scope") response = { scopePage: {
            scope: { scope_epoch: "55555555-5555-4555-8555-555555555555", scope_revision: 1, scope_hash: scopeHash },
            offset: 0, total: members.notes.length, notes_total: members.notes.length, tasks_total: 0, next_offset: null, members,
            sourceRevision: source, baseline: { record_format: format, propagate_deletions: scenario !== "disabled" } } };
          else if (r.action === "notes_actor_create") {
            creates++; assert.equal(acks, 1, "Native Actor admission preceded actual baseline SaveACK");
            b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: false, code: "source_changed" }); return;
          } else throw Error("Unexpected baseline action " + r.action);
          b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: true, ...response });
        });
      };
      const start = await b.t.mcpNotesActorStart(owner, { peer_id: peer, fingerprint: "ABCD-1234-5678-90EF",
        expected_book_revision: await b.t.personalSyncHash(JSON.stringify(data)) }, new b.w.AbortController().signal);
      id = start.operation_id; let state = start;
      for (let i = 0; i < 150; i++) {
        await tick();
        if (heldSave) {
          b.t.mcpNotesActorCancel(owner, id);
          const answer = heldSave; heldSave = null; answer();
        }
        state = b.t.mcpNotesActorStatus(owner, id);
        if (["failed", "cancelled"].includes(state.phase) && (scenario !== "cancel_save" || state.baseline_saved)) break;
      }
      assert.equal(creates, ["allowed", "disabled", "historical"].includes(scenario) ? 1 : 0, scenario);
      assert.equal(writes, scenario === "pre_source" ? 0 : 1);
      assert.equal(b.saves().length, saves + writes);
      assert.equal(state.baseline_saved, !["save_failed", "pre_source"].includes(scenario));
      assert.equal(state.book_persisted, false, "Baseline was misreported as accepted incoming data commit");
      assert.equal(state.native_outcome_unknown, scenario === "save_failed", "Unconfirmed baseline write was reported as recalled/successful");
      assert.deepEqual(plain(data.notizen), before.notizen); assert.deepEqual(plain(data.papierkorb), before.papierkorb);
      const meta = plain(data.personalSync.entities[key]);
      if (["disabled", "historical", "pre_source"].includes(scenario)) assert.deepEqual(meta, previous);
      else {
        assert.equal(meta.state, "deleted"); assert.equal(meta.status, "local_pending");
        assert.equal(meta.prior_hash, previous.hash); assert.equal(meta.hash, ""); assert.ok(meta.proposal_id);
      }
      if (scenario === "late_draft") assert.equal(b.w.document.querySelector("#tb-titel").value, "Late baseline draft");
      passed++;
    } finally { b.close(); }
  }
  console.log("Notes guarded baseline: " + passed + " cases passed");
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
