"use strict";
// Actual shared JS candidate handlers. No native RPC, persistence or phone E2E claim.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve)), plain = value => JSON.parse(JSON.stringify(value));
const watchdog = setTimeout(() => { console.error("Late Notes candidate test timed out"); process.exit(1); }, 30000);
(async () => {
  let passed = 0;
  for (const web of harness.exports.roots) for (const format of [3, 14]) for (const kind of ["note", "task"])
    for (const scenario of ["delete", "restore", "no_trash", "wrong_clock"]) {
      const b = await harness.exports.boot(web, { personalSync: { actor_id: "11111111-1111-4111-8111-111111111111" },
        notizen: [{ id: "local-note", titel: "Synthetic original", text: "Preserve Grüße 🌸", ursprungApp: "notes" }, { id: "private-note", titel: "Private", text: "Never share or mutate" }],
        aufgaben: [{ id: "local-task", titel: "Synthetic original task", faellig: "2026-11-01", erledigt: false }] });
      try {
        if (b.saves().length) b.ack(); await tick();
        const peer = "22222222-2222-4222-8222-222222222222", data = b.t.daten();
        const selection = { notes: new b.w.Set(kind === "note" ? ["local-note"] : []), tasks: new b.w.Set(kind === "task" ? ["local-task"] : []) };
        const initial = await b.t.personalSyncSnapshot(["notes", "tasks"], format, peer, { selection, independentRemovals: true });
        const live = initial.find(value => value.kind === kind);
        assert.ok(live, kind + ": synthetic shared snapshot missing");
        const key = kind + "\0" + live.id, original = plain(kind === "note" ? data.notizen.find(value => value.id === "local-note") : data.aufgaben.find(value => value.id === "local-task"));
        data.personalSync.entities[key].acknowledged_by_peer = true;
        assert.ok(b.t.inDenPapierkorb(kind, original, original.titel));
        if (kind === "note") data.notizen = data.notizen.filter(value => value.id !== "local-note");
        else data.aufgaben = data.aufgaben.filter(value => value.id !== "local-task");
        await b.t.personalSyncSnapshot(["notes", "tasks"], format, peer,
          { selection, independentRemovals: true, propagateSelectedDeletions: true });
        const pending = plain(data.personalSync.entities[key]);
        assert.equal(pending.state, "deleted"); assert.equal(pending.status, "local_pending"); assert.ok(pending.proposal_id);
        const baseline = JSON.stringify(data), saves = b.saves().length, ordinary = plain(data);
        await b.t.personalSyncAnwendenAusBestand(ordinary, [plain(live)], {}, peer, ["notes", "tasks"], { selection, independentRemovals: true }, format);
        const list = kind === "note" ? "notizen" : "aufgaben", id = original.id;
        assert.ok(!ordinary[list].some(value => value.id === id), "Ordinary incoming data prematurely undid a pending local deletion");
        assert.equal(ordinary.personalSync.entities[key].proposal_id, pending.proposal_id);
        const late = plain(ordinary);
        if (scenario === "no_trash") late.papierkorb = [];
        const choice = { proposal_id: pending.proposal_id, decision: scenario === "delete" ? "delete" : "restore", expected_clock: plain(pending.clock) };
        if (scenario === "wrong_clock") choice.expected_clock[0].counter++;
        const before = JSON.stringify(late), expected = scenario === "no_trash" ? "restore_unavailable" : scenario === "wrong_clock" ? "conflict" : "applied";
        assert.equal(b.t.personalSyncEingehendeEntscheidungenAusBestand(late, [choice], selection), expected);
        if (expected !== "applied") assert.equal(JSON.stringify(late), before, "Rejected late review partially mutated its private candidate");
        else {
          assert.equal(late[list].some(value => value.id === id), scenario === "restore");
          if (scenario === "restore") {
            const restored = late[list].find(value => value.id === id);
            assert.equal(restored.titel, original.titel);
            if (kind === "note") assert.equal(restored.text, original.text);
          }
          const applied = JSON.stringify(late);
          assert.equal(b.t.personalSyncEingehendeEntscheidungenAusBestand(late, [choice], selection), "applied");
          assert.equal(JSON.stringify(late), applied, "Late decision replay repeated its data mutation");
        }
        assert.equal(late.notizen.find(value => value.id === "private-note").text, "Never share or mutate");
        assert.equal(JSON.stringify(b.t.daten()), baseline, "Private late review changed the active book before an explicit save claim");
        assert.equal(b.saves().length, saves, "Candidate preparation caused an unreported save");
        passed++;
      } finally { b.close(); }
    }
  console.log("Notes post-data late candidates: " + passed + " cases passed");
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
