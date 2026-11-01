"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve)), plain = value => JSON.parse(JSON.stringify(value));
const watchdog = setTimeout(() => { console.error("Notes scope collection timed out"); process.exit(1); }, 30000);
(async () => {
  let passed = 0;
  for (const web of harness.exports.roots) for (const scenario of ["pages", "empty", "source", "offset", "count", "header", "no_progress", "duplicate", "hash", "identifier", "byte_limit", "member_limit", "module_boundary", "cancel", "draft", "book_changed"]) {
    const b = await harness.exports.boot(web);
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const owner = "a".repeat(48), source = "b".repeat(64), before = JSON.stringify(b.t.daten()), saves = b.saves().length;
      const target = { peer_id: "22222222-2222-4222-8222-222222222222", fingerprint: "ABCD-1234-5678-90EF" };
      const members = scenario === "empty" ? { notes: [], tasks: [] } : { notes: Array.from({ length: 129 }, (_, i) => "note-" + i.toString().padStart(3, "0")), tasks: ["task-ä", "task-😀"] };
      const header = { scope_epoch: "55555555-5555-4555-8555-555555555555", scope_revision: 1, scope_hash: await b.t.personalSyncHash(members) };
      let creates = 0, reads = 0, id = null, held = null;
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern") { queueMicrotask(() => b.ack()); return; }
        if (message.cmd !== "telefon_mcp") return;
        const r = message.request;
        queueMicrotask(() => {
          if (r.action === "notes_actor_source") { b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: true, sourceRevision: source }); return; }
          if (r.action === "notes_actor_create") {
            creates++; b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: false, code: "source_changed" }); return;
          }
          assert.equal(r.action, "notes_actor_scope"); assert.equal(r.sourceRevision, source); assert.equal(r.limit, 128);
          reads++;
          const all = [...members.notes, ...members.tasks], slice = all.slice(r.offset, r.offset + 128), noteCount = Math.min(slice.length, Math.max(0, members.notes.length - r.offset));
          const next = r.offset + slice.length;
          const page = { scope: plain(header), offset: r.offset, total: all.length, notes_total: members.notes.length, tasks_total: members.tasks.length,
            next_offset: next < all.length ? next : null, members: { notes: slice.slice(0, noteCount), tasks: slice.slice(noteCount) }, sourceRevision: source,
            baseline: { record_format: 3, propagate_deletions: false } };
          if (scenario === "source") page.sourceRevision = "c".repeat(64);
          if (scenario === "offset") page.offset++;
          if (scenario === "count") page.total++;
          if (scenario === "header" && reads === 2) page.scope.scope_revision++;
          if (scenario === "no_progress") { page.members = { notes: [], tasks: [] }; page.next_offset = r.offset; }
          if (scenario === "duplicate" && reads === 2) page.members.notes[0] = members.notes[127];
          if (scenario === "hash") page.scope.scope_hash = "f".repeat(64);
          if (scenario === "identifier") page.members.notes[0] = " invalid ";
          if (scenario === "byte_limit") page.members.notes = Array.from({ length: 128 }, (_, i) => "id" + i.toString().padStart(3, "0") + "\u0001".repeat(150));
          if (scenario === "member_limit") page.members.notes.push("more");
          if (scenario === "module_boundary") { page.members.tasks.push(page.members.notes.pop()); }
          const answer = () => b.w.App.telefonMcpErgebnis({ requestId: message.requestId, ok: true, scopePage: page });
          if (["cancel", "draft", "book_changed"].includes(scenario) && reads === 2) held = answer;
          else answer();
        });
      };
      const start = await b.t.mcpNotesActorStart(owner, { ...target, expected_book_revision: await b.t.personalSyncHash(before) }, new b.w.AbortController().signal);
      id = start.operation_id; let state = start;
      for (let i = 0; i < 100; i++) {
        await tick();
        if (held) {
          if (scenario === "cancel") b.t.mcpNotesActorCancel(owner, id);
          if (scenario === "draft") { b.t.oeffneTerminBlatt(null, "2026-11-01"); b.input("#tb-titel", "Preserve scope-read draft"); }
          if (scenario === "book_changed") b.t.daten().einstellungen.allgemein.concurrentScopeEdit = true;
          const answer = held; held = null; answer();
        }
        state = b.t.mcpNotesActorStatus(owner, id);
        if (["failed", "cancelled"].includes(state.phase)) break;
      }
      assert.equal(state.phase, scenario === "cancel" ? "cancelled" : "failed", scenario + JSON.stringify(state));
      assert.equal(creates, ["pages", "empty"].includes(scenario) ? 1 : 0, scenario + ": native owner created before complete valid scope");
      const valid = ["pages", "empty"].includes(scenario);
      assert.equal(b.saves().length, saves + (valid ? 1 : 0), "Invalid scope caused a baseline write");
      assert.equal(state.baseline_saved, valid);
      if (!valid && scenario !== "book_changed") assert.equal(JSON.stringify(b.t.daten()), before);
      if (scenario === "draft") assert.equal(b.w.document.querySelector("#tb-titel").value, "Preserve scope-read draft");
      passed++;
    } finally { b.w.close(); }
  }
  console.log("Notes accepted-scope frontend: " + passed + " cases passed");
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
