"use strict";
// Refs #779: actual desktop load/editor/save/restore paths; native ACKs are synthetic.
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const { pathToFileURL } = require("node:url");
const { webcrypto } = require("node:crypto");
const harnessFile = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(harnessFile, module);
harness.filename = harnessFile; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(harnessFile, "utf8").split("async function run(web)")[0] + "\nmodule.exports = { boot, roots };", harnessFile);
const repo = path.resolve(__dirname, "../.."), mac = path.join(repo, "Magnolie-Organizer-macOS-Beta");
const fixture = JSON.parse(fs.readFileSync(path.join(mac, "Tests/BetaCoreTests/Fixtures/system-reminder-copy.json"), "utf8"));
const copy = value => JSON.parse(JSON.stringify(value));
const source = fixture.source, revision = "a".repeat(64), raw = fixture.records[0];
const metadata = { version: 1, identity: fixture.expectedIdentity, sourceUID: source.sourceUID, calendarID: source.calendarID,
  sourceTitle: source.title, parentUID: source.parentUID, parentTitle: source.parentTitle, parentType: source.parentType,
  nativeType: source.nativeType, readOnly: source.readOnly, permission: source.permission, identifier: raw.identifier, revision,
  copyKind: "standalone-public-fields", revisionCoverage: "serialized-fields-only" };
const task = { ...copy(fixture.expectedTask), id: "local-reminder-copy", uid: "independent-local-reminder@example.test",
  angelegt: 1780000600500, geaendert: 1780000600500, nativeReminderImport: metadata, nativeReminderRecord: raw };
const data = { aufgaben: [task, { id: "ordinary", uid: "ordinary@example.test", titel: "Ordinary task", angelegt: 1780000600500 }],
  notizen: [{ id: "unrelated", titel: "Keep", text: "Unrelated content", html: "Unrelated content" }],
  einstellungen: { allgemein: { handbuchHinweisGezeigt: true }, papierkorb: { an: true, tage: 0 } } };
let checks = 0;
function equal(actual, expected, label) { assert.deepEqual(copy(actual), copy(expected), label); checks++; }
function evidence(book, label) {
  const current = book.aufgaben.find(value => value.id === task.id);
  assert.ok(current, label + ": local identity retained"); checks++;
  equal(current.nativeReminderImport, metadata, label + ": exact provenance");
  equal(current.nativeReminderRecord, raw, label + ": exact original public fields");
  equal([current.uid, current.sync, current.syncQuellen, current.erinnern, current.delegiertAn],
    [task.uid, false, {}, false, ""], label + ": provenance grants no sync, alarm or delegation");
  const ordinary = book.aufgaben.find(value => value.id === "ordinary");
  equal([Object.hasOwn(ordinary, "nativeReminderImport"), Object.hasOwn(ordinary, "nativeReminderRecord")], [false, false], label + ": ordinary task stays unmarked");
}
async function macReplay(book, label) {
  if (!process.env.MACOS_BETA_REVIEW_UI) return;
  const { boot } = await import(pathToFileURL(path.join(mac, "tests/ui_harness.mjs")));
  const b = await boot(process.env.MACOS_BETA_REVIEW_UI);
  try {
    Object.defineProperty(b.w.crypto, "subtle", { value: webcrypto.subtle });
    b.w.MacBeta.receive("init", { daten: copy(book), neu: false, regional: { language: "en", timeZone: "UTC" } });
    await new Promise(resolve => setImmediate(resolve));
    const incoming = { version: 1, source: copy(source), displayTimeZone: "UTC",
      tasks: [{ identifier: raw.identifier, identity: fixture.expectedIdentity, revision, title: raw.fields.title,
        task: copy(fixture.expectedTask), nativeRecord: copy(raw), notices: copy(fixture.expectedNotices) }], excluded: [], snapshotRevision: "b".repeat(64) };
    const before = JSON.stringify(b.t.daten());
    const review = b.w.App.macOSBetaPrepareReminderImport(incoming);
    equal([review.newCount, review.existingCount], [0, 1], label + ": returning to Mac never duplicates the edited copy");
    equal(JSON.stringify(b.t.daten()), before, label + ": repeated proposal preserves local edits");
    b.w.App.macOSBetaCancelReminderImport(review.token);
    const trashed = copy(book), removed = trashed.aufgaben.find(value => value.id === task.id);
    trashed.aufgaben = trashed.aufgaben.filter(value => value.id !== task.id);
    trashed.papierkorb = [{ id: "removed-copy", art: "aufgabe", name: removed.titel, geloescht: Date.now(), eintrag: removed }];
    b.w.MacBeta.receive("init", { daten: trashed, neu: false, regional: { language: "en", timeZone: "UTC" } });
    const blocked = b.w.App.macOSBetaPrepareReminderImport(incoming);
    equal(blocked.newCount, 0, label + ": recycled copy is not recreated");
    equal(blocked.excluded[0].reasons, ["local-reminder-copy-in-trash"], label + ": exact source identity finds the recycle bin");
    b.w.App.macOSBetaCancelReminderImport(blocked.token);
  } catch (error) { console.error("Mac replay failure:", error); throw error; }
  finally { await new Promise(resolve => setImmediate(resolve)); b.close(); }
}
(async () => {
  assert.equal(harness.exports.roots.length, 2, "Both Linux and Windows canonical frontends are required");
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, copy(data));
    try {
      evidence(b.t.daten(), web + ": initial JSON load");
      b.t.speichereJetzt(); b.ack();
      const originalNotes = copy(b.t.daten().notizen);
      b.t.zustand().aufgaben.bearbeiteId = task.id;
      await b.t.wechsel("aufgaben");
      b.input("#aufgabe-titel", "Locally edited after Mac import");
      const save = [...b.w.document.querySelectorAll("#inhalt-rechts button")].find(button => button.textContent === "Save changes");
      assert.ok(save, "Actual task editor save button"); checks++; save.click();
      b.t.speichereJetzt(); b.ack();
      let stored = JSON.parse(b.saves().at(-1).text);
      equal(stored.aufgaben.find(value => value.id === task.id).titel, "Locally edited after Mac import", "Actual editor updates local title");
      evidence(stored, web + ": save payload");
      equal(stored.notizen, originalNotes, "Task edit leaves unrelated notes unchanged");
      for (const method of ["journalWiederhergestellt", "sicherungWiederhergestellt", "gesamtarchivImportiert"]) {
        b.w.App[method]({ ok: true, daten: copy(stored), kennwort: false });
        evidence(b.t.daten(), web + ": " + method);
      }
      const normalized = b.t.normalisiere(copy(stored));
      evidence(normalized, web + ": reopen normalization");
      const arbitrary = copy(task);
      arbitrary.nativeReminderImport = { version: 99, future: { "café": "NFC", "cafe\u0301": "NFD" }, sync: true, erinnern: true, delegiertAn: "untrusted" };
      arbitrary.nativeReminderRecord = [null, "future passive evidence"];
      const opaque = b.t.normalisiere({ aufgaben: [arbitrary] }).aufgaben[0];
      equal(opaque.nativeReminderImport, arbitrary.nativeReminderImport, "Unknown provenance remains opaque evidence");
      equal(opaque.nativeReminderRecord, arbitrary.nativeReminderRecord, "Unknown source shape is not silently discarded");
      equal([opaque.sync, opaque.erinnern, opaque.delegiertAn], [false, false, ""], "Fields inside provenance never become active rights");
      await macReplay(stored, web);
    } finally { await new Promise(resolve => setImmediate(resolve)); b.close(); }
  }
  console.log(JSON.stringify({ issue: 779, assertions: checks, desktopFrontends: 2, macReplay: !!process.env.MACOS_BETA_REVIEW_UI, nativePersistence: false }));
})().catch(error => { console.error(error); process.exitCode = 1; });
