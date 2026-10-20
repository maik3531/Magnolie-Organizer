"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");

async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/index.html", pretendToBeVisual: true });
  const w = dom.window;
  try {
    Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
    w.setTimeout = w.setInterval = () => 0;
    w.__MAGNOLIE_BRUECKE__ = "test"; w.webkit = { messageHandlers: { test: { postMessage() {} } } };
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
    w.App.init({ neu: false, daten: {
      notizen: [{ id: "local-note", titel: "Mobile", text: "Original", notizbuchId: "shared-book" },
        { id: "organizer-only", titel: "Private", text: "Do not project", notizbuchId: "private-book" }],
      aufgaben: [{ id: "mobile-task", titel: "Shared task" }, { id: "organizer-task", titel: "Private task" }],
      notizbuecher: [{ id: "shared-book", name: "Shared" }, { id: "private-book", name: "Private" }],
      personalSync: { actor_id: "11111111-1111-4111-8111-111111111111", note_ids: { "local-note": "wire-note" } }
    } });
    const t = w.OrganizerTest, peer = "22222222-2222-4222-8222-222222222222";
    const snapshotBook = JSON.parse(JSON.stringify(t.daten())), activeBefore = JSON.stringify(t.daten());
    snapshotBook.personalSync.note_ids = { "local-note": "copy-wire" };
    snapshotBook.personalSync.notebook_ids = { "shared-book": "copy-book" };
    snapshotBook.personalSync.attachment_aliases = { "copy-wire\0z-image": "a-image" };
    snapshotBook.notizen.find(note => note.id === "local-note").anhaenge = [{ id: "z-image", name: "copy.png", art: "image",
      daten: "data:image/png;base64,iVBORw0KGgoBAgM=" }];
    const copied = await t.personalSyncSnapshotAusBestand(snapshotBook, ["notes", "tasks"], 3, peer,
      { selection: { notes: new w.Set(["copy-wire"]), tasks: new w.Set(["mobile-task"]) }, independentRemovals: true });
    const copiedNote = copied.find(record => record.kind === "note");
    assert.equal(copiedNote.id, "copy-wire"); assert.equal(copiedNote.value.notebook_id, "copy-book");
    assert.equal(copiedNote.value.attachments[0].attachment_id, "a-image"); assert.equal(copied.attachmentSources.length, 1);
    assert.equal(JSON.stringify(t.daten()), activeBefore, "Private snapshot changed the active book or captured its editor draft");
    assert.ok(snapshotBook.personalSync.entities["note\0copy-wire"], "Private snapshot did not retain its own native bookkeeping");
    let active = true;
    const interrupted = t.personalSyncSnapshotAusBestand(snapshotBook, ["notes"], 3, peer, {
      selection: { notes: new w.Set(["copy-wire"]), tasks: new w.Set() }, independentRemovals: true,
      guard() { if (!active) throw Error("retired actor source"); }
    });
    active = false; await assert.rejects(interrupted, /retired actor source/);
    assert.equal(JSON.stringify(t.daten()), activeBefore, "Retired private snapshot mutated active data");
    const reviewOptions = { selection: { notes: new w.Set(["copy-wire"]), tasks: new w.Set(["mobile-task"]) }, independentRemovals: true };
    const incoming = JSON.parse(JSON.stringify(copiedNote)); incoming.value.text = "Private incoming text";
    incoming.hash = await t.personalSyncHash(incoming.value);
    incoming.clock.push({ actor_id: peer, counter: 1 });
    const attachments = Object.fromEntries(copied.attachmentSources.map(source => [source.sha256, source.data]));
    const reviewed = await t.personalSyncAnwendenAusBestand(snapshotBook, [incoming], attachments, peer, ["notes", "tasks"], reviewOptions);
    assert.equal(reviewed.conflicts, 0);
    assert.equal(snapshotBook.notizen.find(note => note.id === "local-note").text, "Private incoming text");
    assert.equal(snapshotBook.notizen.find(note => note.id === "local-note").anhaenge[0].id, "z-image");
    assert.equal(JSON.stringify(t.daten()), activeBefore, "Private merge changed active content, metadata or drafts");
    const incomingTask = JSON.parse(JSON.stringify(copied.find(record => record.kind === "task")));
    incomingTask.value.completed = true; incomingTask.value.uid = "private-task-uid";
    incomingTask.hash = await t.personalSyncHash(incomingTask.value); incomingTask.clock.push({ actor_id: peer, counter: 1 });
    await t.personalSyncAnwendenAusBestand(snapshotBook, [incomingTask], {}, peer, ["tasks"], reviewOptions);
    assert.equal(snapshotBook.aufgaben.find(task => task.id === "mobile-task").erledigt, true);
    assert.equal(snapshotBook.aufgaben.find(task => task.id === "mobile-task").uid, "private-task-uid");
    assert.equal(JSON.stringify(t.daten()), activeBefore, "Private task review changed the active task book");
    const conflict = JSON.parse(JSON.stringify(incoming)); conflict.value.text = "Remote concurrent text";
    conflict.clock = [{ actor_id: "33333333-3333-4333-8333-333333333333", counter: 1 }];
    conflict.hash = await t.personalSyncHash(conflict.value);
    const conflictReview = await t.personalSyncAnwendenAusBestand(snapshotBook, [conflict], attachments, peer, ["notes"], reviewOptions);
    assert.equal(conflictReview.conflicts, 1);
    assert.ok(snapshotBook.notizen.some(note => note.text === "Private incoming text"));
    assert.ok(snapshotBook.notizen.some(note => note.text === "Remote concurrent text"));
    assert.equal(JSON.stringify(t.daten()), activeBefore, "Private conflict copies escaped into the active book");
    const reviewBefore = JSON.stringify(snapshotBook);
    const forged = JSON.parse(JSON.stringify(incoming)); forged.id = "outside-scope";
    await assert.rejects(t.personalSyncAnwendenAusBestand(snapshotBook, [forged], attachments, peer, ["notes"], reviewOptions));
    assert.equal(JSON.stringify(snapshotBook), reviewBefore, "Out-of-scope review changed private state before validation");
    let reviewActive = true;
    const cancelledReview = t.personalSyncAnwendenAusBestand(snapshotBook, [incoming], attachments, peer, ["notes"], {
      ...reviewOptions, guard() { if (!reviewActive) throw Error("retired review owner"); }
    });
    reviewActive = false; await assert.rejects(cancelledReview, /retired review owner/);
    assert.equal(JSON.stringify(t.daten()), activeBefore, "Cancelled private review changed active data");
    const deleteBook = JSON.parse(JSON.stringify(snapshotBook)); deleteBook.einstellungen.papierkorb.an = true;
    const proposalFor = (kind, id, parent = "") => {
      const meta = deleteBook.personalSync.entities[kind + "\0" + (parent ? parent + "\0" : "") + id];
      return { proposal_id: webcrypto.randomUUID(), kind, id, parent_id: parent, clock: JSON.parse(JSON.stringify(meta.clock)),
        prior_hash: meta.hash, deleted_ms: Date.now(), label: "Owned private decision", source_device: peer };
    };
    const deletion = proposalFor("note", "copy-wire"), unchangedDelete = JSON.stringify(deleteBook);
    assert.equal(t.personalSyncEntscheidungAusBestand(t.daten(), deletion, "delete", reviewOptions.selection, true), "blocked");
    assert.equal(t.personalSyncEntscheidungAusBestand(deleteBook, { ...deletion, id: "organizer-only" }, "delete", reviewOptions.selection, true), "blocked");
    assert.equal(t.personalSyncEntscheidungAusBestand(deleteBook, { ...deletion, prior_hash: "f".repeat(64) }, "delete", reviewOptions.selection), "conflict");
    assert.equal(JSON.stringify(deleteBook), unchangedDelete, "Rejected private delete mutated book or trash");
    deleteBook.personalSync.pending_proposals.push(deletion);
    assert.equal(t.personalSyncEntscheidungAusBestand(deleteBook, deletion, "delete", reviewOptions.selection), "applied");
    assert.ok(!deleteBook.notizen.some(note => note.id === "local-note"));
    const archived = deleteBook.papierkorb.find(item => item.art === "note" && item.eintrag.id === "local-note");
    assert.ok(archived); assert.ok(t.ausDemPapierkorb(archived, deleteBook));
    assert.equal(deleteBook.personalSync.entities["note\0copy-wire"].state, "live");
    assert.ok(deleteBook.personalSync.restoration_requests.includes("note\0copy-wire"));
    const attachmentDelete = proposalFor("attachment", "a-image", "copy-wire");
    assert.equal(t.personalSyncEntscheidungAusBestand(deleteBook, attachmentDelete, "delete", reviewOptions.selection), "applied");
    assert.equal(deleteBook.notizen.find(note => note.id === "local-note").anhaenge.length, 0);
    const archivedImage = deleteBook.papierkorb.find(item => item.art === "attachment" && item.eintrag.id === "z-image");
    assert.ok(t.ausDemPapierkorb(archivedImage, deleteBook));
    assert.equal(deleteBook.notizen.find(note => note.id === "local-note").anhaenge[0].id, "z-image");
    assert.equal(deleteBook.personalSync.entities["attachment\0copy-wire\0a-image"].state, "live");
    const task = deleteBook.aufgaben.find(item => item.id === "mobile-task"), taskMeta = deleteBook.personalSync.entities["task\0mobile-task"];
    t.inDenPapierkorb("task", task, task.titel, "", {}, deleteBook);
    deleteBook.aufgaben = deleteBook.aufgaben.filter(item => item !== task);
    const localProposal = webcrypto.randomUUID(), priorClock = JSON.parse(JSON.stringify(taskMeta.clock));
    Object.assign(taskMeta, { state: "deleted", proposal_id: localProposal, prior_hash: taskMeta.hash, hash: "" });
    const restore = { proposal_id: localProposal, decision: "restore", expected_clock: priorClock };
    assert.equal(t.personalSyncEingehendeEntscheidungenAusBestand(t.daten(), [restore], reviewOptions.selection), "not_granted");
    const restoreBefore = JSON.stringify(deleteBook);
    assert.equal(t.personalSyncEingehendeEntscheidungenAusBestand(deleteBook, [restore], { notes: new w.Set(), tasks: new w.Set() }), "not_granted");
    assert.equal(t.personalSyncEingehendeEntscheidungenAusBestand(deleteBook, [{ ...restore, expected_clock: [] }], reviewOptions.selection), "conflict");
    assert.equal(t.personalSyncEingehendeEntscheidungenAusBestand(deleteBook, [restore, restore], reviewOptions.selection), "conflict");
    assert.equal(t.personalSyncEingehendeEntscheidungenAusBestand(deleteBook, [restore, { ...restore, proposal_id: webcrypto.randomUUID() }], reviewOptions.selection), "not_granted");
    assert.equal(JSON.stringify(deleteBook), restoreBefore, "Rejected typed decision partially restored private book state");
    assert.equal(t.personalSyncEingehendeEntscheidungenAusBestand(deleteBook, [restore], reviewOptions.selection), "applied");
    assert.ok(deleteBook.aufgaben.some(item => item.id === "mobile-task"));
    const restoredOnce = JSON.stringify(deleteBook);
    assert.equal(t.personalSyncEingehendeEntscheidungenAusBestand(deleteBook, [restore], reviewOptions.selection), "applied");
    assert.equal(JSON.stringify(deleteBook), restoredOnce, "Typed decision replay restored or advanced clocks twice");
    assert.equal(JSON.stringify(t.daten()), activeBefore, "Private delete/restore changed actual book, aliases or tracking");
    const selection = { notes: new w.Set(["wire-note"]), tasks: new w.Set(["mobile-task"]) };
    const excluded = t.daten().notizen.find(note => note.id === "organizer-only");
    const descriptors = {};
    for (const key of ["titel", "text", "html", "anhaenge"]) {
      descriptors[key] = Object.getOwnPropertyDescriptor(excluded, key);
      Object.defineProperty(excluded, key, { configurable: true, get() { throw Error("Excluded content/attachments accessed: " + key); } });
    }
    const records = await t.personalSyncSnapshot(["notes", "tasks"], 3, peer, { selection, independentRemovals: true });
    assert.deepEqual(Array.from(records, record => record.kind + ":" + record.id).sort(),
      ["note:wire-note", "notebook:shared-book", "task:mobile-task"]);
    assert.ok(!t.daten().personalSync.entities["note\0organizer-only"]);
    assert.ok(!t.daten().personalSync.entities["task\0organizer-task"]);
    assert.ok(!t.daten().personalSync.entities["notebook\0private-book"]);
    assert.equal(records.attachmentSources.length, 0);
    const meta = t.daten().personalSync.entities["note\0wire-note"];
    meta.acknowledged_by_peer = true;
    const before = JSON.stringify(meta);
    t.daten().notizen = t.daten().notizen.filter(note => note.id !== "local-note");
    const empty = { notes: new w.Set(), tasks: new w.Set() };
    const after = await t.personalSyncSnapshot(["notes", "tasks"], 3, peer, { selection: empty, independentRemovals: true });
    assert.equal(after.length, 0);
    assert.equal(after.attachmentSources.length, 0);
    assert.equal(JSON.stringify(t.daten().personalSync.entities["note\0wire-note"]), before,
      "Independent removal created a remote deletion proposal");
    assert.equal(t.daten().notizen.length, 1, "Scoped snapshot resurrected the removed note");
    for (const key of Object.keys(descriptors)) {
      delete excluded[key]; if (descriptors[key]) Object.defineProperty(excluded, key, descriptors[key]);
    }
    await t.personalSyncSnapshot(["notes", "tasks"], 3, peer);
    assert.equal(t.daten().personalSync.entities["note\0wire-note"].state, "deleted",
      "Legacy snapshot no longer retains its existing deletion contract");
  } finally { w.close(); }
}
(async () => {
  for (const web of require("./web-test-roots")) await check(web);
  console.log("PERSONAL CONTENT SCOPE PASSED: selected IDs before content/hash, minimal books, independent removal and legacy baseline on both frontends");
})().catch(error => { console.error(error); process.exitCode = 1; });
