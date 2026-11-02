"use strict";
// Complete private groups: no native save/receipt or public readiness claim.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const plain = value => JSON.parse(JSON.stringify(value)), tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("Historical group test timed out"); process.exit(1); }, 30000);
(async () => {
  let passed = 0;
  for (const web of harness.exports.roots) for (const format of [3, 14]) for (const fault of ["none", "last-source-missing", "different-run", "duplicate-choice", "partial-choice", "wrong-last-clock"]) {
    const b = await harness.exports.boot(web, { personalSync: { actor_id: "11111111-1111-4111-8111-111111111111" },
      notizen: [{ id: "restore-a", titel: "Synthetic A", text: "A" }, { id: "restore-b", titel: "Synthetic B", text: "B" }, { id: "keep-private", text: "Private" }],
      aufgaben: [{ id: "restore-task", titel: "Synthetic task", erledigt: false }] });
    try {
      if (b.saves().length) b.ack(); await tick();
      const peer = "22222222-2222-4222-8222-222222222222", run = "44444444-4444-4444-8444-444444444444", data = b.t.daten();
      const live = (await b.t.personalSyncSnapshot(["notes", "tasks"], format, peer)).filter(value => value.id.startsWith("restore-"));
      assert.equal(live.length, 3);
      for (const record of live) {
        const list = record.kind === "note" ? "notizen" : "aufgaben", original = data[list].find(value => value.id === record.id);
        data.personalSync.entities[record.kind + "\0" + record.id].acknowledged_by_peer = true;
        b.t.inDenPapierkorb(record.kind, plain(original), original.titel);
        data[list] = data[list].filter(value => value !== original);
      }
      await b.t.personalSyncSnapshot(["notes", "tasks"], format, peer);
      const proposals = live.map(record => {
        const meta = data.personalSync.entities[record.kind + "\0" + record.id]; assert.equal(meta.status, "local_pending");
        return { proposal_id: b.w.crypto.randomUUID(), kind: record.kind, id: record.id, parent_id: "", clock: plain(meta.clock), prior_hash: meta.prior_hash,
          run_id: run, source_device: peer, deleted_ms: 2, label: "Synthetic group" };
      });
      let choices = proposals.map(p => ({ proposal_id: p.proposal_id, decision: "restore", expected_clock: plain(p.clock), confirm_conflict: true }));
      const selection = { notes: new b.w.Set(["keep-private"]), tasks: new b.w.Set() };
      if (fault === "last-source-missing") data.papierkorb = data.papierkorb.filter(piece => piece.eintrag.id !== proposals.at(-1).id);
      if (fault === "different-run") proposals.at(-1).run_id = b.w.crypto.randomUUID();
      if (fault === "duplicate-choice") choices[2] = plain(choices[0]);
      if (fault === "partial-choice") choices.pop();
      if (fault === "wrong-last-clock") choices.at(-1).expected_clock[0].counter++;
      const before = JSON.stringify(data), saves = b.saves().length;
      if (fault !== "none") await assert.rejects(() => b.t.personalSyncHistorischerRestoreKandidat(data, peer, proposals, choices, selection, format));
      else {
        const result = await b.t.personalSyncHistorischerRestoreKandidat(data, peer, proposals, choices, selection, format);
        assert.equal(result.action_authorized, false); assert.equal(result.book.papierkorb.length, 0);
        assert.deepEqual(plain(result.after_live), { notes: ["keep-private", "restore-a", "restore-b"], tasks: ["restore-task"] });
        assert.deepEqual(plain(result.before_live), { notes: ["keep-private"], tasks: [] });
        assert.equal(result.book.personalSync.counter, data.personalSync.counter + 3);
        for (const proposal of proposals) assert.equal(result.book.personalSync.entities[proposal.kind + "\0" + proposal.id].state, "live");
        assert.equal(result.book.personalSync.applied_decisions.length, data.personalSync.applied_decisions.length + 3);
      }
      assert.equal(JSON.stringify(data), before, "Rejected complete group partially mutated the source");
      assert.equal(b.saves().length, saves, "Group preparation unexpectedly saved"); passed++;
    } catch (error) { error.message = [web, format, fault].join("/") + ": " + error.message; throw error; }
    finally { b.close(); }
  }
  console.log("Historical complete local restore groups: " + passed + " cases passed");
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
