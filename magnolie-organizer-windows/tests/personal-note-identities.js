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
  const locations = process.argv.includes("--windows-only") ? ["../app/web"] : ["../app/web", "../../magnolie-organizer/web"];
  for (const p of locations) await check(path.resolve(__dirname, p));
})().catch(error => { console.error(error); process.exitCode = 1; });
