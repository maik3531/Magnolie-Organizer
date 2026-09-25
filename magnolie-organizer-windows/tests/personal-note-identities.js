"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const peer = "33333333-3333-4333-8333-333333333333";
function client(web, id, actor, date) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/index.html", pretendToBeVisual: true });
  const w = dom.window;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.Date.now = () => 1790000000000 + date;
  w.__MAGNOLIE_BRUECKE__ = "test"; w.webkit = { messageHandlers: { test: { postMessage() {} } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  w.App.init({ daten: { personalSync: { actor_id: actor }, notizen: [{ id, titel: "Welcome", text: "Same content",
    html: "Same content", angelegt: date }] }, neu: false });
  return { dom, w, t: w.OrganizerTest };
}
async function check(web) {
  for (const variant of ["same", "same-format2", "attachment-id", "attachment-name", "attachment-content", "format1", "deleted-history", "occupied-parent"]) {
    const a = client(web, "z-local", "11111111-1111-4111-8111-111111111111", 1);
    const b = client(web, "a-local", "22222222-2222-4222-8222-222222222222", 2);
    try {
      const format = variant === "format1" ? 1 : variant === "same-format2" ? 2 : 3;
      const file = { id: "file", name: "image.png", art: "image", daten: "data:image/png;base64,AQID" };
      for (const c of [a, b]) c.t.daten().notizen[0].anhaenge = [{ ...file }];
      if (variant === "attachment-id") b.t.daten().notizen[0].anhaenge[0].id = "other-file";
      if (variant === "attachment-name") b.t.daten().notizen[0].anhaenge[0].name = "other.png";
      if (variant === "attachment-content") b.t.daten().notizen[0].anhaenge[0].daten = "data:image/png;base64,BAUG";
      const snapshot = c => c.t.personalSyncSnapshot(["notes"], format, peer);
      const firstA = await snapshot(a), firstB = await snapshot(b);
      const meta = a.t.daten().personalSync.entities["attachment\0z-local\0file"];
      if (variant === "deleted-history") a.t.daten().personalSync.entities["attachment\0z-local\0old-file"] = {
        ...meta, state: "deleted", status: "resolved" };
      if (variant === "occupied-parent") a.t.daten().personalSync.entities["attachment\0a-local\0file"] = {
        ...meta, parent_id: "a-local", state: "deleted" };
      const apply = (c, records, data) => {
        const descriptor = records.find(r => r.kind === "note").value.attachments?.[0];
        return c.t.personalSyncAnwenden(JSON.parse(JSON.stringify(records)), descriptor ? { [descriptor.sha256]: data } : {}, format, peer, ["notes"]);
      };
      await apply(a, firstB, b.t.daten().notizen[0].anhaenge[0].daten);
      if (!["same", "same-format2"].includes(variant)) {
        assert.equal(a.t.daten().notizen.length, 2, variant + " must prevent attachment identity merging");
        assert.equal(a.t.daten().notizen[0].anhaenge[0].daten, file.daten);
        continue;
      }
      await apply(b, firstA, file.daten);
      for (const c of [a, b]) {
        assert.equal(c.t.daten().notizen.length, 1); assert.equal(c.t.daten().notizen[0].anhaenge.length, 1);
      }
      const moved = a.t.daten().personalSync.entities["attachment\0a-local\0file"];
      assert.equal(moved.parent_id, "a-local"); assert.equal(moved.hash, meta.hash);
      assert.equal(moved.acknowledged_by_peer, false);
      assert.equal(a.t.daten().personalSync.entities["attachment\0z-local\0file"], undefined);
      a.w.App.init({ daten: JSON.parse(JSON.stringify(a.t.daten())), neu: false });
      const nextA = (await snapshot(a)).find(r => r.kind === "note"), nextB = (await snapshot(b)).find(r => r.kind === "note");
      assert.equal(nextA.hash, nextB.hash); assert.equal(nextA.id, nextB.id);
      assert.equal(a.t.daten().notizen[0].id, "z-local");
      assert.ok(!Object.values(a.t.daten().personalSync.entities).some(m => m.state === "deleted"));
      b.t.daten().notizen[0].text = "Edited with attachment"; b.t.daten().notizen[0].html = "Edited with attachment";
      await apply(a, await snapshot(b), file.daten);
      await apply(a, firstB, file.daten);
      assert.equal(a.t.daten().notizen.length, 1); assert.equal(a.t.daten().notizen[0].text, "Edited with attachment");
      assert.equal(a.t.daten().notizen[0].anhaenge.length, 1);
      const proposal = { kind: "attachment", id: "file", parent_id: "a-local", prior_hash: moved.hash,
        clock: moved.clock, source_device: peer, proposal_id: "matched-attachment", deleted_ms: 1 };
      assert.equal(a.t.personalSyncEntscheidungAnwenden(proposal, "delete"), "applied");
      const trash = a.t.daten().papierkorb.find(p => p.art === "attachment");
      assert.equal(trash.parent_id, "z-local"); assert.equal(a.t.ausDemPapierkorb(trash), true);
      assert.equal(a.t.daten().notizen[0].anhaenge[0].daten, file.daten);
      assert.equal(a.t.daten().personalSync.entities["attachment\0a-local\0file"].state, "live");
    } finally { a.w.close(); b.w.close(); }
  }
  for (const format of [1, 2, 3]) {
    const a = client(web, "z-local", "11111111-1111-4111-8111-111111111111", 1);
    const b = client(web, "a-local", "22222222-2222-4222-8222-222222222222", 2);
    const snapshot = c => c.t.personalSyncSnapshot(["notes"], format, peer);
    const apply = (c, records) => c.t.personalSyncAnwenden(JSON.parse(JSON.stringify(records)), {}, format, peer, ["notes"]);
    try {
      const firstA = await snapshot(a), firstB = await snapshot(b);
      assert.equal((await apply(a, firstB)).conflicts, 0);
      assert.equal((await apply(b, firstA)).conflicts, 0);
      assert.equal(a.t.daten().notizen.length, 1); assert.equal(b.t.daten().notizen.length, 1);
      assert.equal(a.t.daten().notizen[0].id, "z-local", "matching changed the local UI identity");
      assert.equal(b.t.daten().notizen[0].id, "a-local");
      const afterA = (await snapshot(a)).find(r => r.kind === "note"), afterB = (await snapshot(b)).find(r => r.kind === "note");
      assert.equal(afterA.id, "a-local"); assert.equal(afterB.id, afterA.id); assert.equal(afterA.hash, afterB.hash);
      a.w.App.init({ daten: JSON.parse(JSON.stringify(a.t.daten())), neu: false });
      if (format >= 2) {
        a.t.daten().notizen[0].anhaenge = [{ id: "file", name: "image.png", art: "image", daten: "data:image/png;base64,AQID" }];
        await snapshot(a);
        const attachment = a.t.daten().personalSync.entities["attachment\0a-local\0file"];
        assert.ok(attachment, "attachment metadata used a physical parent ID instead of the wire ID");
        const proposal = { kind: "attachment", id: "file", parent_id: "a-local", prior_hash: attachment.hash,
          clock: attachment.clock, source_device: peer, proposal_id: "attachment-proposal", deleted_ms: 1 };
        assert.equal(a.t.personalSyncEntscheidungAnwenden({ ...proposal, parent_id: "z-local" }, "delete", true), "conflict");
        assert.equal(a.t.personalSyncEntscheidungAnwenden(proposal, "delete"), "applied");
        const trash = a.t.daten().papierkorb.find(p => p.art === "attachment");
        assert.equal(trash.parent_id, "z-local"); assert.equal(a.t.ausDemPapierkorb(trash), true);
        assert.equal(a.t.daten().notizen[0].anhaenge.length, 1);
        assert.equal(a.t.daten().personalSync.entities["attachment\0a-local\0file"].state, "live");
        a.t.daten().notizen[0].anhaenge = [];
        delete a.t.daten().personalSync.entities["attachment\0a-local\0file"];
        a.t.daten().personalSync.restoration_requests = [];
      }
      a.t.daten().notizen[0].text = "Edited on A"; a.t.daten().notizen[0].html = "Edited on A";
      const edited = await snapshot(a); await apply(b, edited);
      assert.equal(b.t.daten().notizen.length, 1); assert.equal(b.t.daten().notizen[0].text, "Edited on A");
      await apply(b, firstA);
      assert.equal(b.t.daten().notizen[0].text, "Edited on A", "old identity replay overwrote the current content");
      for (const c of [a, b]) {
        await snapshot(c);
        for (const meta of Object.values(c.t.daten().personalSync.entities)) {
          meta.peer_device_id = peer; meta.acknowledged_by_peer = true;
        }
        await snapshot(c);
        assert.ok(!Object.values(c.t.daten().personalSync.entities).some(m => m.state === "deleted"),
          "identity matching invented a deletion");
      }
      const live = b.t.daten().personalSync.entities["note\0a-local"];
      const oldProposal = { kind: "note", id: "z-local", clock: live.clock, prior_hash: live.hash,
        proposal_id: "old-alias", source_device: peer, deleted_ms: 1 };
      assert.equal(b.t.personalSyncEntscheidungAnwenden(oldProposal, "delete", true), "conflict");
      assert.equal(b.t.daten().notizen.length, 1, "a stale alias deletion removed the retained note");
      const canonicalProposal = { ...oldProposal, id: "a-local", proposal_id: "canonical" };
      assert.equal(b.t.personalSyncEntscheidungAnwenden(canonicalProposal, "delete"), "applied");
      assert.equal(b.t.daten().notizen.length, 0);
      await apply(b, firstA); assert.equal(b.t.daten().notizen.length, 0, "deleted note returned under its old alias");
      a.t.daten().notizen = [];
      await snapshot(a);
      const deletions = Object.entries(a.t.daten().personalSync.entities).filter(([k, m]) => k.startsWith("note\0") && m.state === "deleted");
      assert.equal(deletions.length, 1); assert.equal(deletions[0][0], "note\0a-local");
    } finally { a.w.close(); b.w.close(); }
  }
  const a = client(web, "z-local", "11111111-1111-4111-8111-111111111111", 1);
  const b = client(web, "m-local", "22222222-2222-4222-8222-222222222222", 2);
  const c = client(web, "a-local", "44444444-4444-4444-8444-444444444444", 3);
  try {
    const snapshot = x => x.t.personalSyncSnapshot(["notes"], 3, peer);
    const apply = (x, records) => x.t.personalSyncAnwenden(JSON.parse(JSON.stringify(records)), {}, 3, peer, ["notes"]);
    const old = await snapshot(a);
    await apply(a, await snapshot(b)); await apply(a, await snapshot(c));
    const final = (await snapshot(a)).find(r => r.kind === "note");
    assert.equal(final.id, "a-local"); assert.equal(a.t.daten().notizen[0].id, "z-local");
    a.w.App.init({ daten: JSON.parse(JSON.stringify(a.t.daten())), neu: false });
    await apply(a, old); assert.equal(a.t.daten().notizen.length, 1);
    assert.equal((await snapshot(a)).find(r => r.kind === "note").id, "a-local");
  } finally { a.w.close(); b.w.close(); c.w.close(); }

  const foreign = client(web, "personal", "11111111-1111-4111-8111-111111111111", 1);
  try {
    const T = foreign.t;
    T.daten().notizen.push({ ...JSON.parse(JSON.stringify(T.daten().notizen[0])), id: "foreign" });
    const records = await T.personalSyncSnapshot(["notes"], 3, peer);
    const incoming = JSON.parse(JSON.stringify(records.find(r => r.id === "foreign")));
    T.daten().notizen.find(n => n.id === "foreign").baumQuelle = "tree-peer";
    T.daten().personalSync.entities["note\0foreign"].acknowledged_by_peer = true;
    T.daten().personalSync.entities["note\0foreign"].peer_device_id = peer;
    await T.personalSyncSnapshot(["notes"], 3, peer);
    assert.notEqual(T.daten().personalSync.entities["note\0foreign"].state, "deleted", "scope change invented a note deletion");
    assert.equal((await T.personalSyncAnwenden([incoming], {}, 3, peer, ["notes"])).conflicts, 1);
    assert.equal(T.daten().notizen.length, 2); assert.equal(Object.keys(T.daten().personalSync.note_aliases || {}).length, 0);
  } finally { foreign.w.close(); }

  const different = client(web, "local", "11111111-1111-4111-8111-111111111111", 1);
  const remote = client(web, "remote", "22222222-2222-4222-8222-222222222222", 2);
  try {
    remote.t.daten().notizen[0].text = "Different content"; remote.t.daten().notizen[0].html = "Different content";
    await different.t.personalSyncSnapshot(["notes"], 3, peer);
    await different.t.personalSyncAnwenden(JSON.parse(JSON.stringify(await remote.t.personalSyncSnapshot(["notes"], 3, peer))), {}, 3, peer, ["notes"]);
    assert.equal(different.t.daten().notizen.length, 2, "a matching title swallowed different note content");
  } finally { different.w.close(); remote.w.close(); }
  const restoring = client(web, "z-local", "11111111-1111-4111-8111-111111111111", 1);
  try {
    const T = restoring.t;
    T.daten().personalSync.note_ids = { "z-local": "a-wire" };
    T.daten().personalSync.note_aliases = { "z-local": "a-wire" };
    await T.personalSyncSnapshot(["notes"], 3, peer);
    const live = T.daten().personalSync.entities["note\0a-wire"];
    live.acknowledged_by_peer = true; live.peer_device_id = peer;
    T.inDenPapierkorb("note", T.daten().notizen[0], "Welcome");
    T.daten().notizen = [];
    await T.personalSyncSnapshot(["notes"], 3, peer);
    const proposal = T.daten().personalSync.entities["note\0a-wire"];
    T.daten().papierkorb.push({ id: "unrelated-trash", art: "task", eintrag: { id: "a-wire", titel: "Unrelated task" } });
    const decision = { proposal_id: proposal.proposal_id, decision: "restore", expected_clock: proposal.clock };
    const before = JSON.parse(JSON.stringify(T.daten()));
    T.daten().papierkorb = T.daten().papierkorb.filter(p => p.art !== "note");
    assert.equal(T.personalSyncEingehendeEntscheidungen([decision]), "restore_unavailable");
    assert.equal(T.daten().notizen.length, 0); assert.equal(T.daten().aufgaben.length, 0);
    T.daten().papierkorb = before.papierkorb;
    assert.equal(T.personalSyncEingehendeEntscheidungen([decision]), "applied");
    assert.equal(T.daten().notizen[0].id, "z-local"); assert.equal(T.daten().aufgaben.length, 0);
    assert.equal(T.daten().papierkorb.length, 1); assert.equal(T.daten().papierkorb[0].art, "task");
    assert.equal(T.personalSyncEingehendeEntscheidungen([decision]), "applied");
    assert.equal(T.daten().notizen.length, 1);
  } finally { restoring.w.close(); }

  for (const variant of ["formatting", "notebook", "attachment", "pending-deletion"]) {
    const local = client(web, "z-local", "11111111-1111-4111-8111-111111111111", 1);
    const other = client(web, "a-local", "22222222-2222-4222-8222-222222222222", 2);
    try {
      const note = local.t.daten().notizen[0];
      if (variant === "formatting") note.html = "<b>Same content</b>";
      if (variant === "notebook") note.notizbuchId = "different-book";
      if (variant === "attachment") note.anhaenge = [{ id: "file", name: "image.png", art: "image", daten: "data:image/png;base64,AQID" }];
      await local.t.personalSyncSnapshot(["notes"], 3, peer);
      if (variant === "pending-deletion") local.t.daten().personalSync.pending_proposals = [{ kind: "note", id: "z-local" }];
      const records = JSON.parse(JSON.stringify(await other.t.personalSyncSnapshot(["notes"], 3, peer)));
      await local.t.personalSyncAnwenden(records, {}, 3, peer, ["notes"]);
      assert.equal(local.t.daten().notizen.length, 2, variant + " must prevent identity merging");
      assert.equal(Object.keys(local.t.daten().personalSync.note_aliases).length, 0);
    } finally { local.w.close(); other.w.close(); }
  }
  for (const mapping of [{ note_ids: { local: "" } }, { note_aliases: { local: "a", a: "local" } }]) {
    const broken = client(web, "local", "11111111-1111-4111-8111-111111111111", 1);
    try {
      Object.assign(broken.t.daten().personalSync, mapping);
      await assert.rejects(() => broken.t.personalSyncSnapshot(["notes"], 3, peer));
      assert.equal(broken.t.daten().notizen.length, 1);
    } finally { broken.w.close(); }
  }
  console.log("PERSONAL NOTE IDENTITIES PASSED: " + web);
}
(async () => {
  const locations = [path.resolve(__dirname, "../app/web")];
  const linux = process.env.MAGNOLIE_LINUX_SOURCE ? path.resolve(process.env.MAGNOLIE_LINUX_SOURCE, "web") : path.resolve(__dirname, "../../magnolie-organizer/web");
  if (!process.argv.includes("--windows-only") && (process.env.MAGNOLIE_LINUX_SOURCE || fs.existsSync(linux))) locations.push(linux);
  for (const p of locations) await check(p);
})().catch(error => { console.error(error); process.exitCode = 1; });
