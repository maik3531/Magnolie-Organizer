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
