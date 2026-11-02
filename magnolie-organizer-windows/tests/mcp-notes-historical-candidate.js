"use strict";
// Actual shared GUI preparation only, not native origin/save/receipt acceptance.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const plain = value => JSON.parse(JSON.stringify(value)), tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("Historical candidate test timed out"); process.exit(1); }, 30000);
(async () => {
  let passed = 0;
  for (const web of harness.exports.roots) for (const format of [3, 14]) for (const kind of ["note", "task"])
    for (const fault of ["none", "missing", "duplicate", "foreign", "changed", "clock", "hash", "confirmation", "delete", "data-member", "present", "resolved",
      "async-change", "caller-copy", "old-local-clock", "foreign-peer", "duplicate-target", ...(kind === "note" ? ["alias-duplicate", "pending-child"] : [])]) {
      const b = await harness.exports.boot(web, { personalSync: { actor_id: "11111111-1111-4111-8111-111111111111" },
        notizen: [{ id: "restore-note", titel: "Synthetic", text: "Preserve Grüße 🌸", ursprungApp: "notes" }, { id: "private-note", text: "Keep private" }],
        aufgaben: [{ id: "restore-task", titel: "Synthetic task", erledigt: false }] });
      try {
        if (b.saves().length) b.ack(); await tick();
        const peer = "22222222-2222-4222-8222-222222222222", run = "44444444-4444-4444-8444-444444444444", data = b.t.daten();
        const records = await b.t.personalSyncSnapshot(["notes", "tasks"], format, peer);
        const live = records.find(value => value.kind === kind && value.id.startsWith("restore-"));
        assert.ok(live); const key = kind + "\0" + live.id, list = kind === "note" ? "notizen" : "aufgaben";
        const original = plain(data[list].find(value => value.id === live.id));
        data.personalSync.entities[key].acknowledged_by_peer = true;
        b.t.inDenPapierkorb(kind, original, original.titel); data[list] = data[list].filter(value => value.id !== original.id);
        await b.t.personalSyncSnapshot(["notes", "tasks"], format, peer);
        const pending = plain(data.personalSync.entities[key]); assert.equal(pending.status, "local_pending");
        const proposal = { proposal_id: b.w.crypto.randomUUID(), kind, id: live.id, parent_id: "", clock: plain(pending.clock), prior_hash: pending.prior_hash,
          run_id: run, source_device: peer, deleted_ms: 2, label: "Synthetic historical" };
        const choice = { proposal_id: proposal.proposal_id, decision: "restore", expected_clock: plain(pending.clock), confirm_conflict: true };
        const selection = { notes: new b.w.Set(data.notizen.map(value => value.id)), tasks: new b.w.Set(data.aufgaben.map(value => value.id)) };
        if (fault === "missing") data.papierkorb = [];
        if (fault === "duplicate") data.papierkorb.push({ ...plain(data.papierkorb[0]), id: b.w.crypto.randomUUID() });
        if (fault === "foreign") data.papierkorb[0].eintrag[kind === "note" ? "baumQuelle" : "delegiertAn"] = "foreign";
        if (fault === "changed") data.papierkorb[0].eintrag.titel = "Substituted local source";
        if (fault === "clock") { proposal.clock[0].counter++; choice.expected_clock[0].counter++; }
        if (fault === "hash") proposal.prior_hash = "f".repeat(64);
        if (fault === "confirmation") choice.confirm_conflict = false;
        if (fault === "delete") choice.decision = "delete";
        if (fault === "data-member") selection[kind === "note" ? "notes" : "tasks"].add(live.id);
        if (fault === "present") data[list].push(plain(original));
        if (fault === "resolved") data.personalSync.entities[key].status = "resolved";
        if (fault === "old-local-clock") data.personalSync.counter = 0;
        if (fault === "foreign-peer") proposal.source_device = run;
        if (fault === "alias-duplicate") {
          data.personalSync.note_ids["second-local-id"] = live.id;
          data.papierkorb.push({ ...plain(data.papierkorb[0]), id: b.w.crypto.randomUUID(), eintrag: { ...plain(original), id: "second-local-id" } });
        }
        if (fault === "pending-child") data.personalSync.entities["attachment\0" + live.id + "\0pending-child"] = { state: "deleted", status: "local_pending" };
        const before = JSON.stringify(data), saves = b.saves().length;
        if (fault === "async-change") {
          const pending = b.t.personalSyncHistorischerRestoreKandidat(data, peer, [proposal], [choice], selection, format);
          data.notizen.find(value => value.id === "private-note").text = "User change during hash";
          const changed = JSON.stringify(data);
          await assert.rejects(() => pending);
          assert.equal(JSON.stringify(data), changed, "Async rejection overwrote user changes");
          assert.equal(b.saves().length, saves); passed++; continue;
        }
        if (fault === "caller-copy") {
          const pending = b.t.personalSyncHistorischerRestoreKandidat(data, peer, [proposal], [choice], selection, format);
          proposal.id = "caller-substitution"; choice.expected_clock[0].counter++; selection.notes.clear(); selection.tasks.clear();
          const result = await pending;
          assert.equal(result.action_authorized, false);
          assert.ok(result.book[list].some(value => value.id === original.id));
          assert.ok(!result.book[list].some(value => value.id === "caller-substitution"));
          assert.equal(JSON.stringify(data), before); assert.equal(b.saves().length, saves); passed++; continue;
        }
        if (fault === "duplicate-target") {
          const duplicate = { ...plain(proposal), proposal_id: b.w.crypto.randomUUID() };
          await assert.rejects(() => b.t.personalSyncHistorischerRestoreKandidat(data, peer, [proposal, duplicate],
            [choice, { ...plain(choice), proposal_id: duplicate.proposal_id }], selection, format));
        }
        else if (fault !== "none") await assert.rejects(() => b.t.personalSyncHistorischerRestoreKandidat(data, peer, [proposal], [choice], selection, format));
        else {
          const result = await b.t.personalSyncHistorischerRestoreKandidat(data, peer, [proposal], [choice], selection, format);
          assert.equal(result.action_authorized, false);
          assert.equal(result.book[list].find(value => value.id === original.id).titel, original.titel);
          assert.equal(result.book.personalSync.entities[key].state, "live");
          assert.equal(result.book.personalSync.entities[key].status, "restored");
          assert.ok(result.book.personalSync.counter > data.personalSync.counter);
          assert.deepEqual(plain(result.before_live), plain({ notes: [...selection.notes].sort(), tasks: [...selection.tasks].sort() }));
          assert.ok(result.after_live[kind === "note" ? "notes" : "tasks"].includes(live.id));
          assert.ok(!selection[kind === "note" ? "notes" : "tasks"].has(live.id));
          assert.equal(result.book.notizen.find(value => value.id === "private-note").text, "Keep private");
        }
        assert.equal(JSON.stringify(data), before, "Preparation mutated source book");
        assert.equal(b.saves().length, saves, "Preparation wrote without native save claim");
        passed++;
      } catch (error) { error.message = [web, format, kind, fault].join("/") + ": " + error.message; throw error; }
      finally { b.close(); }
    }
  console.log("Historical local restore candidates: " + passed + " cases passed");
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
