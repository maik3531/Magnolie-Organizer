import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { boot, tick } from "./ui_harness.mjs";

const clone = value => JSON.parse(JSON.stringify(value));
const digest = value => createHash("sha256").update(JSON.stringify(value)).digest("hex");
let checks = 0;
const equal = (actual, expected, label) => { assert.deepEqual(clone(actual), clone(expected), label); checks++; };
const throws = (action, pattern, label) => { assert.throws(action, pattern, label); checks++; };
const rejects = async (action, pattern, label) => { await assert.rejects(action, pattern, label); checks++; };
const initial = { termine: [], aufgaben: [], kontakte: [], notizen: [],
  futureRoot: { retained: ["opaque", { value: 17 }] }, einstellungen: { allgemein: { handbuchHinweisGezeigt: true } } };
const source = (name = "Calendar A") => ({ uid: "macos-events:" + Buffer.from(name).toString("base64"),
  title: name, parentUID: "native-account", parentTitle: "iCloud", parentType: "calDAV", nativeType: "calDAV" });
function draft(identifier, { account = source(), title = "Same title", start = "2026-05-10T10:00:17Z",
  end = "2026-05-10T11:00:19Z", allDay = false, zone = "UTC", date = "2026-05-10", time = "10:00",
  endDate = "", endTime = "11:00", location = "Office" } = {}) {
  const identity = digest([account.uid, identifier]);
  const fields = { title, notes: "Source note", location, start: Date.parse(start) / 1000, end: Date.parse(end) / 1000,
    allDay, timeZone: zone, recurring: false, isDetached: false, recurrenceRules: [], alarms: [], attendeeCount: 0, hasOrganizer: false,
    metadataIncomplete: ["provider-opaque-fields"] };
  const revision = digest(fields), raw = value => value.replace(/[-:]/g, "");
  return { uid: "mac-native-copy:" + identity, titel: title, notiz: fields.notes, ort: location,
    datum: date, endDatum: endDate, zeit: allDay ? "" : time, endZeit: allDay ? "" : endTime,
    icsAnzeigeZeitzone: zone, wiederholung: { art: "none" }, sync: false, syncKalenderUid: "", syncQuellen: {},
    icsQuelleId: "", icsQuelleName: "", nativeSourceReadOnly: false, standardErinnerung: false, individuelleErinnerungTage: 0, alarme: [],
    icsRoundtrip: allDay ? ["DTSTART;VALUE=DATE:" + start.slice(0, 10).replace(/-/g, ""), "DTEND;VALUE=DATE:" + end.slice(0, 10).replace(/-/g, "")]
      : ["DTSTART:" + raw(start), "DTEND:" + raw(end)],
    nativeCalendarImport: { version: 1, identity, sourceUID: account.uid, identifier, sourceTitle: account.title, parentUID: account.parentUID, revision },
    nativeSystemRecord: { kind: "events", sourceUID: account.uid, identifier, revision, revisionCoverage: "serialized-fields-only", fields, occurrenceDate: null } };
}
// Manually source-shaped synthetic data, NOT output from executing Swift. These
// keys follow ICalendarImport.componentRecord/decode and the final additions in
// SystemCalendarImport.appointment. The fixture deliberately includes every
// property emitted for the supported single-event path, plus full public native
// fields, so strict candidate comparison is tested against more than a minimal DTO.
function sourceShapeDraft(identifier, options = {}) {
  const value = draft(identifier, options), fields = value.nativeSystemRecord.fields;
  Object.assign(fields, { externalIdentifier: "external-" + identifier,
    url: options.url ?? null, occurrenceDate: null, modified: null, created: null,
    status: options.tentative ? 2 : 1, availability: options.available ? 1 : 0 });
  const revision = digest(fields);
  value.nativeCalendarImport.revision = revision; value.nativeSystemRecord.revision = revision;
  const zero = fields.start === fields.end;
  Object.assign(value, { kategorien: "", akzentFarbe: "", vertraulich: false, vorlaeufig: !!options.tentative,
    kostenstelle: "", kunde: "", wiederholung: { art: "none", bis: "" }, icsKomplex: false, icsSerienUid: "",
    icsZusatzDaten: [], icsZusatzTermine: [], icsEndeFehlt: false, icsNullDauer: zero,
    icsSequence: 0, icsAenderungszeitFehlt: true, geaendert: 0, ganztag: fields.allDay });
  // The native codec omits display endTime if it equals the same-day startTime.
  if (zero) value.endZeit = "";
  const escape = text => text.replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/,/g, "\\,").replace(/;/g, "\\;");
  if (value.ort) value.icsRoundtrip.push("LOCATION:" + escape(value.ort));
  if (fields.url) value.icsRoundtrip.push("URL:" + fields.url);
  value.icsRoundtrip.push(options.available ? "TRANSP:TRANSPARENT" : "TRANSP:OPAQUE");
  // The codec represents STATUS using vorlaeufig. Keeping a second mutable raw
  // STATUS would contradict later local edits; original status stays in fields.
  return value;
}
function payload(appointments, account = source(), excluded = []) {
  return { version: 1, source: account, window: { start: Date.parse("2026-01-01T00:00:00Z") / 1000, end: Date.parse("2027-01-01T00:00:00Z") / 1000 },
    appointments, excluded, snapshotRevision: digest(appointments) };
}
async function context() {
  const b = await boot(process.argv[2], Date.parse("2026-05-01T12:00:00Z")), seen = new Set();
  const { w, t, messages } = b;
  w.MacBeta.receive("init", { daten: clone(initial), neu: false, regional: { language: "en", timeZone: "UTC" } });
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
  await pump();
  return { ...b, pump };
}
async function commit(b, review, options) {
  const result = b.w.App.macOSBetaCommitCalendarImport(review.token);
  // Attach a rejection handler before pumping synchronous synthetic replies.
  const settled = result.then(value => ({ value }), error => ({ error }));
  await b.pump(options);
  const outcome = await settled;
  if (outcome.error) throw outcome.error;
  return outcome.value;
}

function openSourceSettings(b, reply = true) {
  const { w, t, messages } = b;
  t.oeffneEinstellungen(); w.document.querySelector("#einst-tab-sync").click();
  const request = messages.filter(message => message.cmd === "eds_status" && message.requestId).at(-1);
  if (reply) w.MacBeta.receive("edsStatus", { requestId: request.requestId, kalender: [], adressbuecher: [] });
  return { request, button: () => w.document.querySelector("#macos-system-calendar-import"),
    visible: () => !w.document.querySelector("#einstellungen-schleier").classList.contains("verborgen"),
    starts: () => messages.filter(message => message.cmd === "macos_kalender_importieren") };
}

{
  // #773 exercises the actual registered Settings modal, not just its hidden
  // page builder. Native payloads/ACKs remain explicitly synthetic.
  const b = await context(), { w, t, messages } = b;
  try {
    const entry = openSourceSettings(b, false);
    equal(entry.button().disabled, true, "Real calendar source button waits for outstanding EDS request");
    entry.button().click(); equal(entry.starts(), [], "Pending EDS request prevents native calendar picker start");
    w.MacBeta.receive("edsStatus", { requestId: "stale", kalender: [], adressbuecher: [] });
    equal(entry.button().disabled, true, "Foreign EDS reply cannot release the calendar source button");
    w.MacBeta.receive("edsStatus", { requestId: entry.request.requestId, kalender: [], adressbuecher: [] });
    equal(entry.button().disabled, false, "Correlated EDS reply releases the real calendar source button");
    t.daten().futureRoot.sourceButtonEdit = "save before picker";
    entry.button().click();
    equal([entry.starts().length, entry.visible()], [0, true], "Settings and picker wait for the ordinary document save ACK");
    const startSave = messages.filter(message => message.cmd === "speichern").at(-1);
    equal(JSON.parse(startSave.text).futureRoot.sourceButtonEdit, "save before picker", "Actual start save contains the pending document change");
    await b.pump();
    equal(entry.starts(), [{ cmd: "macos_kalender_importieren" }], "Actual calendar button sends only the parameterless native command");
    equal(entry.visible(), false, "Canonical close removes the Settings parent modal before native selection");
    const native = sourceShapeDraft("from-settings", { title: "Calendar copied from Settings", tentative: true,
      location: "Room A, West; Floor 2", url: "https://example.invalid/calendar-copy" });
    const before = JSON.stringify(t.daten()), review = w.App.macOSBetaPrepareCalendarImport(payload([native]));
    equal([review.newCount, review.existingCount, review.changedCount, review.excluded.length], [1, 0, 0, 0], "Full source-shaped DTO can prepare after the real Settings entry");
    equal(JSON.stringify(t.daten()), before, "Button-based preparation remains model-read-only");
    let finished = false;
    const pending = w.App.macOSBetaCommitCalendarImport(review.token).then(value => { finished = true; return { value }; }, error => ({ error }));
    await b.pump({ ackSnapshots: false });
    equal(messages.filter(message => message.cmd === "mutations_snapshot").at(-1).reason, "pre-system-calendar-import", "Button-based copy uses the existing recovery checkpoint");
    equal([finished, JSON.stringify(t.daten())], [false, before], "No mutation while the native checkpoint remains unacknowledged");
    await b.pump({ ackSaves: false });
    equal([finished, t.daten().termine.length], [false, 1], "Checkpoint allows append but cannot report durable copy success");
    await b.pump(); const outcome = await pending;
    if (outcome.error) throw outcome.error;
    equal([finished, outcome.value.count], [true, 1], "Actual source-button flow finishes only after final save ACK");
    const copied = t.daten().termine[0];
    equal([copied.nativeCalendarImport, copied.nativeSystemRecord, copied.icsRoundtrip],
      [native.nativeCalendarImport, native.nativeSystemRecord, native.icsRoundtrip], "Full provenance and precise ICS survive button-to-save flow");
    equal(t.daten().futureRoot.sourceButtonEdit, "save before picker", "Unrelated pending change survives the whole source-button flow");
  } finally { b.close(); }
}

for (const stage of ["before-start", "during-save"]) {
  const b = await context(), { w, t } = b;
  try {
    const entry = openSourceSettings(b);
    t.daten().futureRoot.modalRace = stage;
    if (stage === "during-save") entry.button().click();
    t.oeffneTerminBlatt(null, "2026-05-10");
    const editor = w.document.querySelector("#tb-titel");
    if (stage === "before-start") w.App.macOSBetaStartCalendarImport();
    await b.pump();
    equal([entry.starts().length, entry.visible(), editor.isConnected], [0, true, true], "Additional modal prevents close/start and remains intact: " + stage);
    equal([t.daten().termine.length, t.daten().futureRoot.modalRace], [0, stage], "Additional modal guard preserves the existing document: " + stage);
  } finally { b.close(); }
}

{
  const b = await context(), { w, t } = b;
  try {
    t.oeffneTerminBlatt(null, "2026-05-10");
    const title = w.document.querySelector("#tb-titel");
    title.value = "Keep this unsaved local appointment"; title.dispatchEvent(new w.Event("input", { bubbles: true }));
    const entry = openSourceSettings(b);
    entry.button().click();
    const cancel = [...w.document.querySelectorAll("#aenderungen-schleier button")].find(button => button.textContent === "Cancel");
    assert.ok(cancel, "Real canonical navigation guard asks about the pending editor draft"); checks++;
    equal([entry.starts().length, entry.visible(), title.value], [0, true, "Keep this unsaved local appointment"], "Start waits for the actual editor decision");
    cancel.click(); await b.pump();
    equal([entry.starts().length, entry.visible(), title.isConnected, title.value, t.daten().termine.length],
      [0, true, true, "Keep this unsaved local appointment", 0], "Cancelling the navigation guard preserves both dialogs and the exact editor draft");
  } finally { b.close(); }
}

{
  const b = await context(), { t } = b;
  try {
    const entry = openSourceSettings(b);
    t.daten().futureRoot.unsavedStart = "Keep this change after storage failure";
    const before = JSON.stringify(t.daten());
    entry.button().click(); await b.pump({ save: false });
    equal([entry.starts().length, entry.visible(), JSON.stringify(t.daten())], [0, true, before], "Failed start save keeps Settings and all pending data without opening a picker");
    t.speichereJetzt(); await b.pump();
    entry.button().click(); await b.pump();
    equal([entry.starts(), entry.visible(), JSON.stringify(t.daten())], [[{ cmd: "macos_kalender_importieren" }], false, before],
      "Explicit successful save retry permits a fresh start without losing pending changes");
  } finally { b.close(); }
}

for (const stage of ["before-start", "during-save"]) for (const fieldID of ["briefkasten-url", "briefkasten-kennwort"]) {
  const b = await context(), { w, t, messages } = b;
  try {
    const entry = openSourceSettings(b);
    const account = { kontoArt: "nextcloud", davAktiv: false, briefkastenAktiv: false,
      url: "https://cloud.example.test", benutzer: "synthetic-user", kennwortVorhanden: false,
      revision: "1".repeat(64), zustand: "nicht_eingerichtet", fehler: "", fehlerCode: "none" };
    w.MacBeta.receive("baumBriefkastenStatus", account);
    const request = messages.filter(message => message.cmd === "eds_status" && message.requestId).at(-1);
    w.MacBeta.receive("edsStatus", { requestId: request.requestId, kalender: [], adressbuecher: [] });
    const url = w.document.querySelector("#briefkasten-url"), password = w.document.querySelector("#briefkasten-kennwort");
    equal([url.disabled, password.disabled, entry.button().disabled], [false, false, false], "Actual DAV fields are enabled only with a valid native revision");
    t.daten().futureRoot.accountDraftRace = stage;
    const before = JSON.stringify(t.daten()), savesBefore = messages.filter(message => message.cmd === "speichern").length;
    if (stage === "during-save") entry.button().click();
    const field = w.document.getElementById(fieldID), value = fieldID === "briefkasten-url"
      ? "https://unsaved.example.test/dav" : "public-synthetic-unsaved-app-password";
    field.value = value; field.dispatchEvent(new w.Event("input", { bubbles: true }));
    if (stage === "before-start") {
      entry.button().click();
      equal(messages.filter(message => message.cmd === "speichern").length, savesBefore, "Existing account draft blocks navigation/save before any document write");
    }
    await b.pump();
    equal([entry.starts().length, entry.visible(), field.isConnected, field.value, JSON.stringify(t.daten())], [0, true, true, value, before],
      "Uncommitted account field is retained without close or picker: " + fieldID + "/" + stage);
    equal([url.value, password.value], fieldID === "briefkasten-url" ? [value, ""] : [account.url, value],
      "Password-only case has no URL edit or account changed-listener side effect");
    equal(messages.filter(message => message.cmd === "baum_briefkasten_speichern").length, 0, "Calendar start cannot save or discard the separate native account draft");
    equal(w.document.querySelector("#zettel").textContent, "Save or discard the account changes before importing.", "Blocked account draft receives an actionable notice");
    if (stage === "before-start" && fieldID === "briefkasten-kennwort") {
      t.schliesseEinstellungen();
      equal([entry.visible(), field.value], [false, value], "Explicit user close can leave the password value in hidden DOM");
      w.App.macOSBetaStartCalendarImport(); await b.pump();
      equal(entry.starts(), [{ cmd: "macos_kalender_importieren" }], "Hidden DOM after conscious close does not falsely block a fresh native-menu start");
    }
  } finally { b.close(); }
}

{
  // The native read panel is not a DOM modal. A user can open a fresh editor
  // while it is reading; its unsaved fields are not yet part of DATEN.
  for (const stage of ["before-prepare", "before-commit", "during-checkpoint"]) {
    const b = await context(), { w, t } = b;
    try {
      let review = null, pending = null;
      if (stage !== "before-prepare") review = w.App.macOSBetaPrepareCalendarImport(payload([draft("editor-race")]));
      if (stage === "during-checkpoint") pending = w.App.macOSBetaCommitCalendarImport(review.token).then(() => null, error => error);
      t.oeffneTerminBlatt(null, "2026-05-10");
      const title = w.document.querySelector("#tb-titel");
      assert.ok(title, "Actual canonical appointment editor opened"); checks++;
      title.value = "Keep this unsaved draft";
      title.dispatchEvent(new w.Event("input", { bubbles: true }));
      if (stage === "before-prepare")
        throws(() => w.App.macOSBetaPrepareCalendarImport(payload([draft("editor-race")])), /editor/, "Preparation preserves active form draft");
      else if (stage === "before-commit")
        await rejects(w.App.macOSBetaCommitCalendarImport(review.token), /stale/, "Commit preserves form draft opened after preview");
      else {
        await b.pump();
        assert.match((await pending).message, /stale/); checks++;
      }
      equal(title.isConnected, true, "Aborted import leaves the real form open: " + stage);
      equal(title.value, "Keep this unsaved draft", "Unsaved form text remains intact: " + stage);
      equal(t.daten().termine.length, 0, "No native copy appended around draft race: " + stage);
    } finally { b.close(); }
  }
}

{
  const b = await context(), { w, t, messages } = b;
  try {
    const complete = [sourceShapeDraft("complete-timed", { title: "Public fields, complete shape", location: "Room A, West; Floor 2 \\ Annex",
        url: "https://example.invalid/appointment?x=1&y=2" }),
      sourceShapeDraft("complete-tentative", { tentative: true, available: true }),
      sourceShapeDraft("complete-zero", { start: "2026-05-10T10:00:17Z", end: "2026-05-10T10:00:17Z" }),
      sourceShapeDraft("complete-date", { allDay: true, start: "2026-05-10T00:00:00Z", end: "2026-05-11T00:00:00Z" })];
    const expectedKeys = ["uid", "titel", "datum", "endDatum", "zeit", "endZeit", "icsAnzeigeZeitzone", "notiz", "kategorien", "akzentFarbe",
      "vertraulich", "vorlaeufig", "kostenstelle", "kunde", "individuelleErinnerungTage", "standardErinnerung", "wiederholung", "icsKomplex",
      "icsSerienUid", "icsZusatzDaten", "icsZusatzTermine", "icsEndeFehlt", "icsNullDauer", "icsRoundtrip", "icsSequence", "icsAenderungszeitFehlt",
      "geaendert", "ort", "ganztag", "alarme", "sync", "syncKalenderUid", "syncQuellen", "icsQuelleId", "icsQuelleName", "nativeSourceReadOnly",
      "nativeSystemRecord", "nativeCalendarImport"].sort();
    equal(Object.keys(complete[0]).sort(), expectedKeys, "Source-shaped fixture covers the complete current native event DTO");
    const review = w.App.macOSBetaPrepareCalendarImport(payload(complete));
    equal([review.newCount, review.excluded.length], [4, 0], "Full timed/tentative/zero-duration/DATE DTOs survive actual canonical normalization");
    await commit(b, review);
    for (const original of complete) {
      const actual = t.daten().termine.find(record => record.uid === original.uid);
      for (const name of expectedKeys) {
        if (name === "wiederholung") {
          for (const part of Object.keys(original[name])) equal(actual[name][part], original[name][part], "Full DTO recurrence property remains exact: " + part);
        } else equal(actual[name], original[name], "Full native DTO property remains exact: " + name);
      }
    }
    equal(t.daten().termine[1].vorlaeufig, true, "Tentative native status remains visible in the canonical model");
    equal(t.daten().termine[1].icsRoundtrip.some(line => /^STATUS[;:]/.test(line)), false, "Canonical tentative state has no stale duplicate raw STATUS");
    equal(t.daten().termine[1].nativeSystemRecord.fields.status, 2, "Original tentative EventKit status remains in native provenance");
    const zero = t.daten().termine[2];
    equal([zero.icsNullDauer, zero.endZeit], [true, ""], "Zero-duration decoder shape retains its exact marker and empty display endTime");
    equal(zero.icsRoundtrip.filter(line => /^DT(?:START|END):/.test(line)),
      ["DTSTART:20260510T100017Z", "DTEND:20260510T100017Z"], "Zero-duration raw bounds remain equal without an invented duration");
    equal(t.normalisiere(clone(t.daten())).termine.map(record => [record.icsNullDauer, record.vorlaeufig, record.ganztag, record.standardErinnerung]),
      [[false, false, false, false], [false, true, false, false], [true, false, false, false], [false, false, true, false]],
      "Complete native copy flags survive actual whole-book normalization");
    const tentative = t.daten().termine[1], nativeBefore = clone(tentative.nativeSystemRecord), provenanceBefore = clone(tentative.nativeCalendarImport);
    const timeBefore = tentative.icsRoundtrip.filter(line => /^DT(?:START|END)[;:]/.test(line));
    t.oeffneTerminBlatt(tentative, tentative.datum);
    const tentativeField = w.document.querySelector("#tb-vorlaeufig");
    assert.ok(tentativeField, "Actual canonical tentative checkbox opened"); checks++;
    equal(w.document.querySelector("#tb-standard-erinnerung").checked, false, "Opening native copy editor preserves its reminder opt-out at zero custom days");
    equal(w.document.querySelector("#tb-standard-erinnerung-zeile").style.display, "", "Native copy exposes a conscious default-reminder choice even at zero custom days");
    tentativeField.checked = false;
    tentativeField.dispatchEvent(new w.Event("change", { bubbles: true }));
    w.document.querySelector("#tb-fertig").click();
    t.speichereJetzt(); await b.pump();
    equal(tentative.vorlaeufig, false, "Actual local editor changes tentative state");
    equal(tentative.icsRoundtrip.some(line => /^STATUS[;:]/.test(line)), false, "Actual editor roundtrip introduces no contradictory native raw STATUS");
    equal(tentative.icsRoundtrip.filter(line => /^DT(?:START|END)[;:]/.test(line)), timeBefore, "Status-only local edit retains exact UTC seconds");
    equal(tentative.nativeSystemRecord, nativeBefore, "Local status edit keeps the original native snapshot intact");
    equal(tentative.nativeCalendarImport, provenanceBefore, "Local status edit does not rewrite native import identity or revision");
    equal(tentative.standardErinnerung, false, "Saving a status-only local edit does not invent a standard reminder");
    t.daten().einstellungen.erinnerung.an = true; t.daten().einstellungen.erinnerung.vorlauf = 0;
    b.at("2026-05-10T10:00:00Z");
    let reminderCount = messages.filter(message => message.cmd === "erinnerung_zeigen").length;
    t.pruefeErinnerungen();
    equal(messages.filter(message => message.cmd === "erinnerung_zeigen").length, reminderCount, "Actual scheduler remains quiet after the status-only edit");
    t.oeffneTerminBlatt(tentative, tentative.datum);
    const defaultReminder = w.document.querySelector("#tb-standard-erinnerung");
    defaultReminder.checked = true; defaultReminder.dispatchEvent(new w.Event("change", { bubbles: true }));
    w.document.querySelector("#tb-fertig").click(); t.speichereJetzt(); await b.pump();
    equal(tentative.standardErinnerung, true, "Explicit default-reminder opt-in survives local editor save");
    equal(t.normalisiere(clone(t.daten())).termine[1].standardErinnerung, true, "Explicit reminder opt-in also survives normalization");
    t.pruefeErinnerungen();
    equal(messages.filter(message => message.cmd === "erinnerung_zeigen").length, reminderCount + 1, "Actual scheduler honors the explicit default-reminder opt-in");
    const customAlarm = t.daten().termine[0];
    t.oeffneTerminBlatt(customAlarm, customAlarm.datum);
    w.document.querySelector("#tb-alarme > button").click();
    const minutes = w.document.querySelector(".tb-alarm-zahl");
    minutes.value = "0"; minutes.dispatchEvent(new w.Event("input", { bubbles: true }));
    w.document.querySelector("#tb-fertig").click(); t.speichereJetzt(); await b.pump();
    equal([customAlarm.standardErinnerung, customAlarm.alarme.length, customAlarm.alarme[0].offsetMinuten], [false, 1, 0], "An explicitly added local alarm works independently of default-reminder opt-out");
    equal(customAlarm.icsRoundtrip.includes("BEGIN:VALARM"), true, "Actual editor writes the explicitly requested local alarm");
    reminderCount = messages.filter(message => message.cmd === "erinnerung_zeigen").length;
    t.pruefeErinnerungen();
    equal(messages.filter(message => message.cmd === "erinnerung_zeigen").length, reminderCount + 1, "Actual scheduler honors the explicit local alarm");
  } finally { b.close(); }
}

{
  const b = await context(), { w, t, messages } = b;
  try {
    t.daten().einstellungen.futureImport = { keep: true };
    t.daten().gesundheit.futureImport = { keep: [1, 2] };
    t.daten().customOrganizer.futureImport = { keep: [3, 4] };
    t.speichereJetzt(); await b.pump();
    const before = JSON.stringify(t.daten()), domainBefore = JSON.stringify([t.daten().einstellungen, t.daten().gesundheit, t.daten().customOrganizer]);
    const incoming = payload([draft("first"), draft("second")]);
    const review = w.App.macOSBetaPrepareCalendarImport(incoming);
    equal(JSON.stringify(t.daten()), before, "Preparation has no model mutation");
    equal([review.newCount, review.existingCount, review.changedCount], [2, 0, 0], "Same title and time are distinct native identities");
    equal(review.preview[0], { title: "Same title", date: "2026-05-10", time: "10:00", endDate: "", endTime: "11:00", allDay: false, location: "Office" }, "Concrete preview");
    review.preview[0].title = "External mutation"; incoming.appointments[0].titel = "Payload mutation";
    throws(() => w.App.macOSBetaPrepareCalendarImport(payload([draft("parallel")])), /already/, "One active proposal");
    await rejects(w.App.macOSBetaCommitCalendarImport("wrong-token"), /Invalid/, "Wrong token cannot clear the valid review");
    let finished = false;
    const pending = w.App.macOSBetaCommitCalendarImport(review.token).then(value => { finished = true; return value; });
    equal(JSON.stringify(t.daten()), before, "No mutation before recovery ACK");
    await b.pump({ ackSaves: false });
    equal(finished, false, "No success before durable save ACK");
    equal(t.daten().termine.length, 2, "Checkpoint authorizes exactly the reviewed additive copies");
    await b.pump();
    equal((await pending).count, 2, "Durable import receipt");
    equal(t.daten().termine[0].titel, "Same title", "Returned preview and original payload cannot change private plan");
    equal(JSON.stringify([t.daten().einstellungen, t.daten().gesundheit, t.daten().customOrganizer]), domainBefore, "Other model domains retained");
    equal(t.daten().futureRoot, initial.futureRoot, "Unknown root fields retained");
    equal(t.daten().termine.map(record => record.nativeSystemRecord), payload([draft("first"), draft("second")]).appointments.map(record => record.nativeSystemRecord), "Exposed native metadata retained exactly");
    equal(new Set(t.daten().termine.map(record => record.id)).size, 2, "Fresh unique local IDs");
    await rejects(w.App.macOSBetaCommitCalendarImport(review.token), /Invalid/, "Consumed token cannot replay");
    const record = t.daten().termine[0], expanded = t.icsExpansion(record, Date.parse("2026-05-10T00:00:00Z"), Date.parse("2026-05-11T00:00:00Z"), false, true);
    equal(expanded[0].icsOccurrence, Date.parse("2026-05-10T10:00:17Z"), "Real canonical expansion retains UTC seconds");
    equal(record.icsRoundtrip, draft("first").icsRoundtrip, "Exact UTC bounds retained");
    const reloaded = t.normalisiere(clone(t.daten()));
    equal(reloaded.termine[0].standardErinnerung, false, "Native copy reminder opt-out survives full canonical reload");
    record.titel = "Locally edited"; record.notiz = "Keep my notes";
    record.future = { retained: "local extension" };
    const localBefore = JSON.stringify(record);
    const repeated = w.App.macOSBetaPrepareCalendarImport(payload([draft("first"), draft("second")]));
    equal([repeated.newCount, repeated.existingCount, repeated.changedCount], [0, 2, 0], "Repeat import skips existing copies");
    equal((await commit(b, repeated)).count, 0, "No-op import does not create a second copy");
    equal(JSON.stringify(record), localBefore, "Local edits and opaque extensions are untouched");
    const updated = draft("first", { title: "Changed in Apple Calendar" });
    const changed = w.App.macOSBetaPrepareCalendarImport(payload([updated]));
    equal([changed.newCount, changed.changedCount], [0, 1], "Native changes are review-only, never an update");
    await commit(b, changed);
    equal(JSON.stringify(record), localBefore, "Changed source does not overwrite local data");
    const secondSource = source("Calendar B"), other = w.App.macOSBetaPrepareCalendarImport(payload([draft("first", { account: secondSource })], secondSource));
    equal(other.newCount, 1, "Same native identifier in another source stays separate");
    await commit(b, other);
    const movedAccount = clone(source()); movedAccount.parentUID = "different-account";
    throws(() => w.App.macOSBetaPrepareCalendarImport(payload([draft("first", { account: movedAccount })], movedAccount)), /Conflicting/, "Reused calendar ID under another native account fails closed");
    const foreign = draft("foreign"); t.daten().termine.push({ id: "foreign", uid: foreign.uid, datum: "2026-05-10", titel: "Unrelated" });
    throws(() => w.App.macOSBetaPrepareCalendarImport(payload([foreign])), /identity/, "Foreign UID collision cannot adopt an existing event");
    t.daten().termine.pop();
    t.daten().termine.push({ ...clone(record), id: "ambiguous" });
    throws(() => w.App.macOSBetaPrepareCalendarImport(payload([draft("first")])), /Multiple/, "Ambiguous native identity fails closed");
    t.daten().termine.pop();
    const deleted = draft("deleted");
    t.daten().papierkorb.push({ id: "trash", art: "appointment", eintrag: deleted });
    const trash = w.App.macOSBetaPrepareCalendarImport(payload([deleted]));
    equal([trash.newCount, trash.excluded[0].reasons[0]], [0, "local-calendar-copy-in-trash"], "Import does not silently restore a trashed local copy");
    w.App.macOSBetaCancelCalendarImport(trash.token);
    w.App.macOSBetaStartCalendarImport(); await b.pump();
    equal(messages.filter(message => message.cmd === "macos_kalender_importieren").at(-1), { cmd: "macos_kalender_importieren" }, "Start sends only native picker command after saving");
  } finally { b.close(); }
}

{
  const b = await context(), { w, t } = b;
  try {
    const tooLong = draft("location-loss", { location: "x".repeat(1001) });
    const trimmed = draft("location-trim", { location: " Office " });
    const review = w.App.macOSBetaPrepareCalendarImport(payload([draft("valid"), tooLong, trimmed], source(), [{ title: "Series", reasons: ["native-series-projection-not-lossless"] }]));
    equal([review.newCount, review.excluded.length], [1, 3], "Canonical content losses are explicitly excluded before mutation");
    equal(review.excluded.slice(1).map(item => item.reasons), [["canonical-calendar-content-would-change"], ["canonical-calendar-content-would-change"]], "Text changes are not silently accepted");
    equal(t.daten().termine, [], "Excluded records do not affect book");
    equal(w.App.macOSBetaCancelCalendarImport(review.token), { ok: true, cancelled: true }, "Explicit cancel discards only matching proposal");
    await rejects(w.App.macOSBetaCommitCalendarImport(review.token), /Invalid/, "Cancelled proposal cannot commit");
    throws(() => w.App.macOSBetaPrepareCalendarImport(payload([draft("duplicate"), draft("duplicate")])), /Ambiguous/, "Duplicate native payload identities rejected");
    const malformed = payload([draft("bad")]); malformed.appointments[0].nativeSystemRecord.revision = "b".repeat(64);
    throws(() => w.App.macOSBetaPrepareCalendarImport(malformed), /identity/, "Revision mismatch rejected");
    const syncAuthority = payload([draft("bad-sync")]); syncAuthority.appointments[0].sync = true;
    throws(() => w.App.macOSBetaPrepareCalendarImport(syncAuthority), /Unsupported/, "Import never accepts supplied sync authority");
    const series = payload([draft("bad-series")]); series.appointments[0].icsRoundtrip.push("RRULE:FREQ=DAILY");
    throws(() => w.App.macOSBetaPrepareCalendarImport(series), /Unsupported/, "Unsupported recurrence cannot enter through import proposal");
    const huge = payload([], source(), Array.from({ length: 10001 }, () => ({ title: "X", reasons: ["unsupported"] })));
    throws(() => w.App.macOSBetaPrepareCalendarImport(huge), /Invalid/, "Record bound is enforced");
    const window = payload([]); window.window.end = window.window.start + 367 * 86400;
    throws(() => w.App.macOSBetaPrepareCalendarImport(window), /Invalid/, "Window beyond 366 days refused");
    const bytes = payload([draft("byte-limit")]); bytes.appointments[0].nativeSystemRecord.fields.notes = "x".repeat(16 * 1024 * 1024);
    throws(() => w.App.macOSBetaPrepareCalendarImport(bytes), /byte limit/, "Payload byte bound is enforced before parsing");
    const stale = w.App.macOSBetaPrepareCalendarImport(payload([draft("stale")]));
    t.daten().futureRoot.userEdit = "after preview";
    await rejects(w.App.macOSBetaCommitCalendarImport(stale.token), /stale/, "In-place book edits invalidate the review");
    equal(t.daten().termine, [], "Stale review retains user edits and no appointments");
    const checkpoint = w.App.macOSBetaPrepareCalendarImport(payload([draft("checkpoint")]));
    await rejects(commit(b, checkpoint, { snapshot: false }), /recovery/i, "Failed checkpoint refuses import");
    equal(t.daten().termine, [], "No mutation on failed checkpoint");
    const afterCheckpoint = w.App.macOSBetaPrepareCalendarImport(payload([draft("after-checkpoint")]));
    const waiting = w.App.macOSBetaCommitCalendarImport(afterCheckpoint.token).then(() => null, error => error);
    t.daten().futureRoot.moreEdit = true;
    await b.pump();
    assert.match((await waiting).message, /stale/); checks++;
    equal(t.daten().termine, [], "Second stale check after native checkpoint protects intervening edit");
    const cancelled = w.App.macOSBetaPrepareCalendarImport(payload([draft("cancel-waiting")]));
    const waitingCancelled = w.App.macOSBetaCommitCalendarImport(cancelled.token).then(() => null, error => error);
    equal(w.App.macOSBetaCancelCalendarImport(cancelled.token).cancelled, true, "Cancel during checkpoint still prevents append");
    const replacement = w.App.macOSBetaPrepareCalendarImport(payload([draft("replacement")]));
    await b.pump();
    assert.match((await waitingCancelled).message, /stale/); checks++;
    equal(w.App.macOSBetaCancelCalendarImport(replacement.token).cancelled, true, "Old callback cannot discard newer review");
    const failedSave = w.App.macOSBetaPrepareCalendarImport(payload([draft("unsaved")]));
    await rejects(commit(b, failedSave, { save: false }), /unsaved/, "Final save failure is not success");
    equal(t.daten().termine.length, 1, "Failed save leaves new copy available for explicit save retry");
    t.speichereJetzt(); await b.pump();
    const retry = w.App.macOSBetaPrepareCalendarImport(payload([draft("unsaved")]));
    equal([retry.newCount, retry.existingCount], [0, 1], "Repeat after save retry cannot duplicate copied event");
    w.App.macOSBetaCancelCalendarImport(retry.token);
    const expired = w.App.macOSBetaPrepareCalendarImport(payload([draft("expired")]));
    b.at("2026-05-01T12:05:01Z");
    await rejects(w.App.macOSBetaCommitCalendarImport(expired.token), /stale/, "Five-minute review expiry");
    const restoring = w.App.macOSBetaPrepareCalendarImport(payload([draft("restore")]));
    w.MacBeta.validateRestore(JSON.stringify(initial));
    await rejects(w.App.macOSBetaCommitCalendarImport(restoring.token), /stale/, "Restore fence blocks pending review");
    throws(() => w.App.macOSBetaPrepareCalendarImport(payload([draft("blocked")])), /not available/, "Restore fence blocks new review");
  } finally { b.close(); }
}

{
  const b = await context(), { w, t, messages } = b;
  try {
    const allDay = draft("all-day", { allDay: true, start: "2026-05-10T00:00:00Z", end: "2026-05-13T00:00:00Z", endDate: "2026-05-12" });
    const fold = draft("fold", { start: "2026-10-25T01:30:17Z", end: "2026-10-25T02:15:19Z", zone: "Europe/Berlin", date: "2026-10-25", time: "02:30", endTime: "03:15" });
    const review = w.App.macOSBetaPrepareCalendarImport(payload([allDay, fold, draft("no-alarm")]));
    await commit(b, review);
    const [allDayCopy, foldCopy] = t.daten().termine;
    equal(allDayCopy.icsRoundtrip, allDay.icsRoundtrip, "Exclusive DATE end retained across multi-day import");
    equal(t.termineAm("2026-05-12", true).some(record => record.uid === allDayCopy.uid), true, "Multi-day DATE event occupies its final included date");
    equal(t.termineAm("2026-05-13", true).some(record => record.uid === allDayCopy.uid), false, "Exclusive DATE end does not occupy following date");
    const expanded = t.icsExpansion(foldCopy, Date.parse("2026-10-25T00:00:00Z"), Date.parse("2026-10-26T00:00:00Z"), false, true);
    equal(expanded[0].icsOccurrence, Date.parse("2026-10-25T01:30:17Z"), "UTC line selects later DST fold with seconds");
    t.daten().einstellungen.erinnerung.an = true; t.daten().einstellungen.erinnerung.vorlauf = 0;
    b.at("2026-05-10T10:00:00Z");
    let reminders = messages.filter(message => message.cmd === "erinnerung_zeigen").length;
    t.pruefeErinnerungen();
    equal(messages.filter(message => message.cmd === "erinnerung_zeigen").length, reminders, "Actual scheduler does not invent standard alarms for imported copies");
    t.daten().termine = t.normalisiere(clone(t.daten())).termine;
    t.pruefeErinnerungen();
    equal(messages.filter(message => message.cmd === "erinnerung_zeigen").length, reminders, "No invented alarm after canonical reload either");
    const normal = { ...clone(t.daten().termine[2]), id: "normal-event", uid: "normal-event", standardErinnerung: false };
    delete normal.nativeCalendarImport; delete normal.nativeSystemRecord;
    t.daten().termine.push(normal); t.pruefeErinnerungen();
    equal(messages.filter(message => message.cmd === "erinnerung_zeigen").length, reminders + 1, "Existing ordinary-event reminder behavior remains unchanged");
  } finally { b.close(); }
}
// #778: an already observed save ACK is distinct from unconfirmed saving.
for (const stage of ["checkpoint", "saving"]) {
  const b = await context(), { w, t } = b;
  try {
    const review = w.App.macOSBetaPrepareCalendarImport(payload([draft("old-generation")]));
    const pending = w.App.macOSBetaCommitCalendarImport(review.token).then(() => null, error => error);
    if (stage === "saving") await b.pump({ ackSaves: false });
    w.MacBeta.receive("init", { daten: clone(initial), neu: false, regional: { language: "en", timeZone: "UTC" } });
    await b.pump(); const failure = await pending;
    assert.match(failure.message, /stale|document changed/i); checks++;
    equal(/copies were added|remain unsaved|saving was not confirmed/i.test(failure.message), false,
      "Pre-append rejection or observed save ACK keeps its specific document-change diagnosis: " + stage);
    equal(t.daten().termine.length, 0, "Obsolete import never changes replacement document: " + stage);
  } finally { b.close(); }
}

// #778: exercise the public renderer hook after the real canonical append.
for (const language of ["en", "de"]) {
  const b = await context(), { w, t, messages } = b;
  const appearance = w.MagnolieAppearance;
  try {
    w.MagnolieI18n.setLocale(language);
    await commit(b, w.App.macOSBetaPrepareCalendarImport(payload([draft("existing-copy")])));
    t.daten().termine[0].titel = "Keep this local calendar edit";
    t.speichereJetzt(); await b.pump();
    const original = JSON.stringify(t.daten().termine), originalCount = t.daten().termine.length;
    const review = w.App.macOSBetaPrepareCalendarImport(payload([draft("render-failure")]));
    try {
      w.MagnolieAppearance = { ...appearance, update() { throw new Error("Synthetic renderer failure after append"); } };
      await rejects(commit(b, review), language === "de"
        ? /Terminkopien wurden hinzugefügt, ihre Speicherung wurde jedoch nicht bestätigt\..*Synthetic renderer failure after append/
        : /Appointment copies were added, but saving was not confirmed\..*Synthetic renderer failure after append/,
        "Actual renderer failure explains local mutation and unconfirmed persistence");
    } finally { w.MagnolieAppearance = appearance; }
    equal(t.daten().termine.length, originalCount + 1, "Added copy survives renderer failure for save retry");
    equal(JSON.stringify(t.daten().termine.slice(0, originalCount)), original, "Renderer failure preserves all pre-existing records and local edits");
    equal(t.daten().termine.at(-1).nativeCalendarImport.identifier, "render-failure", "Renderer failure retains exact native provenance");
    t.speichereJetzt(); await b.pump();
    const saved = JSON.parse(messages.filter(message => message.cmd === "speichern").at(-1).text);
    equal(saved.termine, t.daten().termine, "Actual retry save contains both existing records and the added copy");
    const retry = w.App.macOSBetaPrepareCalendarImport(payload([draft("render-failure")]));
    equal([retry.newCount, retry.existingCount], [0, 1], "Save retry preserves provenance and prevents duplicate import");
    w.App.macOSBetaCancelCalendarImport(retry.token);
    w.MacBeta.receive("init", { daten: saved, neu: false, regional: { language, timeZone: "UTC" } });
    await b.pump();
    const reopened = w.App.macOSBetaPrepareCalendarImport(payload([draft("render-failure")]));
    equal([reopened.newCount, reopened.existingCount], [0, 1], "Reopened retry-save bytes still prevent duplicate import");
    w.App.macOSBetaCancelCalendarImport(reopened.token);
  } finally { w.MagnolieAppearance = appearance; b.close(); }
}

console.log(`Mac native calendar import: ${checks} projected UI checks; synthetic EventKit payload/transport, not native access evidence.`);
