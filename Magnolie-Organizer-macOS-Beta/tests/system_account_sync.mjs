import assert from "node:assert/strict";
import fs from "node:fs";
import { boot, tick } from "./ui_harness.mjs";

// Actual projected Organizer UI. Provider outcomes, save ACK and final native
// disk verification are synthetic here; XCTest covers the native ledger path.
let checks = 0;
const clone = value => JSON.parse(JSON.stringify(value));
const equal = (a, b, label) => { assert.deepEqual(clone(a), clone(b), label); checks++; };
const ok = (value, label) => { assert.ok(value, label); checks++; };
const selection = { sourceUID: "macos-events:Zml4dHVyZQ==", kind: "events", start: "2026-01-01", end: "2027-01-01" };
const source = { uid: selection.sourceUID, art: "events", name: "Synthetic calendar", systemSyncFields: true, readOnly: false };
const contacts = { uid: "macos-contacts:Ym9vaw==", art: "contacts", name: "Synthetic contacts", systemSyncFields: true, readOnly: true };
const reminders = { uid: "macos-reminders:bGlzdA==", art: "reminders", name: "Synthetic reminders", systemSyncFields: true, readOnly: false };
const fixture = JSON.parse(fs.readFileSync(process.env.MACOS_BETA_SYSTEM_SYNC_UI_FIXTURE ||
  new URL("../Tests/BetaCoreTests/Fixtures/system-account-sync-ui.json", import.meta.url), "utf8"));
function preserves(required, proposed, path = "book") {
  if (Array.isArray(required)) {
    assert.ok(Array.isArray(proposed), path); assert.equal(proposed.length, required.length, path);
    required.forEach((value, index) => preserves(value, proposed[index], path + "[" + index + "]"));
  } else if (required && typeof required === "object") {
    assert.ok(proposed && typeof proposed === "object" && !Array.isArray(proposed), path);
    for (const [key, value] of Object.entries(required)) { assert.ok(Object.hasOwn(proposed, key), path + "." + key); preserves(value, proposed[key], path + "." + key); }
  } else assert.deepEqual(proposed, required, path);
}

async function context(locale = "en") {
  const b = await boot(process.argv[2]), seen = new Set();
  b.pump = async (save = true) => {
    for (let step = 0; step < 6; step++) {
      for (const message of [...b.messages]) if (message.cmd === "speichern" && !seen.has(message.id)) {
        seen.add(message.id); b.w.MacBeta.receive("gespeichert", { id: message.id, ok: save, fehler: save ? "" : "Synthetic save failure" });
      }
      await tick();
    }
  };
  b.w.MacBeta.receive("init", { daten: {
    termine: [{ id: "existing-event", uid: "existing-event-uid", titel: "Existing event", datum: "2026-11-01", zeit: "10:00", dauer: 60, futureEvent: { retain: true } }],
    aufgaben: [{ id: "existing-task", titel: "Existing task", kinder: [], futureTask: { retain: true } }],
    kontakte: [{ id: "existing-contact", vorname: "Existing", nachname: "Contact", futureContact: { retain: true } }],
    notizen: [{ id: "existing-note", titel: "Existing note", text: "Retain me", futureNote: { retain: true } }],
    futureRoot: { retain: true }, einstellungen: { allgemein: { handbuchHinweisGezeigt: true } }
  }, neu: false, regional: { language: locale, timeZone: "UTC" } });
  b.t.speichereJetzt(); await b.pump();
  b.starts = () => b.messages.filter(message => message.cmd === "macos_system_sync");
  b.start = async (value = selection) => {
    b.w.App.macOSBetaStartSystemSync(value); await b.pump();
    const request = b.starts().at(-1); ok(request, "A valid manual source start reaches the native command");
    equal(b.w.App.macOSBetaAdmitSystemSync(request.requestId, JSON.stringify(b.t.daten())),
      { ok: true, requestId: request.requestId, epoch: b.t.daten().syncEpoch }, "Admission matches the actual current saved model");
    return request;
  };
  b.page = () => {
    b.t.oeffneEinstellungen(); b.w.document.getElementById("einst-tab-sync").click();
    const status = b.messages.filter(message => message.cmd === "eds_status").at(-1);
    b.w.MacBeta.receive("edsStatus", { requestId: status.requestId, macos: true, verfuegbar: true, buchOk: true,
      systemAccountSyncImplemented: true, permissions: { events: "authorized", contacts: "authorized", reminders: "authorized" },
      kalender: [source, reminders], adressbuecher: [contacts], fehler: "" });
    return b.w.document.getElementById("macos-system-sync");
  };
  return b;
}

for (const locale of ["en", "de"]) {
  const b = await context(locale);
  try {
    const before = JSON.stringify(b.t.daten()), page = b.page();
    ok(page, "Real settings contain a separate native field-sync section");
    ok(page.textContent.includes(locale === "de" ? "Feldsynchronisation" : "field synchronization"), "The new section is localized: " + locale);
    ok(page.textContent.includes(locale === "de" ? "nicht exportiert" : "not sent"), "Bounded write scope is explained: " + locale);
    ok(page.textContent.includes(locale === "de" ? "atomar" : "atomically"), "Apple comparison/save limitation is explicit: " + locale);
    equal(b.w.document.getElementById("macos-system-sync-source").options.length, 4, "Calendar, contact and reminder source capabilities are separate from copy/read-only labels");
    equal([b.starts().length, JSON.stringify(b.t.daten())], [0, before], "Rendering and discovery grant no authority and mutate no book");
    b.w.document.getElementById("sync-jetzt").click(); await b.pump();
    equal(b.starts().length, 1, "Actual sync button uses the bounded native request once");
    equal(b.starts()[0].sourceUID, source.uid, "Selected native source is carried unchanged");
  } finally { b.close(); }
}

{
  const b = await context();
  try {
    b.t.daten().futureRoot.pending = "before start";
    b.w.App.macOSBetaStartSystemSync(selection); b.w.App.macOSBetaStartSystemSync(selection); await tick();
    equal(b.starts(), [], "No system account read/write is dispatched before the initial save ACK");
    await b.pump(); equal(b.starts().length, 1, "Duplicate starts share one pending save/request");
    const request = b.starts()[0];
    equal(b.w.document.body.inert, true, "The native phase locks ordinary editing");
    assert.throws(() => b.w.App.macOSBetaAdmitSystemSync(request.requestId, JSON.stringify({ ...b.t.daten(), futureRoot: {} })), /saved book/); checks++;
    b.w.MacBeta.receive("macOSBetaSystemSyncFinished", { requestId: "stale", ok: true });
    equal(b.w.document.body.inert, true, "A stale native completion cannot unlock the active request");
    b.w.MacBeta.receive("macOSBetaSystemSyncFinished", { requestId: request.requestId, ok: false, fehler: "Synthetic cancelled native consent" });
    equal([b.w.document.body.inert, b.w.App.macOSBetaSystemSyncBusy()], [false, false], "Native consent cancellation releases controls");
    ok(b.w.document.getElementById("zettel").textContent.includes("cancelled native consent"), "Consent cancellation is not a success");
  } finally { b.close(); }
}

for (const kind of ["events", "contacts", "reminders"]) {
  const b = await context();
  try {
    const selected = kind === "events" ? selection : { sourceUID: kind === "contacts" ? contacts.uid : reminders.uid, kind };
    const request = await b.start(selected), before = clone(b.t.daten()), candidate = clone(before);
    const key = kind === "events" ? "termine" : kind === "contacts" ? "kontakte" : "aufgaben";
    const field = kind === "contacts" ? "vorname" : "titel";
    candidate[key][0][field] = "Native supported field change";
    const runID = "synthetic-run-" + kind;
    const prepared = b.w.App.macOSBetaPrepareSystemSync(request.requestId, runID, JSON.stringify(candidate));
    equal(b.t.daten(), before, "Candidate normalization probe does not mutate the current book: " + kind);
    let finished = false;
    const completion = b.w.App.macOSBetaCommitSystemSync(request.requestId, runID, prepared.text).then(value => { finished = true; return value; });
    await tick(); equal(finished, false, "Commit awaits the actual save ACK: " + kind);
    equal(b.t.daten()[key][0][field], "Native supported field change", "Candidate is visible in the current model while awaiting its save: " + kind);
    equal(b.w.document.body.inert, true, "Save ACK alone has not released the native transaction: " + kind);
    await b.pump(); const receipt = await completion;
    equal([receipt.ok, receipt.requestId, receipt.runID], [true, request.requestId, runID], "UI returns a correlated save receipt: " + kind);
    equal(b.w.document.body.inert, true, "Independent native disk verification is still required: " + kind);
    const after = clone(b.t.daten()); after[key][0][field] = before[key][0][field];
    equal(after, before, "Other domains, local IDs and future fields survive: " + kind);
    b.w.MacBeta.receive("macOSBetaSystemSyncFinished", { requestId: request.requestId, ok: true });
    equal(b.w.document.body.inert, false, "Only final correlated native verification unlocks: " + kind);
    ok(b.w.document.getElementById("zettel").textContent.includes("saved and verified"), "Success appears after final native confirmation: " + kind);
  } finally { b.close(); }
}

for (const row of fixture.rows) {
  const b = await context();
  try {
    const selected = row.kind === "events" ? selection : { sourceUID: row.kind === "contacts" ? contacts.uid : reminders.uid, kind: row.kind };
    const request = await b.start(selected), before = clone(b.t.daten()), candidate = clone(before);
    const key = row.kind === "events" ? "termine" : row.kind === "contacts" ? "kontakte" : "aufgaben";
    const id = crypto.randomUUID();
    candidate[key].push({ ...clone(row.canonicalRecord), id, uid: id, sync: false, syncQuellen: {}, syncKalenderUid: "", geaendert: Date.now(),
      ...(row.kind === "reminders" ? { elternUid: "", reihenfolge: before.aufgaben.filter(task => !task.elternUid).length } : {}) });
    const prepared = b.w.App.macOSBetaPrepareSystemSync(request.requestId, "fixture-" + row.kind, JSON.stringify(candidate));
    preserves(candidate, JSON.parse(prepared.text)); checks++;
    equal(b.t.daten(), before, "Real copy-derived candidate remains a nonmutating preflight: " + row.kind);
    const completion = b.w.App.macOSBetaCommitSystemSync(request.requestId, "fixture-" + row.kind, prepared.text);
    await b.pump(); const receipt = await completion;
    equal([receipt.ok, b.t.daten()[key].length, b.t.daten()[key].at(-1).id], [true, before[key].length + 1, id], "Source-shaped first adoption survives the actual normalizer and ACK: " + row.kind);
    if (row.kind === "contacts") {
      equal(b.t.daten().jahrestage, before.jahrestage, "Contact-only birthday adoption creates no calendar anniversary or implicit name link");
      equal(b.t.daten().kontakte.at(-1).geburtstag, "--02-29", "Yearless leap birthday survives the sync candidate");
    }
  } finally { b.close(); }
}

{
  const b = await context();
  try {
    const request = await b.start(), before = clone(b.t.daten()), candidate = clone(before);
    candidate.termine[0].ort = "x".repeat(1001);
    const prepared = b.w.App.macOSBetaPrepareSystemSync(request.requestId, "invalid-field-probe", JSON.stringify(candidate));
    assert.throws(() => preserves(candidate, JSON.parse(prepared.text)), /ort/); checks++;
    equal(b.t.daten(), before, "Changed existing records undergo the real normalizer probe before any candidate is applied");
    equal(b.messages.filter(message => message.cmd === "speichern").at(-1).text, JSON.stringify(before), "A rejected planned field has no result-save message");
  } finally { b.close(); }
}

{
  const b = await context();
  try {
    const request = await b.start(), candidate = clone(b.t.daten()); candidate.termine[0].titel = "Pending native result";
    const prepared = b.w.App.macOSBetaPrepareSystemSync(request.requestId, "nack-run", JSON.stringify(candidate));
    const rejected = assert.rejects(b.w.App.macOSBetaCommitSystemSync(request.requestId, "nack-run", prepared.text), /saving was not confirmed/);
    await b.pump(false); await rejected; checks++;
    equal(b.t.daten().termine[0].titel, "Pending native result", "Save NACK does not invent rollback of an applied result");
    b.w.MacBeta.receive("macOSBetaSystemSyncFinished", { requestId: request.requestId, ok: false, fehler: "Synthetic retained journal" });
    b.t.speichereJetzt(); await b.pump();
    await b.start(); equal(b.t.daten().termine.length, 1, "A later explicit retry saves/rechecks the same candidate without duplicating records");
  } finally { b.close(); }
}

{
  const b = await context();
  try {
    const request = await b.start(), before = clone(b.t.daten()), candidate = clone(before); candidate.termine[0].titel = "Rendered later";
    const prepared = b.w.App.macOSBetaPrepareSystemSync(request.requestId, "renderer-run", JSON.stringify(candidate));
    const original = b.w.MagnolieAppearance; b.w.MagnolieAppearance = { ...original, update() { throw new Error("Synthetic renderer failure"); } };
    const completion = b.w.App.macOSBetaCommitSystemSync(request.requestId, "renderer-run", prepared.text);
    await b.pump(); const receipt = await completion; b.w.MagnolieAppearance = original;
    equal([receipt.ok, receipt.renderingFailed], [true, true], "Renderer failure does not lose the previously registered real save ACK");
    equal([b.t.daten().termine[0].titel, b.t.daten().notizen], ["Rendered later", before.notizen], "Rendered failure retains applied and unrelated data");
  } finally { b.close(); }
}

{
  const b = await context();
  try {
    b.t.daten().futureRoot.pending = "force an outstanding initial save";
    b.w.App.macOSBetaStartSystemSync(selection); await tick();
    b.t.oeffneTerminBlatt(null, "2026-11-01");
    const input = b.w.document.getElementById("tb-titel"); input.value = "Late editor draft"; input.dispatchEvent(new b.w.Event("input", { bubbles: true }));
    await b.pump(); equal(b.starts(), [], "An editor opened while saving blocks the subsequent native request");
    equal([input.isConnected, input.value], [true, "Late editor draft"], "Late draft is retained");
  } finally { b.close(); }
}

{
  const b = await context();
  try {
    b.t.daten().futureRoot.pending = "save failure before native start";
    b.w.App.macOSBetaStartSystemSync(selection); await b.pump(false);
    equal([b.starts(), b.w.App.macOSBetaSystemSyncBusy(), b.w.document.body.inert], [[], false, false], "Initial save NACK starts no provider operation and frees the UI");
    b.t.speichereJetzt(); await b.pump();
    const request = await b.start({ ...selection, action: "revoke" });
    equal(request.action, "revoke", "Revocation is a distinct native action, never an imported permission flag");
    const before = clone(b.t.daten());
    b.w.MacBeta.receive("macOSBetaSystemSyncFinished", { requestId: request.requestId, ok: true, revoked: true });
    equal(b.t.daten(), before, "Revoking native authority does not delete local entries");
  } finally { b.close(); }
}

for (const choice of ["Cancel", "Discard"]) {
  const b = await context();
  try {
    b.t.oeffneTerminBlatt(null, "2026-11-01");
    const input = b.w.document.getElementById("tb-titel"); input.value = "Pre-existing editor draft"; input.dispatchEvent(new b.w.Event("input", { bubbles: true }));
    b.w.App.macOSBetaStartSystemSync(selection);
    const button = [...b.w.document.querySelectorAll("#aenderungen-schleier button")].find(item => item.textContent === choice);
    ok(button, "Existing unsaved-editor guard is used for " + choice); button.click(); await b.pump();
    equal(b.starts().length, choice === "Cancel" ? 0 : 1, "Outer guard finishes before native synchronization: " + choice);
    if (choice === "Cancel") equal([input.isConnected, input.value], [true, "Pre-existing editor draft"], "Cancelled sync preserves the real editor draft");
  } finally { b.close(); }
}

{
  const b = await context();
  try {
    b.w.MacBeta.send({ cmd: "sicherung_wiederherstellen", pfad: "synthetic-restore.json", kennwort: "" }, "hostTest");
    b.w.App.macOSBetaStartSystemSync(selection); await b.pump();
    equal(b.starts(), [], "An active native restore blocks a stale system-sync entry");
  } finally { b.close(); }
}

{
  const b = await context();
  try {
    const request = await b.start(), candidate = clone(b.t.daten()); candidate.termine[0].titel = "Provider result";
    b.t.daten().termine[0].titel = "Concurrent local change";
    assert.throws(() => b.w.App.macOSBetaPrepareSystemSync(request.requestId, "changed-run", JSON.stringify(candidate)), /current book changed/); checks++;
    equal(b.t.daten().termine[0].titel, "Concurrent local change", "Programmatic concurrent changes are never overwritten by a late native candidate");
    const beforeStarts = b.messages.length;
    b.w.App.macOSBetaStartNoteImport(); b.w.App.macOSBetaStartCalendarImport(); b.w.App.macOSBetaStartContactImport(); b.w.App.macOSBetaStartReminderImport();
    await tick(); equal(b.messages.length, beforeStarts, "Other native copy/import entry points are blocked during sync");
  } finally { b.close(); }
}
console.log(JSON.stringify({ issue: 786, actualProjectedUIChecks: checks, locales: ["en", "de"],
  sourceShapedFixture: fixture.provenance, syntheticProviderAndDiskReceipts: true, nativeExecution: false }));
