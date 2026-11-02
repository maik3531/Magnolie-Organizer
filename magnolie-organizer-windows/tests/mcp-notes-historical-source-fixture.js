"use strict";
// Synthetic actual shared-GUI source vectors for native projection parity tests.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const plain = value => JSON.parse(JSON.stringify(value));
const watchdog = setTimeout(() => { console.error("Historical source fixture timed out"); process.exit(1); }, 30000);
(async () => {
  const fixtures = [], peer = "22222222-2222-4222-8222-222222222222", run = "44444444-4444-4444-8444-444444444444";
  const image = JSON.parse(fs.readFileSync(path.join(__dirname, "resources/personal-sync-contract.json"), "utf8")).format2.data_url;
  for (const web of harness.exports.roots) for (const format of [3, 14]) for (const kind of ["note", "task"]) {
    const b = await harness.exports.boot(web, { personalSync: { actor_id: "11111111-1111-4111-8111-111111111111" },
      notizen: [{ id: "restore-note", titel: "Synthetic Grüße 🌸", text: "Protected synthetic source", ursprungApp: "notes",
        anhaenge: [{ id: "sample-image", name: "sample.png", art: "image", daten: image }] }],
      aufgaben: [{ id: "restore-task", titel: "Synthetic task", notiz: "Only synthetic", prio: 1, faellig: "2026-11-01", erledigt: false }] });
    try {
      if (b.saves().length) b.ack();
      b.w.Date.now = () => 1793505600000;
      const data = b.t.daten(), records = await b.t.personalSyncSnapshot(["notes", "tasks"], format, peer);
      const record = records.find(value => value.kind === kind), list = kind === "note" ? "notizen" : "aufgaben";
      const entry = data[list].find(value => value.id === record.id);
      data.personalSync.entities[kind + "\0" + record.id].acknowledged_by_peer = true;
      b.t.inDenPapierkorb(kind, plain(entry), entry.titel); data[list] = data[list].filter(value => value !== entry);
      await b.t.personalSyncSnapshot(["notes", "tasks"], format, peer);
      const meta = data.personalSync.entities[kind + "\0" + record.id];
      const fixture = { peer, run, format, book: plain(data), target: { proposal_id: b.w.crypto.randomUUID(), kind, id: record.id, parent_id: "",
        prior_hash: meta.prior_hash, clock: plain(meta.clock) }, members: { notes: data.notizen.map(value => value.id).sort(), tasks: data.aufgaben.map(value => value.id).sort() } };
      if (process.argv.includes("--candidate")) {
        fixture.choice = { proposal_id: fixture.target.proposal_id, decision: "restore", expected_clock: plain(meta.clock), confirm_conflict: true };
        const proposal = { ...plain(fixture.target), run_id: run, source_device: peer, deleted_ms: 2, label: "Synthetic candidate" };
        const result = await b.t.personalSyncHistorischerRestoreKandidat(data, peer, [proposal], [fixture.choice],
          { notes: new b.w.Set(fixture.members.notes), tasks: new b.w.Set(fixture.members.tasks) }, format);
        fixture.candidate_text = JSON.stringify(result.book);
      }
      fixtures.push(fixture);
    } finally { b.close(); }
  }
  process.stdout.write(JSON.stringify(fixtures));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
