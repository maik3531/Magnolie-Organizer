"use strict";
// Ordinary actual shared candidate merge must not decide a pending attachment restore.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const plain = value => JSON.parse(JSON.stringify(value)), tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("Pending attachment merge timed out"); process.exit(1); }, 30000);
(async () => {
  let passed = 0;
  for (const web of harness.exports.roots) for (const format of [3, 14]) for (const relation of ["dominates", "concurrent", "dominates-alias", "dominates-new-id"]) {
    const removed = "data:image/png;base64,iVBORw0KGgoB", retained = "data:image/png;base64,iVBORw0KGgoC";
    const b = await harness.exports.boot(web, { personalSync: { actor_id: "11111111-1111-4111-8111-111111111111" }, notizen: [
      { id: "parent-note", titel: "Parent", text: "Original", ursprungApp: "notes", anhaenge: [
        { id: "removed-image", name: "removed.png", art: "image", daten: removed }, { id: "retained-image", name: "retained.png", art: "image", daten: retained }] },
      { id: "private-note", titel: "Private", text: "Never mutate" }] });
    try {
      if (b.saves().length) b.ack(); await tick();
      const peer = "22222222-2222-4222-8222-222222222222", data = b.t.daten(), selection = { notes: new b.w.Set(["parent-note"]), tasks: new b.w.Set() };
      const record = plain((await b.t.personalSyncSnapshot(["notes"], format, peer, { selection, independentRemovals: true })).find(value => value.kind === "note"));
      const descriptor = record.value.attachments.find(value => value.name === "removed.png"), key = "attachment\0" + record.id + "\0" + descriptor.attachment_id;
      data.personalSync.entities[key].acknowledged_by_peer = true;
      const parent = data.notizen.find(value => value.id === "parent-note"); parent.anhaenge = parent.anhaenge.filter(value => value.id !== "removed-image"); parent.text = "Local edit";
      await b.t.personalSyncSnapshot(["notes"], format, peer, { selection, independentRemovals: true, propagateSelectedDeletions: true });
      const pending = plain(data.personalSync.entities[key]); assert.equal(pending.status, "local_pending");
      const incoming = plain(record); incoming.value.text = "Remote accepted edit"; incoming.value.modified_ms++;
      if (relation === "dominates-alias" || relation === "dominates-new-id") {
        const remoteId = "zz-remote-image";
        if (relation === "dominates-alias") data.personalSync.attachment_aliases[record.id + "\0" + remoteId] = descriptor.attachment_id;
        incoming.value.attachments.find(value => value.name === "removed.png").attachment_id = remoteId;
      }
      incoming.modified_ms = incoming.value.modified_ms; incoming.hash = await b.t.personalSyncHash(incoming.value);
      incoming.clock = relation.startsWith("dominates") ? plain(data.personalSync.entities["note\0" + record.id].clock) : plain(record.clock);
      incoming.clock.push({ actor_id: peer, counter: 99 }); incoming.clock.sort((a, z) => a.actor_id.localeCompare(z.actor_id));
      const baseline = JSON.stringify(data), incomingBefore = JSON.stringify(incoming), candidate = plain(data), attachmentData = Object.fromEntries(record.value.attachments.map(value => [value.sha256, value.name === "removed.png" ? removed : retained]));
      await b.t.personalSyncAnwendenAusBestand(candidate, [incoming], attachmentData, peer, ["notes"], { selection, independentRemovals: true }, format);
      const merged = candidate.notizen.find(value => value.id === "parent-note");
      assert.ok(!merged.anhaenge.some(value => value.id === "removed-image"), relation + ": ordinary parent merge restored a pending attachment before any native late decision/save");
      assert.equal(merged.anhaenge.find(value => value.id === "retained-image").daten, retained);
      assert.equal(candidate.personalSync.entities[key].proposal_id, pending.proposal_id);
      assert.equal(candidate.personalSync.entities[key].status, "local_pending");
      assert.deepEqual(plain(candidate.personalSync.entities[key]), pending);
      assert.equal(JSON.stringify(incoming), incomingBefore, "Ordinary filtering mutated the accepted original source record/hash");
      assert.ok(candidate.notizen.every(value => !value.anhaenge.some(item => item.id === "removed-image")), "Conflict materialization resurrected a pending attachment under another note");
      if (relation === "dominates-new-id") assert.equal(merged.anhaenge.find(value => value.id === "zz-remote-image").daten, removed, "Pending protection blocked a genuinely different incoming attachment identity");
      const noteBefore = plain(candidate.personalSync.entities["note\0" + record.id]);
      const afterSnapshot = await b.t.personalSyncSnapshotAusBestand(candidate, ["notes"], format, peer, { selection, independentRemovals: true });
      // A genuinely new identity keeps the legacy local attachment ordering;
      // its later projection may legitimately record that independent addition.
      if (relation !== "dominates-new-id") {
        assert.deepEqual(plain(candidate.personalSync.entities["note\0" + record.id].clock), noteBefore.clock, "Effective parent projection caused a spurious subsequent local clock change: " + format + "/" + relation + " " + JSON.stringify({ source: incoming.value, actual: afterSnapshot.find(value => value.kind === "note").value }));
        assert.equal(candidate.personalSync.entities["note\0" + record.id].hash, noteBefore.hash);
      }
      assert.equal(candidate.notizen.find(value => value.id === "private-note").text, "Never mutate");
      assert.equal(JSON.stringify(data), baseline); passed++;
    } finally { b.close(); }
  }
  console.log("Pending attachment merge: " + passed + " cases passed");
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
