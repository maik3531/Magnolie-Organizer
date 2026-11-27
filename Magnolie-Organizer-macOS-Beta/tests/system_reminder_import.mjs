import assert from "node:assert/strict";
import fs from "node:fs";
import { createHash, webcrypto } from "node:crypto";
import { boot, tick } from "./ui_harness.mjs";

const clone = value => JSON.parse(JSON.stringify(value));
const digest = value => createHash("sha256").update(JSON.stringify(value)).digest("hex");
const fixture = JSON.parse(fs.readFileSync(new URL("../Tests/BetaCoreTests/Fixtures/system-reminder-copy.json", import.meta.url), "utf8"));
let checks = 0;
const equal = (actual, expected, label) => { assert.deepEqual(clone(actual), clone(expected), label); checks++; };
const ok = (value, label) => { assert.ok(value, label); checks++; };
const throws = (action, pattern, label) => { assert.throws(action, pattern, label); checks++; };
const rejects = async (action, pattern, label) => { await assert.rejects(action, pattern, label); checks++; };
const initial = { termine: [],
  aufgaben: [
    { id: "local-root", uid: "local-root-uid", titel: fixture.expectedTask.titel, reihenfolge: 0, future: { keep: 1 } },
    { id: "local-child", uid: "local-child-uid", elternUid: "local-root-uid", titel: "Existing child", reihenfolge: 0, future: { keep: 2 } },
    { id: "local-grandchild", uid: "local-grandchild-uid", elternUid: "local-child-uid", titel: "Existing grandchild", reihenfolge: 0 },
    { id: "local-second", uid: "local-second-uid", titel: "Second root", reihenfolge: 1, future: { keep: [3, 4] } }
  ], kontakte: [{ id: "local-contact", vorname: "Local", nachname: "Contact" }],
  jahrestage: [{ id: "local-annual", uid: "local-annual-uid", name: "Unrelated yearly entry", datum: "--03-01", typ: "anniversary" }],
  notizen: [{ id: "local-note", titel: "Local note", text: "Original note", html: "Original note", notizbuchId: "local-book" }],
  notizgruppen: [{ id: "group", name: "Notebooks" }], notizbuecher: [{ id: "local-book", gruppeId: "group", name: "Notes" }],
  futureRoot: { keep: ["opaque", { value: 17 }] },
  einstellungen: { allgemein: { handbuchHinweisGezeigt: true }, regional: { timeZone: fixture.displayTimeZone } } };
const source = (id = fixture.source.calendarID) => ({ ...clone(fixture.source), sourceUID: "macos-reminders:" + Buffer.from(id).toString("base64"), calendarID: id });
function item(identifier = "reminder-one", { origin = source(), change = () => {} } = {}) {
  // This is the shared reader/Core-shaped fixture, not a claim of native Swift
  // execution. Revisions below are synthetic transport tokens for actual JS.
  const nativeRecord = clone(fixture.records[0]); nativeRecord.identifier = identifier;
  const value = { identifier, title: nativeRecord.fields.title, task: clone(fixture.expectedTask), nativeRecord, notices: fixture.expectedNotices.slice() };
  change(value);
  return { ...value, identity: identifier === "reminder-one" && origin.calendarID === fixture.source.calendarID
    ? fixture.expectedIdentity : digest([origin.sourceUID, identifier]), revision: digest([origin, value.nativeRecord]) };
}
function payload(tasks, origin = source(), excluded = [], displayTimeZone = fixture.displayTimeZone) {
  return { version: 1, source: origin, displayTimeZone, tasks, excluded, snapshotRevision: digest([origin, tasks, excluded]) };
}
function setDates(value, start = "", startTime = "", due = "", dueTime = "", zone = null) {
  const components = (date, time) => date ? { calendar: "gregorian", calendarTimeZone: "Pacific/Auckland",
    year: +date.slice(0, 4), month: +date.slice(5, 7), day: +date.slice(8, 10),
    ...(time ? { hour: +time.slice(0, 2), minute: +time.slice(3, 5), second: 0 } : {}), ...(zone ? { timeZone: zone } : {}) } : null;
  const line = (name, date, time) => date ? name + (time ? zone ? ";TZID=" + zone : "" : ";VALUE=DATE") + ":" +
    date.replaceAll("-", "") + (time ? "T" + time.replace(":", "") + "00" : "") : null;
  Object.assign(value.task, { startDatum: start, startZeit: startTime, faellig: due, faelligZeit: dueTime,
    icsRoundtrip: [line("DTSTART", start, startTime), line("DUE", due, dueTime)].filter(Boolean) });
  value.nativeRecord.fields.startComponents = components(start, startTime);
  value.nativeRecord.fields.dueComponents = components(due, dueTime);
}
async function context(book = initial) {
  const b = await boot(process.argv[2], Date.parse("2026-05-01T12:00:00Z")), seen = new Set();
  const { w, t, messages } = b;
  Object.defineProperty(w.crypto, "subtle", { value: webcrypto.subtle });
  w.MacBeta.receive("init", { daten: clone(book), neu: false, regional: { language: "en", timeZone: fixture.displayTimeZone } });
  const pump = async ({ snapshot = true, save = true, ackSnapshots = true, ackSaves = true } = {}) => {
    for (let n = 0; n < 8; n++) {
      for (const message of [...messages]) {
        const key = message.cmd + ":" + (message.id ?? message.token ?? "");
        if (seen.has(key)) continue;
        if (message.cmd === "speichern" && ackSaves) {
          seen.add(key); w.MacBeta.receive("gespeichert", { id: message.id, ok: save, fehler: save ? "" : "Synthetic save failure" });
        }
        if (message.cmd === "mutations_snapshot" && ackSnapshots) {
          seen.add(key); w.MacBeta.receive("mutationsSnapshot", { token: message.token, ok: snapshot, fehler: snapshot ? "" : "Synthetic recovery failure" });
        }
      }
      await tick();
    }
  };
  await pump(); return { ...b, pump };
}
async function commit(b, review, options) {
  const pending = b.w.App.macOSBetaCommitReminderImport(review.token).then(value => ({ value }), error => ({ error }));
  await b.pump(options); const outcome = await pending;
  if (outcome.error) throw outcome.error;
  return outcome.value;
}
function changeInput(w, field, value) {
  field.value = value; field.dispatchEvent(new w.Event("input", { bubbles: true }));
}
async function editTask(b, task) {
  if (b.t.zustand().sektion === "aufgaben") await b.t.wechsel("planer");
  b.t.zustand().aufgaben.bearbeiteId = task.id; await b.t.wechsel("aufgaben");
  const form = b.w.document.querySelector("#inhalt-rechts fieldset.formular");
  ok(form && form.querySelector("#aufgabe-titel").value === task.titel, "Actual canonical task editor opens"); return form;
}
async function saveTask(b, form) {
  const save = [...form.querySelectorAll(".form-knoepfe button")].find(button => button.textContent === "Save changes");
  ok(save, "Actual canonical task save action exists"); save.click(); b.t.speichereJetzt(); await b.pump();
  ok(!form.isConnected, "Successful task edit leaves the editor");
}

let reopened;
{
  const b = await context(), { w, t, messages } = b;
  try {
    t.speichereJetzt(); await b.pump();
    const before = JSON.stringify(t.daten()), tasks = JSON.stringify(t.daten().aufgaben);
    const unrelated = JSON.stringify(Object.fromEntries(Object.entries(t.daten()).filter(([key]) => key !== "aufgaben")));
    const incoming = payload([item(), item("second")]), review = w.App.macOSBetaPrepareReminderImport(incoming);
    equal(JSON.stringify(t.daten()), before, "Preparation leaves every existing document byte unchanged");
    equal([review.newCount, review.existingCount, review.changedCount, review.targetTitle, review.displayTimeZone], [2, 0, 0, "Tasks", fixture.displayTimeZone], "Complete Core-shaped fixture produces two standalone task copies");
    equal(review.source, source(), "Exact list and account metadata shown in review");
    equal(review.preview[0].notices, fixture.expectedNotices, "Explicit public-field, priority and standalone notices retained");
    for (const text of [fixture.expectedTask.titel, fixture.expectedTask.notiz, "09:05", "10:45", "2026-11-27", "Europe/Berlin", "Room 4",
      "https://example.test/review", new Date(1780000000.125 * 1000).toISOString(), new Date(1780000600.5 * 1000).toISOString(),
      "Original priority: 0", "Display timezone", "Floating time; no source time zone is assigned.", "No task notification is enabled by this copy."])
      ok(review.preview[0].text.includes(text), "Full exact preview includes " + text);
    incoming.tasks[0].task.titel = "Outside mutation"; review.preview[0].text = "Outside mutation";
    throws(() => w.App.macOSBetaPrepareReminderImport(payload([item("parallel")])), /already/, "Only one private review can be outstanding");
    await rejects(w.App.macOSBetaCommitReminderImport("wrong-token"), /Invalid/, "Wrong token cannot consume a valid review");
    let finished = false;
    const pending = w.App.macOSBetaCommitReminderImport(review.token).then(value => { finished = true; return value; });
    equal(JSON.stringify(t.daten()), before, "No append before the recovery checkpoint acknowledgement");
    await b.pump({ ackSaves: false });
    equal([finished, t.daten().aufgaben.length], [false, 6], "Append waits for the actual durable save acknowledgement");
    const outstanding = messages.filter(message => message.cmd === "speichern").at(-1);
    w.MacBeta.receive("gespeichert", { id: outstanding.id + "-foreign", ok: true }); await tick();
    equal(finished, false, "Foreign save reply cannot complete the transaction");
    equal(w.App.macOSBetaCancelReminderImport(review.token).cancelled, false, "Saving proposal cannot be cancelled or replaced");
    await b.pump(); equal((await pending).count, 2, "Durable save returns exact appended count");
    equal(JSON.stringify(t.daten().aufgaben.slice(0, 4)), tasks, "Existing roots, descendants, order and extra fields are all unchanged");
    equal(JSON.stringify(Object.fromEntries(Object.entries(t.daten()).filter(([key]) => key !== "aufgaben"))), unrelated, "Anniversaries, contacts, notes and settings remain exact");
    const copy = t.daten().aufgaben[4];
    equal(copy.titel, fixture.expectedTask.titel, "Private proposal cannot be changed through the returned preview or caller payload");
    equal(copy.nativeReminderRecord, fixture.records[0], "All exact source timestamps, absent zones and public raw fields survive");
    equal(copy.nativeReminderImport, { version: 1, identity: fixture.expectedIdentity, sourceUID: source().sourceUID, calendarID: source().calendarID,
      sourceTitle: source().title, parentUID: source().parentUID, parentTitle: source().parentTitle, parentType: source().parentType,
      nativeType: source().nativeType, readOnly: false, permission: "authorized", identifier: "reminder-one", revision: item().revision,
      copyKind: "standalone-public-fields", revisionCoverage: "serialized-fields-only" }, "Versioned standalone provenance is inert and complete");
    equal([copy.elternUid, copy.icsElternUid, copy.icsElternQuelleId, copy.icsImportUid, copy.icsSerienUid, copy.personen], ["", "", "", "", "", []], "No native or local hierarchy/person association is invented");
    equal([copy.sync, copy.syncQuellen, copy.syncKalenderUid, copy.icsQuelleId, copy.icsQuelleName, copy.herkunft, copy.fremdId, copy.delegiertAn], [false, {}, "", "", "", "", "", ""], "Copy acquires no source sync, delegated branch or source-write authority");
    equal([copy.reihenfolge, t.daten().aufgaben[5].reihenfolge], [2, 3], "New roots append after existing root siblings without renumbering descendants");
    equal([copy.angelegt, copy.geaendert, copy.personalGeaendert], Array(3).fill(Date.parse("2026-05-01T12:00:00Z")), "Constructor assigns honest local creation timestamps");
    ok(/^mag-.+@magnolie-organizer$/.test(copy.uid) && copy.uid !== t.daten().aufgaben[5].uid, "Independent canonical local UIDs, not native identities");
    equal(new Set(t.daten().aufgaben.map(task => task.id)).size, 6, "Independent fresh task IDs");
    equal([copy.erinnern, copy.individuelleErinnerungTage, copy.vorlaufTage, copy.erinnerungsMinute], [false, 0, 0, 480], "Due dates do not enable any local alarm default");
    equal(w.MacBeta.taskAlarms(copy, fixture.displayTimeZone), [], "Actual Mac task alarm projector has no notification for the copy");
    equal(t.normalisiere(clone(t.daten())).aufgaben, t.daten().aufgaben, "Whole task hierarchy and copied provenance are a reload normalization fixed point");
    await rejects(w.App.macOSBetaCommitReminderImport(review.token), /Invalid/, "Consumed token cannot be replayed");
    copy.titel = "Edited locally"; copy.notiz = "My local note"; copy.prio = 1; copy.future = { keep: 42 };
    const edited = JSON.stringify(copy), repeat = w.App.macOSBetaPrepareReminderImport(payload([item(), item("second")]));
    equal([repeat.newCount, repeat.existingCount, repeat.changedCount], [0, 2, 0], "Repeated source recognizes provenance despite local edits");
    equal((await commit(b, repeat)).count, 0, "Empty reviewed append remains valid"); equal(JSON.stringify(copy), edited, "Repeated import preserves local fields");
    const changed = item("reminder-one", { change: value => { value.nativeRecord.fields.modified += 5; value.nativeRecord.fields.notes = value.task.notiz = "Changed at source"; } });
    const changeReview = w.App.macOSBetaPrepareReminderImport(payload([changed]));
    equal([changeReview.newCount, changeReview.changedCount, changeReview.changedPreview[0].title], [0, 1, changed.title], "Changed source is explained without merging");
    await commit(b, changeReview); equal(JSON.stringify(copy), edited, "Changed native source cannot overwrite a local task");
    const foreignSource = source("second-list");
    await commit(b, w.App.macOSBetaPrepareReminderImport(payload([item("reminder-one", { origin: foreignSource })], foreignSource)));
    equal(t.daten().aufgaben.length, 7, "Same source identifier/title in another list remains an independent copy");
    const reused = item("foreign-record"); reused.identity = fixture.expectedIdentity;
    throws(() => w.App.macOSBetaPrepareReminderImport(payload([reused])), /identity/, "Foreign record cannot reuse an existing provenance identity");
    const movedSource = source(); movedSource.parentUID = "macos-account:" + Buffer.from("different-account").toString("base64");
    throws(() => w.App.macOSBetaPrepareReminderImport(payload([item("reminder-one", { origin: movedSource })], movedSource)), /identity/, "Same list/item identity under a different native account fails closed");
    t.daten().aufgaben.push({ ...clone(copy), id: "ambiguous-copy", uid: "ambiguous-uid" });
    throws(() => w.App.macOSBetaPrepareReminderImport(payload([item()])), /Multiple/, "Ambiguous local provenance cannot silently pick a winner"); t.daten().aufgaben.pop();
    const trash = t.daten().aufgaben.splice(5, 1)[0]; t.normalisiereAufgabenGraph(t.daten().aufgaben);
    t.daten().papierkorb.push({ id: "task-trash", art: "aufgabe", eintrag: clone(trash), name: "Copy", geloescht: Date.now() });
    const trashed = w.App.macOSBetaPrepareReminderImport(payload([item("second")]));
    equal([trashed.newCount, trashed.excluded[0].reasons[0]], [0, "local-reminder-copy-in-trash"], "Deliberately deleted task is not restored by repeated source reads");
    w.App.macOSBetaCancelReminderImport(trashed.token);
    equal(messages.filter(message => message.cmd === "sync" || message.cmd === "eds_speichern" || message.cmd === "baum_senden").length, 0, "Copy creates no native writes, sync or delegation");
    reopened = clone(t.daten());
  } finally { b.close(); }
}

{
  const b = await context(reopened), { w, t, messages } = b;
  try {
    const existing = JSON.stringify(t.daten().aufgaben.slice(0, 4)), annuals = JSON.stringify(t.daten().jahrestage), copy = t.daten().aufgaben[4];
    const review = w.App.macOSBetaPrepareReminderImport(payload([item(), item("second")]));
    equal([review.newCount, review.existingCount, review.excluded[0].reasons[0]], [0, 1, "local-reminder-copy-in-trash"], "Actual reopen preserves active and trash provenance"); await commit(b, review);
    const raw = clone(copy.nativeReminderRecord), meta = clone(copy.nativeReminderImport), times = clone(copy.icsRoundtrip);
    let form = await editTask(b, copy);
    equal([form.querySelector("#aufgabe-erinnern").checked, form.querySelector("#aufgabe-individuelle-erinnerung").value], [false, ""], "Actual editor opens with all notification controls off");
    changeInput(w, form.querySelector("textarea"), "Edited in the real task form\nwith <b>literal markup</b>");
    form.querySelector("select").value = "3"; form.querySelector("select").dispatchEvent(new w.Event("change", { bubbles: true }));
    await saveTask(b, form);
    equal([copy.prio, copy.notiz], [3, "Edited in the real task form\nwith <b>literal markup</b>"], "Actual text and priority edits stay local");
    equal(copy.icsRoundtrip, times, "Priority edit creates no stale raw PRIORITY or changes to source time semantics");
    equal([copy.nativeReminderRecord, copy.nativeReminderImport], [raw, meta], "Local edits preserve exact inert native evidence");
    equal(JSON.stringify(t.daten().aufgaben.slice(0, 4)), existing, "Actual editor and redraw preserve unrelated hierarchy");
    equal(JSON.stringify(t.daten().jahrestage), annuals, "Task editing cannot manufacture anniversary data");
    equal(t.normalisiere(clone(t.daten())).aufgaben[4], copy, "Edited task reopens without provenance or date loss");
    t.daten().einstellungen.erinnerung.an = true; b.at("2026-11-27T09:45:00Z"); t.pruefeErinnerungen();
    equal(messages.filter(message => message.cmd === "erinnerung_zeigen").length, 0, "Actual notification polling stays silent at copied due time");
    form = await editTask(b, copy);
    form.querySelector("#aufgabe-erinnern").checked = true;
    form.querySelector("#aufgabe-erinnern").dispatchEvent(new w.Event("change", { bubbles: true }));
    await saveTask(b, form);
    equal(w.MacBeta.taskAlarms(copy, fixture.displayTimeZone).map(value => new Date(value.at).toISOString()), ["2026-11-27T09:45:00.000Z"], "A later explicit user opt-in enables the normal due alarm");
    t.pruefeErinnerungen(); equal(messages.filter(message => message.cmd === "erinnerung_zeigen").length, 1, "Actual scheduler honors the explicitly saved local alarm");
    equal(copy.nativeReminderRecord.fields.alarms, [], "Opt-in never rewrites native original alarm evidence");
  } finally { b.close(); }
}

{
  const b = await context(), { w, t } = b;
  try {
    const cases = [
      ["undated", "", "", "", ""], ["due-date", "", "", "2026-11-27", ""],
      ["start-date", "2026-11-26", "", "", ""], ["dates", "2026-11-26", "", "2026-11-27", ""],
      ["same-date", "2026-11-27", "", "2026-11-27", ""],
      ["same-clock-next-day", "2026-11-27", "09:05", "2026-11-28", "09:05"],
      ["start-time", "2026-11-27", "09:05", "", ""], ["due-time", "", "", "2026-11-27", "10:45"],
      ["date-and-time", "2026-11-26", "", "2026-11-27", "10:45"],
      ["floating-gap", "", "", "2026-03-29", "02:30"], ["floating-fold", "", "", "2026-10-25", "02:30"]
    ].map(([id, ...dates]) => item(id, { change: value => setDates(value, ...dates) }));
    const anchored = item("anchored", { change: value => {
      setDates(value, "2026-11-27", "09:05", "2026-11-27", "10:45", "America/New_York");
      value.task.startZeit = "15:05"; value.task.faelligZeit = "16:45";
    } }); cases.push(anchored);
    for (let priority = 0; priority <= 9; priority++) cases.push(item("priority-" + priority, { change: value => {
      value.nativeRecord.fields.priority = priority; value.task.prio = priority >= 1 && priority <= 3 ? 1 : priority >= 7 ? 3 : 2;
    } }));
    for (const completedAt of [null, 1780001000.25]) cases.push(item("complete-" + completedAt, { change: value => {
      value.nativeRecord.fields.completed = value.task.erledigt = true; value.nativeRecord.fields.completionDate = completedAt;
    } }));
    const emptyNote = item("empty-note", { change: value => { value.task.notiz = ""; value.nativeRecord.fields.notes = null; value.nativeRecord.fields.hasNotes = false; } });
    cases.push(emptyNote);
    const review = w.App.macOSBetaPrepareReminderImport(payload(cases)); equal(review.newCount, cases.length, "Canonical-compatible date forms, all original priorities and completion states are retained");
    await commit(b, review);
    for (const proposed of cases) {
      const copy = t.daten().aufgaben.find(task => task.nativeReminderImport?.identifier === proposed.identifier), dates = [copy.startDatum, copy.startZeit, copy.faellig, copy.faelligZeit];
      const before = clone(copy.nativeReminderRecord), form = await editTask(b, copy);
      changeInput(w, form.querySelector("#aufgabe-titel"), copy.titel + " edited"); await saveTask(b, form);
      equal([copy.startDatum, copy.startZeit, copy.faellig, copy.faelligZeit], dates, "Actual plain title edit preserves dates: " + proposed.identifier);
      equal(copy.nativeReminderRecord, before, "Native evidence survives actual edit: " + proposed.identifier);
      equal(w.MacBeta.taskAlarms(copy, fixture.displayTimeZone), [], "Every compatible form remains passive: " + proposed.identifier);
    }
    const noteText = "\tCafe\u0301 👩‍💻\n<b>literal & text</b>\t";
    const unicode = item("unicode", { change: value => { value.task.notiz = value.nativeRecord.fields.notes = noteText; } });
    await t.wechsel("planer");
    await commit(b, w.App.macOSBetaPrepareReminderImport(payload([unicode])));
    const copy = t.daten().aufgaben.at(-1), form = await editTask(b, copy); equal(form.querySelector("textarea").value, noteText, "Tabs, LF, NFD and emoji survive the actual textarea exactly");
    await saveTask(b, form); equal(copy.notiz, noteText, "Literal note HTML never becomes markup or changes through editor save");
  } finally { b.close(); }
}

{
  const b = await context(), { w, t } = b;
  try {
    const losses = [
      ["title-trim", value => { value.task.titel = value.title = value.nativeRecord.fields.title = "  Title  "; }],
      ["title-empty", value => { value.task.titel = value.title = value.nativeRecord.fields.title = ""; }],
      ["title-line", value => { value.task.titel = value.title = value.nativeRecord.fields.title = "Title\nline"; }],
      ["note-crlf", value => { value.task.notiz = value.nativeRecord.fields.notes = "A\r\nB"; }],
      ["note-cr", value => { value.task.notiz = value.nativeRecord.fields.notes = "A\rB"; }],
      ["seconds", value => { value.task.icsRoundtrip[1] = "DUE:20261127T104537"; value.nativeRecord.fields.dueComponents.second = 37; }],
      ["raw-mismatch", value => { value.task.icsRoundtrip[1] = "DUE:20261127T114500"; }],
      ["duplicate-date", value => { value.task.icsRoundtrip[1] = value.task.icsRoundtrip[0]; }],
      ["invalid-date", value => { setDates(value, "", "", "2026-02-30", ""); }],
      ["raw-date-drift", value => { value.nativeRecord.fields.dueComponents.day = 28; }],
      ["raw-calendar-drift", value => { value.nativeRecord.fields.dueComponents.calendar = "buddhist"; }],
      ["raw-zone-drift", value => { value.nativeRecord.fields.dueComponents.timeZone = "UTC"; }],
      ["raw-partial-date", value => { delete value.nativeRecord.fields.dueComponents.year; }],
      ["reverse-dates", value => { setDates(value, "2026-11-28", "", "2026-11-27", ""); }],
      ["mixed-semantics", value => { setDates(value, "2026-11-27", "09:05", "2026-11-27", "10:45");
        value.nativeRecord.fields.dueComponents.timeZone = "Europe/Berlin"; value.task.icsRoundtrip[1] = "DUE;TZID=Europe/Berlin:20261127T104500"; }],
      ["instant-order", value => {
        setDates(value, "2026-10-25", "01:15", "2026-10-25", "00:45", "UTC");
        value.task.startZeit = "02:15"; value.task.faelligZeit = "02:45";
      }],
      ["time-no-date", value => { setDates(value, "", "", "", "10:45"); }],
      ["time-date", value => { setDates(value, "2026-11-27", "09:05", "2026-11-27", ""); }],
      ["equal-time", value => { setDates(value, "2026-11-27", "10:45", "2026-11-27", "10:45"); }],
      ["raw-priority", value => { value.task.icsRoundtrip = ["PRIORITY:0"]; }],
      ["fold", value => { setDates(value, "", "", "2026-10-25", "02:30", "Europe/Berlin"); }],
      ["gap", value => { setDates(value, "", "", "2026-03-29", "02:30", "Europe/Berlin"); }]
    ].map(([id, change]) => item(id, { change }));
    const before = JSON.stringify(t.daten()), review = w.App.macOSBetaPrepareReminderImport(payload(losses, source(), [{ identifier: "native-excluded", title: "Recurring source", reasons: ["native-reminder-recurrence-not-supported"] }]));
    equal([review.newCount, review.excluded.length], [0, losses.length + 1], "Every incompatible task remains a visible per-record exclusion");
    equal(review.excluded.slice(1).map(value => value.reasons[0]), losses.map(() => "canonical-reminder-content-would-change"), "No unannounced field coercion or incompatible editor range");
    equal((await commit(b, review)).count, 0, "All-excluded review adds nothing"); equal(JSON.stringify(t.daten()), before, "All exclusions leave the entire book exact");
    for (const change of [value => { value.identity = ["a".repeat(64)]; }, value => { value.nativeRecord.identifier = "different"; },
      value => { value.nativeRecord.failure = "read failure"; }, value => { value.nativeRecord.fields.hasAlarms = true; },
      value => { value.nativeRecord.fields.alarms = [{ relativeOffset: 0 }]; }, value => { value.nativeRecord.fields.hasRecurrenceRules = true; },
      value => { value.nativeRecord.fields.hierarchyAvailable = true; }, value => { value.nativeRecord.fields.completionDate = 1780001000; },
      value => { value.nativeRecord.fields.created = 253402300800; }, value => { value.task.sync = true; }, value => { value.task.erinnern = true; },
      value => { value.task.individuelleErinnerungTage = 1; }, value => { value.task.elternUid = "local-root-uid"; },
      value => { value.nativeRecord.fields.notes = "different"; }, value => { value.task.prio = 1; }, value => { value.task.erledigt = true; },
      value => { value.nativeRecord.fields.privateAPI = "unexpected"; }, value => { value.nativeRecord.fields.title = "\uD800"; },
      value => { value.nativeRecord.fields.metadataIncomplete = []; }, value => { value.nativeRecord.fields.hasNotes = false; },
      value => { value.task.titel = value.title = value.nativeRecord.fields.title = "\uDFFF"; }, value => { value.notices = []; },
      value => { value.task.icsRoundtrip.push("UID:source-identity"); }]) {
      const invalid = item("invalid"); change(invalid);
      throws(() => w.App.macOSBetaPrepareReminderImport(payload([invalid])), /Invalid/, "Malformed, foreign-field or active-alarm proposal refused");
    }
    throws(() => w.App.macOSBetaPrepareReminderImport(payload([item("duplicate"), item("duplicate")])), /ambiguous/, "Duplicate source selection refused");
    throws(() => w.App.macOSBetaPrepareReminderImport(payload([item("duplicate")], source(), [{ identifier: "duplicate", title: "Excluded", reasons: ["failure"] }])), /ambiguous/, "Included/excluded native identities cannot overlap");
    for (const change of [value => { value.calendarID = "different-list"; }, value => { value.parentUID = "macos-account:not-base64"; },
      value => { value.permission = "denied"; }, value => { value.readOnly = "false"; }]) {
      const invalid = source(); change(invalid); throws(() => w.App.macOSBetaPrepareReminderImport(payload([item()], invalid)), /Invalid/, "Source/list/account/permission shape validated");
    }
    throws(() => w.App.macOSBetaPrepareReminderImport(payload([item()], source(), [], "UTC")), /Invalid/, "Review cannot project in a different current display zone");
    const unicodeSource = source("Cafe\u0301 🪷"), unicodeReview = w.App.macOSBetaPrepareReminderImport(payload([item("unicode-source", { origin: unicodeSource })], unicodeSource));
    equal(unicodeReview.source, unicodeSource, "List identity uses exact UTF-8 bytes with no Unicode normalization"); w.App.macOSBetaCancelReminderImport(unicodeReview.token);
    const readOnly = source(); readOnly.readOnly = true;
    const readReview = w.App.macOSBetaPrepareReminderImport(payload([item("read-only", { origin: readOnly })], readOnly));
    equal(readReview.newCount, 1, "A readable native read-only list can create an independent local task"); w.App.macOSBetaCancelReminderImport(readReview.token);
    throws(() => w.App.macOSBetaPrepareReminderImport(payload(Array.from({ length: 101 }, (_, i) => item("many-" + i)))), /Invalid/, "100 selected-record limit enforced");
    const oversized = payload([item()]); oversized.extra = "x".repeat(16 * 1024 * 1024);
    throws(() => w.App.macOSBetaPrepareReminderImport(oversized), /byte limit/, "16MiB serialized proposal limit enforced before cloning");
    const hugeNote = item("huge-note", { change: value => { value.task.notiz = value.nativeRecord.fields.notes = "é".repeat(524289); } });
    throws(() => w.App.macOSBetaPrepareReminderImport(payload([hugeNote])), /Invalid/, "Note bound uses actual UTF-8 byte count");
    const hundred = w.App.macOSBetaPrepareReminderImport(payload(Array.from({ length: 100 }, (_, i) => item("allowed-" + i))));
    equal(hundred.newCount, 100, "Exactly 100 distinct source records preserve identical local titles without matching"); w.App.macOSBetaCancelReminderImport(hundred.token);
    t.daten().aufgaben[3].reihenfolge = 0;
    const unsafeGraph = JSON.stringify(t.daten());
    throws(() => w.App.macOSBetaPrepareReminderImport(payload([item("graph-loss")])), /hierarchy/, "Import refuses a pre-existing graph requiring rank mutation");
    equal(JSON.stringify(t.daten()), unsafeGraph, "Graph probe never repairs or mutates originals implicitly");
  } finally { b.close(); }
}

{
  const b = await context(), { w, t } = b;
  try {
    const stale = w.App.macOSBetaPrepareReminderImport(payload([item("stale")])); t.daten().futureRoot.userEdit = "after preview";
    await rejects(w.App.macOSBetaCommitReminderImport(stale.token), /stale/, "Any book edit invalidates the preview");
    const checkpoint = w.App.macOSBetaPrepareReminderImport(payload([item("checkpoint")]));
    await rejects(commit(b, checkpoint, { snapshot: false }), /recovery/i, "Failed checkpoint cannot append tasks");
    equal(t.daten().aufgaben.length, 4, "Checkpoint failures preserve existing tasks");
    const during = w.App.macOSBetaPrepareReminderImport(payload([item("during-checkpoint")]));
    const waiting = w.App.macOSBetaCommitReminderImport(during.token).then(() => null, error => error);
    t.daten().aufgaben[0].reihenfolge = 42;
    await b.pump(); ok(/stale/.test((await waiting).message), "Changed graph is rejected again inside the checkpoint callback");
    equal([t.daten().aufgaben.length, t.daten().aufgaben[0].reihenfolge], [4, 42], "Pending local order change is preserved without import or redraw");
    t.daten().aufgaben[0].reihenfolge = 0;
    const cancel = w.App.macOSBetaPrepareReminderImport(payload([item("cancel-checkpoint")]));
    const cancelled = w.App.macOSBetaCommitReminderImport(cancel.token).then(() => null, error => error);
    equal(w.App.macOSBetaCancelReminderImport(cancel.token).cancelled, true, "Matching checkpoint cancellation prevents append");
    const newer = w.App.macOSBetaPrepareReminderImport(payload([item("newer")]));
    await b.pump(); ok(/stale/.test((await cancelled).message), "Old cancelled checkpoint cannot commit");
    equal(w.App.macOSBetaCancelReminderImport(newer.token).cancelled, true, "Old checkpoint cannot discard a newer proposal");
    const saveFailed = w.App.macOSBetaPrepareReminderImport(payload([item("unsaved")]));
    await rejects(commit(b, saveFailed, { save: false }), /Imported tasks remain unsaved/, "Failed durable save is not reported as successful import");
    equal(t.daten().aufgaben.length, 5, "Unsaved appended copy remains visible for save retry");
    t.speichereJetzt(); await b.pump();
    const retry = w.App.macOSBetaPrepareReminderImport(payload([item("unsaved")]));
    equal([retry.newCount, retry.existingCount], [0, 1], "Successful save retry does not duplicate source copy"); w.App.macOSBetaCancelReminderImport(retry.token);
    const expired = w.App.macOSBetaPrepareReminderImport(payload([item("expired")])); b.at("2026-05-01T12:05:01Z");
    await rejects(w.App.macOSBetaCommitReminderImport(expired.token), /stale/, "Prepared review expires after five minutes");
    const zone = w.App.macOSBetaPrepareReminderImport(payload([item("zone")])); t.daten().einstellungen.regional.timeZone = "UTC";
    await rejects(w.App.macOSBetaCommitReminderImport(zone.token), /stale/, "Display-zone change invalidates the review");
    t.daten().einstellungen.regional.timeZone = fixture.displayTimeZone;
    const restoring = w.App.macOSBetaPrepareReminderImport(payload([item("restore")])); w.MacBeta.validateRestore(JSON.stringify(initial));
    await rejects(w.App.macOSBetaCommitReminderImport(restoring.token), /stale/, "Restore fence invalidates the prepared review");
    throws(() => w.App.macOSBetaPrepareReminderImport(payload([item("blocked")])), /not available/, "Restore fence blocks new preparation");
  } finally { b.close(); }
}

for (const stage of ["prepared", "checkpoint", "saving"]) {
  const b = await context(), { w, t, messages } = b;
  try {
    const old = w.App.macOSBetaPrepareReminderImport(payload([item("old-generation")]));
    const pending = stage === "prepared" ? null : w.App.macOSBetaCommitReminderImport(old.token).then(() => null, error => error);
    if (stage === "saving") await b.pump({ ackSaves: false });
    w.MacBeta.receive("init", { daten: clone(initial), neu: false, regional: { language: "en", timeZone: fixture.displayTimeZone } });
    if (stage === "prepared") {
      const current = w.App.macOSBetaPrepareReminderImport(payload([item("new-generation")]));
      await rejects(w.App.macOSBetaCommitReminderImport(old.token), /Invalid/, "Old token cannot consume replacement document review");
      equal(w.App.macOSBetaCancelReminderImport(current.token).cancelled, true, "Idle obsolete proposal releases a newly initialized document");
    } else {
      throws(() => w.App.macOSBetaPrepareReminderImport(payload([item("wait")])), /already/, "In-flight review stays owned across initialization: " + stage);
      w.App.macOSBetaStartReminderImport(); equal(messages.filter(message => message.cmd === "macos_erinnerungen_importieren").length, 0, "In-flight review cannot start another native selection");
      await b.pump(); ok(/stale|document changed/i.test((await pending).message), "Old generation cannot report success: " + stage);
      equal(t.daten().aufgaben.length, 4, "Replacement document never receives previous-generation candidates");
    }
  } finally { b.close(); }
}

{
  const b = await context(), { w, t } = b;
  const appearance = w.MagnolieAppearance;
  try {
    t.speichereJetzt(); await b.pump();
    const original = JSON.stringify(t.daten().aufgaben), review = w.App.macOSBetaPrepareReminderImport(payload([item("render-failure")]));
    try {
      w.MagnolieAppearance = { ...appearance, update() { throw new Error("Synthetic renderer failure after append"); } };
      await rejects(commit(b, review), /Task copies were added, but saving was not confirmed\..*Synthetic renderer failure after append/,
        "Actual public renderer exception explains append and unconfirmed persistence without claiming rollback");
    } finally { w.MagnolieAppearance = appearance; }
    equal(t.daten().aufgaben.length, 5, "Already appended task remains available after rendering failure");
    equal(JSON.stringify(t.daten().aufgaben.slice(0, 4)), original, "Renderer failure never changes existing task records");
    equal(t.daten().aufgaben.at(-1).nativeReminderImport.identifier, "render-failure", "Failed rendering does not discard native provenance");
    t.speichereJetzt(); await b.pump();
    const retry = w.App.macOSBetaPrepareReminderImport(payload([item("render-failure")]));
    equal([retry.newCount, retry.existingCount], [0, 1], "Real save retry preserves the appended copy and prevents duplicate reimport");
    w.App.macOSBetaCancelReminderImport(retry.token);
  } finally { w.MagnolieAppearance = appearance; b.close(); }
}

for (const kind of ["task", "note", "modal"]) for (const stage of ["before-prepare", "before-commit", "during-checkpoint"]) {
  const b = await context(), { w, t } = b;
  try {
    if (kind === "task") await editTask(b, t.daten().aufgaben[0]);
    if (kind === "note") { t.zustand().notizen.notizbuchId = "local-book"; t.zustand().notizen.auswahlId = "local-note"; await t.wechsel("notizen"); await b.pump(); }
    let review, pending;
    if (stage !== "before-prepare") review = w.App.macOSBetaPrepareReminderImport(payload([item("draft-race")]));
    if (stage === "during-checkpoint") pending = w.App.macOSBetaCommitReminderImport(review.token).then(() => null, error => error);
    let field;
    if (kind === "task") { field = w.document.querySelector("#aufgabe-titel"); changeInput(w, field, "Pending task draft"); }
    if (kind === "note") {
      field = w.document.querySelector("#notiz-text"); field.textContent = "Pending note fragment"; field.dispatchEvent(new w.Event("input", { bubbles: true }));
      equal(t.daten().notizen[0].text, "Original note", "Real pending note fragment is still outside DATEN");
    }
    if (kind === "modal") { t.oeffneTerminBlatt(null, "2026-05-10"); field = w.document.querySelector("#tb-titel"); changeInput(w, field, "Pending appointment draft"); }
    const displayed = kind === "note" ? field.textContent : field.value;
    if (stage === "before-prepare") throws(() => w.App.macOSBetaPrepareReminderImport(payload([item("draft-race")])), /editor/, "Open draft blocks preparation: " + kind);
    else if (stage === "before-commit") await rejects(w.App.macOSBetaCommitReminderImport(review.token), /stale/, "New draft blocks commit: " + kind);
    else { await b.pump(); ok(/stale/.test((await pending).message), "Draft race is rechecked inside checkpoint: " + kind); }
    equal([field.isConnected, kind === "note" ? field.textContent : field.value, t.daten().aufgaben.length], [true, displayed, 4], "Actual editor DOM and values survive rejection: " + kind + "/" + stage);
    if (kind === "note") { t.sichereNotizSnapshot(); equal(t.daten().notizen[0].text, displayed, "Pending note callback still saves its content"); }
  } finally { b.close(); }
}

{
  const b = await context(), { w, t, messages } = b;
  try {
    t.oeffneEinstellungen(); w.document.querySelector("#einst-tab-sync").click();
    const request = messages.filter(message => message.cmd === "eds_status" && message.requestId).at(-1);
    const button = () => w.document.querySelector("#macos-system-reminder-import"), starts = () => messages.filter(message => message.cmd === "macos_erinnerungen_importieren");
    equal(button().disabled, true, "Actual System Sources button waits for its own source response");
    button().click(); equal(starts().length, 0, "Pending source request prevents native selection");
    w.MacBeta.receive("edsStatus", { requestId: "foreign", kalender: [], adressbuecher: [] }); equal(button().disabled, true, "Foreign source reply does not enable the button");
    w.MacBeta.receive("edsStatus", { requestId: request.requestId, kalender: [], adressbuecher: [] }); equal(button().disabled, false, "Matching source reply enables reminder selection");
    t.daten().futureRoot.buttonEdit = true; button().click();
    equal(starts().length, 0, "Native selection waits for actual pre-picker save ACK");
    equal(w.document.querySelector("#einstellungen-schleier").classList.contains("verborgen"), false, "Settings remain while save is pending");
    await b.pump(); equal(starts(), [{ cmd: "macos_erinnerungen_importieren" }], "Actual button emits a parameterless native command");
    equal(w.document.querySelector("#einstellungen-schleier").classList.contains("verborgen"), true, "Canonical settings close clears only its own modal");
    await commit(b, w.App.macOSBetaPrepareReminderImport(payload([item("from-button")])));
    equal(t.daten().aufgaben.at(-1).nativeReminderImport.identifier, "from-button", "Actual settings button completes full reviewed checkpoint/save flow");
    t.oeffneTerminBlatt(null, "2026-05-10"); const title = w.document.querySelector("#tb-titel");
    w.App.macOSBetaStartReminderImport(); await b.pump(); equal([title.isConnected, starts().length], [true, 1], "Unrelated modal is retained and prevents new native selection");
  } finally { b.close(); }
}

for (const stage of ["before-start", "during-save"]) for (const fieldID of ["briefkasten-url", "briefkasten-kennwort"]) {
  const b = await context(), { w, t, messages } = b;
  try {
    t.oeffneEinstellungen(); w.document.querySelector("#einst-tab-sync").click();
    const account = { kontoArt: "nextcloud", davAktiv: false, briefkastenAktiv: false, url: "https://cloud.example.test", benutzer: "synthetic-user",
      kennwortVorhanden: false, revision: "1".repeat(64), zustand: "nicht_eingerichtet", fehler: "", fehlerCode: "none" };
    w.MacBeta.receive("baumBriefkastenStatus", account);
    const request = messages.filter(message => message.cmd === "eds_status" && message.requestId).at(-1);
    w.MacBeta.receive("edsStatus", { requestId: request.requestId, kalender: [], adressbuecher: [] });
    const button = () => w.document.querySelector("#macos-system-reminder-import"), visible = () => !w.document.querySelector("#einstellungen-schleier").classList.contains("verborgen");
    const starts = () => messages.filter(message => message.cmd === "macos_erinnerungen_importieren");
    const url = w.document.querySelector("#briefkasten-url"), password = w.document.querySelector("#briefkasten-kennwort");
    equal([url.disabled, password.disabled, button().disabled], [false, false, false], "Actual DAV inputs require and accept a valid account revision");
    t.daten().futureRoot.accountDraftRace = stage;
    const before = JSON.stringify(t.daten()), saves = messages.filter(message => message.cmd === "speichern").length;
    if (stage === "during-save") button().click();
    const field = w.document.getElementById(fieldID), value = fieldID === "briefkasten-url" ? "https://unsaved.example.test/dav" : "public-synthetic-unsaved-password";
    changeInput(w, field, value);
    if (stage === "before-start") { button().click(); equal(messages.filter(message => message.cmd === "speichern").length, saves, "Pending account input blocks before document save"); }
    await b.pump();
    equal([starts().length, visible(), field.isConnected, field.value, JSON.stringify(t.daten())], [0, true, true, value, before], "Reminder entry preserves account input/model: " + fieldID + "/" + stage);
    equal([url.value, password.value], fieldID === "briefkasten-url" ? [value, ""] : [account.url, value], "Password-only draft does not depend on the DAV changed listener");
    equal(messages.filter(message => message.cmd === "baum_briefkasten_speichern").length, 0, "Import never saves account drafts");
    equal(w.document.querySelector("#zettel").textContent, "Save or discard the account changes before importing.", "Pending account draft is explained");
    if (stage === "before-start" && fieldID === "briefkasten-kennwort") {
      t.schliesseEinstellungen(); w.App.macOSBetaStartReminderImport(); await b.pump(); equal(starts(), [{ cmd: "macos_erinnerungen_importieren" }], "Consciously closed stale hidden password does not block menu entry");
    }
  } finally { b.close(); }
}

for (const kind of ["task", "note"]) {
  const b = await context(), { w, t, messages } = b;
  try {
    let field;
    if (kind === "task") { await editTask(b, t.daten().aufgaben[0]); field = w.document.querySelector("#aufgabe-titel"); }
    else { t.zustand().notizen.notizbuchId = "local-book"; t.zustand().notizen.auswahlId = "local-note"; await t.wechsel("notizen"); field = w.document.querySelector("#notiz-text"); }
    t.daten().futureRoot.startEditorRace = kind; const before = JSON.stringify(t.daten());
    w.App.macOSBetaStartReminderImport();
    if (kind === "task") changeInput(w, field, "New task input while saving");
    else { field.textContent = "New note input while saving"; field.dispatchEvent(new w.Event("input", { bubbles: true })); }
    await b.pump();
    if (kind === "task") {
      equal(messages.filter(message => message.cmd === "macos_erinnerungen_importieren").length, 0, "Task draft created while awaiting start save blocks native picker");
      equal([field.isConnected, field.value, JSON.stringify(t.daten())], [true, "New task input while saving", before], "New task form survives start-save race unchanged");
    } else {
      // The canonical durable-save loop deliberately flushes a newly pending
      // Notes fragment and waits for its additional save before continuing.
      equal(messages.filter(message => message.cmd === "macos_erinnerungen_importieren").length, 1, "Canonical save loop can safely finish the newly queued Notes fragment before native selection");
      equal([field.isConnected, field.textContent, t.daten().notizen[0].text], [true, "New note input while saving", "New note input while saving"], "New Notes fragment is retained in DOM and saved data");
      equal(JSON.parse(messages.filter(message => message.cmd === "speichern").at(-1).text).notizen[0].text, "New note input while saving", "Actual last acknowledged save contains the new Notes fragment");
    }
  } finally { b.close(); }
}

{
  const b = await context(), { w, t, messages } = b;
  try {
    t.oeffneEinstellungen(); t.daten().futureRoot.pendingSave = true;
    w.App.macOSBetaStartReminderImport(); await b.pump({ save: false });
    equal(messages.filter(message => message.cmd === "macos_erinnerungen_importieren").length, 0, "Failed pre-picker save cannot start native read");
    equal(w.document.querySelector("#einstellungen-schleier").classList.contains("verborgen"), false, "Failed save keeps the canonical settings dialog");
  } finally { b.close(); }
}

{
  const b = await context(), { w, t } = b;
  try {
    // Supplemental strings for this new Mac flow only; no claim of a complete
    // shared gettext-catalog or native AppKit locale run.
    w.MagnolieI18n.setLocale("de");
    t.oeffneEinstellungen(); w.document.querySelector("#einst-tab-sync").click();
    equal(w.document.querySelector("#macos-system-reminder-import").textContent, "macOS-Erinnerungen übernehmen", "Actual reminder source button uses the supplementary German text");
    t.schliesseEinstellungen();
    const review = w.App.macOSBetaPrepareReminderImport(payload([item("de-copy")]));
    ok(review.preview[0].text.includes("Anzeigezeitzone: Europe/Berlin"), "German preview distinguishes the display zone");
    ok(review.preview[0].text.includes("Uhrzeit ohne Zeitzonenbindung; die Quelle weist ihr keine Zeitzone zu."), "German preview explains floating time honestly");
    ok(review.preview[0].text.includes("Diese Übernahme aktiviert keine Aufgabenbenachrichtigung."), "German preview explains passive task alarms");
    w.App.macOSBetaCancelReminderImport(review.token);
  } finally { b.close(); }
}

{
  const b = await context(), { t, messages } = b;
  try {
    const raw = ["BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER;VALUE=DATE-TIME:20261127T103017Z", "END:VALARM"];
    const book = t.daten();
    book.termine = t.normalisiere({ termine: [
      { id: "event-absolute", titel: "Exact event", datum: "2027-06-10", zeit: "09:00",
        icsRoundtrip: ["RRULE:FREQ=DAILY", ...raw, ...raw] },
      { id: "event-cancelled", titel: "Cancelled event", datum: "2027-06-10", zeit: "09:00",
        icsRoundtrip: ["STATUS:CANCELLED", ...raw] },
    ] }).termine;
    book.aufgaben = [
      { id: "task-absolute", titel: "Exact task", icsRoundtrip: ["CLASS:PUBLIC", ...raw] },
      { id: "task-done", titel: "Done task", erledigt: true, icsRoundtrip: raw },
      { id: "task-private", titel: "Confidential task", icsRoundtrip: ["CLASS:CONFIDENTIAL", ...raw] },
      { id: "task-legacy", titel: "Legacy private title", icsRoundtrip: raw },
    ];
    const notifications = () => messages.filter(message => message.cmd === "erinnerung_zeigen");
    book.einstellungen.erinnerung.an = true;
    b.at("2026-11-27T10:30:16Z"); t.pruefeErinnerungen();
    equal(notifications().length, 0, "Absolute reminders do not fire a second early");
    b.at("2026-11-27T10:30:17Z"); book.einstellungen.erinnerung.an = false; t.pruefeErinnerungen();
    equal(notifications().length, 0, "Absolute reminders respect the global opt-out");
    book.einstellungen.erinnerung.an = true;
    t.pruefeErinnerungen(); t.pruefeErinnerungen();
    equal(notifications().map(message => message.rumpf), ["Exact event", "Exact task", "Task reminder"],
      "Actual polling sends one notification per absolute trigger via the existing bridge");
  } finally { b.close(); }
}

{
  const b = await context(), { t, messages } = b;
  try {
    const raw = ["BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER;VALUE=DATE-TIME:20300510T103000Z", "END:VALARM"];
    const book = t.daten();
    book.einstellungen.regional.timeZone = "UTC";
    Object.assign(book.einstellungen.erinnerung, { an: true, vorlauf: 0 });
    book.termine = t.normalisiere({ termine: [
      { id: "coincident-event", titel: "Coincident event", datum: "2030-05-10", zeit: "10:30", icsRoundtrip: raw },
      { id: "other-event", titel: "Other event", datum: "2030-05-10", zeit: "10:30" },
    ] }).termine;
    book.aufgaben = [];
    b.at("2030-05-10T10:29:59Z"); t.pruefeErinnerungen();
    equal(messages.filter(message => message.cmd === "erinnerung_zeigen").length, 0, "No coincident notification before the trigger");
    b.at("2030-05-10T10:30:00Z"); t.pruefeErinnerungen(); t.pruefeErinnerungen();
    equal(messages.filter(message => message.cmd === "erinnerung_zeigen").length, 2,
      "Same item and instant must notify once; a distinct item at that instant remains independent");
  } finally { b.close(); }
}

for (const lead of [0, 1]) {
  const b = await context(), { t, messages } = b;
  try {
    const day = lead ? "2030-05-10" : "2030-05-11";
    const stamp = day.replaceAll("-", "");
    const putAlarm = second => ["CLASS:PUBLIC", "DUE:20300511T103000Z", "BEGIN:VALARM",
      "ACTION:DISPLAY", `TRIGGER;VALUE=DATE-TIME:${stamp}T1030${second}Z`, "END:VALARM"];
    const task = { id: "coincident-task", titel: "Coincident task", faellig: "2030-05-11", faelligZeit: "10:30",
      erinnern: !lead, individuelleErinnerungTage: lead, icsAnzeigeZeitzone: "UTC", icsRoundtrip: putAlarm("00") };
    const book = t.daten();
    book.termine = []; book.aufgaben = [task];
    book.einstellungen.regional.timeZone = "UTC"; book.einstellungen.erinnerung.an = true;
    const count = () => messages.filter(message => message.cmd === "erinnerung_zeigen").length;
    b.at(`${day}T10:30:00Z`); t.pruefeErinnerungen();
    equal(count(), 1, `Coincident absolute and regular task alarms notify once for lead ${lead}`);
    task.icsRoundtrip = task.icsRoundtrip.slice(0, 2);
    t.pruefeErinnerungen(); t.pruefeErinnerungen();
    equal(count(), 1, `Removing the absolute alarm keeps the same receipt for lead ${lead}`);
    task.icsRoundtrip = putAlarm("17");
    b.at(`${day}T10:30:17Z`); t.pruefeErinnerungen();
    equal(count(), 2, `A different trigger second still notifies for lead ${lead}`);
  } finally { b.close(); }
}

console.log(`Mac reminder projection: ${checks} UI checks; shared synthetic reader/Core fixture and transport, not EventKit or macOS evidence.`);
