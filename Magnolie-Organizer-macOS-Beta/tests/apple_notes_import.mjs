import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { boot, tick } from "./ui_harness.mjs";

const clone = value => JSON.parse(JSON.stringify(value));
const digest = value => createHash("sha256").update(JSON.stringify(value)).digest("hex");
let checks = 0;
const equal = (actual, expected, label) => { assert.deepEqual(clone(actual), clone(expected), label); checks++; };
const throws = (action, pattern, label) => { assert.throws(action, pattern, label); checks++; };
const rejects = async (action, pattern, label) => { await assert.rejects(action, pattern, label); checks++; };
const initial = { termine: [], aufgaben: [], kontakte: [],
  notizen: [{ id: "local-note", titel: "Same title", text: "Local text", html: "<b>Local text</b>", notizbuchId: "local-book", future: { retain: 17 } }],
  notizgruppen: [{ id: "group", name: "Notebooks" }],
  notizbuecher: [{ id: "local-book", gruppeId: "group", name: "Existing notebook" }, { id: "target-book", gruppeId: "group", name: "Apple copies" }],
  futureRoot: { retained: ["opaque", { value: 17 }] }, einstellungen: { allgemein: { handbuchHinweisGezeigt: true } } };
const source = (accountID = "account-A", folderID = "folder-A") => ({ accountID, accountTitle: "iCloud", folderID, folderTitle: "Notes" });
function item(identifier, { origin = source(), title = "Same title", text = "Local text", bodyHTML = "<div>Native formatted text</div>", modified = 1770000000.25 } = {}) {
  // Honest synthetic native input, following AppleNotesImport's public DTO. No
  // AppleScript or Swift execution is implied by these renderer contract tests.
  const nativeRecord = { identifier, title, passwordProtected: false, attachmentCount: 0, plaintext: text, bodyHTML, modified, failure: null };
  return { identity: digest([origin.accountID, identifier]), revision: digest([origin, nativeRecord]), identifier, title, text, nativeRecord };
}
function payload(notes, origin = source(), excluded = []) {
  return { version: 1, source: origin, notes, excluded, snapshotRevision: digest([origin, notes, excluded]) };
}
async function context(book = initial) {
  const b = await boot(process.argv[2], Date.parse("2026-05-01T12:00:00Z")), seen = new Set();
  const { w, t, messages } = b;
  w.MacBeta.receive("init", { daten: clone(book), neu: false, regional: { language: "en", timeZone: "UTC" } });
  t.zustand().notizen.notizbuchId = "target-book"; t.zustand().notizen.auswahlId = null;
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
  const result = b.w.App.macOSBetaCommitAppleNotesImport(review.token);
  const settled = result.then(value => ({ value }), error => ({ error }));
  await b.pump(options);
  const outcome = await settled;
  if (outcome.error) throw outcome.error;
  return outcome.value;
}

let reopenBook;
{
  const b = await context(), { w, t, messages } = b;
  try {
    t.daten().einstellungen.futureImport = { keep: true };
    t.daten().gesundheit.futureImport = { keep: [1, 2] };
    t.daten().customOrganizer.futureImport = { keep: [3, 4] };
    t.speichereJetzt(); await b.pump();
    const before = JSON.stringify(t.daten()), originalNote = JSON.stringify(t.daten().notizen[0]);
    const domains = JSON.stringify([t.daten().einstellungen, t.daten().gesundheit, t.daten().customOrganizer]);
    const literal = " \n# Literal <script>window.appleSourceRan = true</script> & <img src=x onerror=alert(1)>\n ";
    const nativeHTML = '<div data-apple-source="private"><script>window.appleSourceRan=true</script><img src="https://example.invalid/track"><b>Original formatting</b></div>';
    const incoming = payload([item("first"), item("second"), item("literal", { title: "<b>Literal title</b>", text: literal, bodyHTML: nativeHTML })]);
    const review = w.App.macOSBetaPrepareAppleNotesImport(incoming);
    equal(JSON.stringify(t.daten()), before, "Preparation leaves the complete model untouched");
    equal([review.newCount, review.existingCount, review.changedCount, review.notebookTitle], [3, 0, 0, "Apple copies"], "Concrete target and identity-based counts");
    equal(review.preview[2], { title: "<b>Literal title</b>", text: literal }, "Review returns the full exact plaintext");
    review.preview[0].text = "Changed returned preview"; incoming.notes[0].text = "Changed original payload";
    throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([item("parallel")])), /already/, "One active proposal");
    await rejects(w.App.macOSBetaCommitAppleNotesImport("wrong-token"), /Invalid/, "Wrong token cannot clear the current review");
    let finished = false;
    const pending = w.App.macOSBetaCommitAppleNotesImport(review.token).then(value => { finished = true; return value; });
    equal(JSON.stringify(t.daten()), before, "No mutation before recovery ACK");
    await b.pump({ ackSaves: false });
    equal([finished, t.daten().notizen.length], [false, 4], "Copied notes remain unacknowledged until actual save ACK");
    await b.pump(); equal((await pending).count, 3, "Durable copy receipt");
    equal(JSON.stringify(t.daten().notizen[0]), originalNote, "Existing same-title/same-text note remains exact");
    equal(JSON.stringify([t.daten().einstellungen, t.daten().gesundheit, t.daten().customOrganizer]), domains, "Other domains remain exact");
    equal(t.daten().futureRoot, initial.futureRoot, "Root extension retained");
    equal(t.daten().notizen.slice(1).map(note => note.notizbuchId), ["target-book", "target-book", "target-book"], "All copies go to reviewed target notebook");
    equal(new Set(t.daten().notizen.map(note => note.id)).size, 4, "Fresh independent local note IDs");
    equal(t.daten().notizen.slice(1).some(note => Object.hasOwn(note, "uid")), false, "No external UID is invented for notes");
    equal(t.daten().notizen[1].text, "Local text", "Private proposal ignores outside mutation");
    const copied = t.daten().notizen[3];
    equal(copied.text, literal, "Whitespace and literal source text retained");
    equal(copied.nativeAppleNotesRecord.bodyHTML, nativeHTML, "Source HTML retained only as inert provenance");
    equal([copied.nativeAppleNotesImport.copyKind, copied.nativeAppleNotesImport.revisionCoverage], ["plaintext", "serialized-fields-only"], "Copy limitations explicitly retained");
    const surface = w.document.createElement("div"); surface.innerHTML = copied.html;
    equal(surface.querySelectorAll("script,img,b,[data-apple-source]").length, 0, "Source HTML and literal tags do not become rendered elements");
    for (const br of surface.querySelectorAll("br")) br.replaceWith(w.document.createTextNode("\n"));
    equal(surface.textContent, literal, "Rendered copy retains every literal character and newline");
    equal(w.appleSourceRan ?? false, false, "Source script was never evaluated");
    equal(t.normalisiere(clone(t.daten())).notizen[3].nativeAppleNotesRecord, copied.nativeAppleNotesRecord, "Whole-book normalization preserves original native record");
    equal(t.normalisiere(clone(t.daten())).notizen[3].nativeAppleNotesImport, copied.nativeAppleNotesImport, "Whole-book normalization preserves copy identity and source");
    await rejects(w.App.macOSBetaCommitAppleNotesImport(review.token), /Invalid/, "Consumed token cannot replay");
    const local = t.daten().notizen[1]; local.titel = "Edited locally"; local.text = "My local wording"; local.html = "<em>My local wording</em>"; local.future = { keep: true };
    const localBefore = JSON.stringify(local);
    const repeated = w.App.macOSBetaPrepareAppleNotesImport(payload([item("first"), item("second")]));
    equal([repeated.newCount, repeated.existingCount, repeated.changedCount], [0, 2, 0], "Repeat source read skips copies despite local edits");
    equal((await commit(b, repeated)).count, 0, "Zero-candidate review is valid and does not mutate");
    equal(JSON.stringify(local), localBefore, "Local text, formatting and extension retained");
    const changed = w.App.macOSBetaPrepareAppleNotesImport(payload([item("first", { text: "Changed in Apple Notes", modified: 1770000001 })]));
    equal([changed.newCount, changed.changedCount, changed.changedPreview[0].title], [0, 1, "Same title"], "Source change is identified without overwriting");
    await commit(b, changed); equal(JSON.stringify(local), localBefore, "Source change preserves local copy");
    const moved = source("account-A", "folder-B"); moved.folderTitle = "Moved notes";
    const movement = w.App.macOSBetaPrepareAppleNotesImport(payload([item("first", { origin: moved })], moved));
    equal([movement.newCount, movement.changedCount], [0, 1], "Folder move is a changed source, never a new identity");
    await commit(b, movement); equal(JSON.stringify(local), localBefore, "Folder movement never moves or changes local notebook");
    const otherAccount = source("account-B");
    const accountReview = w.App.macOSBetaPrepareAppleNotesImport(payload([item("first", { origin: otherAccount })], otherAccount));
    equal(accountReview.newCount, 1, "Same note identifier under another account is separate");
    await commit(b, accountReview);
    const conflict = item("foreign"); conflict.identity = local.nativeAppleNotesImport.identity;
    throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([conflict])), /identity/, "Foreign source cannot adopt an existing identity");
    t.daten().notizen.push({ ...clone(local), id: "duplicate-local" });
    throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([item("first")])), /Multiple/, "Duplicate local identities fail closed");
    t.daten().notizen.pop();
    const trashed = t.daten().notizen[2];
    t.daten().notizen.splice(2, 1); t.daten().papierkorb.push({ id: "trash-copy", art: "note", eintrag: clone(trashed), name: trashed.titel, geloescht: Date.now() });
    const trashReview = w.App.macOSBetaPrepareAppleNotesImport(payload([item("second")]));
    equal([trashReview.newCount, trashReview.excluded[0].reasons[0]], [0, "local-apple-note-copy-in-trash"], "Copying does not silently restore a trashed note");
    w.App.macOSBetaCancelAppleNotesImport(trashReview.token);
    w.App.macOSBetaStartAppleNotesImport(); await b.pump();
    equal(messages.filter(message => message.cmd === "macos_apple_notizen_importieren").at(-1), { cmd: "macos_apple_notizen_importieren" }, "Start uses parameterless native selector after saving");
    reopenBook = clone(t.daten());
  } finally { b.close(); }
}

{
  const b = await context(reopenBook), { w, t } = b;
  try {
    const before = clone(t.daten().notizen.find(note => note.nativeAppleNotesImport?.identifier === "first" && note.nativeAppleNotesImport.accountID === "account-A"));
    const reopened = w.App.macOSBetaPrepareAppleNotesImport(payload([item("first"), item("second")]));
    equal([reopened.newCount, reopened.existingCount, reopened.excluded[0].reasons[0]], [0, 1, "local-apple-note-copy-in-trash"], "Actual fresh initialization retains both copy and trash identities");
    await commit(b, reopened);
    equal(t.daten().notizen.find(note => note.id === before.id), before, "Reopening then repeating leaves local copy exact");
  } finally { b.close(); }
}

{
  const b = await context(), { w, t } = b;
  try {
    const unchanged = [
      item("empty-both", { title: "", text: "", bodyHTML: "" }),
      item("empty-title", { title: "", text: "Text without a title" }),
      item("empty-text", { title: "Title without text", text: "" }),
      item("tabs", { title: "Title\t", text: "\tfirst\tline\n\nlast\t " }),
      item("unicode", { title: "Cafe\u0301 🪷", text: "é / e\u0301\n中文 العربية 👩‍💻\u2028\u2029\u00a0", bodyHTML: "<div>\r\nInert HTML\r</div>" }),
      item("title-linebreaks", { title: "A\r\nB\rC", text: "A\nB" })
    ];
    const changed = [item("crlf", { text: "first\r\nsecond" }), item("cr", { text: "first\rsecond" })];
    const review = w.App.macOSBetaPrepareAppleNotesImport(payload([...unchanged, ...changed]));
    equal(review.newCount, unchanged.length, "Empty strings, tabs, emoji and decomposed Unicode are eligible");
    equal(review.preview, unchanged.map(value => ({ title: value.title, text: value.text })), "Complete review preserves exact UTF-16 title/text content");
    equal(review.excluded, changed.map(value => ({ identifier: value.identifier, title: value.title, reasons: ["canonical-note-content-would-change"] })),
      "CRLF and CR are excluded because the actual HTML parser would normalize their content");
    await commit(b, review);
    const normalized = t.normalisiere(clone(t.daten()));
    for (let i = 0; i < unchanged.length; i++) {
      const note = t.daten().notizen[i + 1], expected = unchanged[i], surface = w.document.createElement("div");
      equal([note.titel, note.text, note.nativeAppleNotesRecord], [expected.title, expected.text, expected.nativeRecord], "Canonical note and inert native record retained: " + expected.identifier);
      equal(normalized.notizen[i + 1], note, "Full canonical normalization preserves the stored copy: " + expected.identifier);
      surface.innerHTML = note.html;
      for (const br of surface.querySelectorAll("br")) br.replaceWith(w.document.createTextNode("\n"));
      equal(surface.textContent, expected.text, "Actual rendered literal remains exact: " + expected.identifier);
    }
    for (const text of ["\uD800", "\uDFFF", "before\uD800after", "\uDFFF\uD800"]) {
      throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([item("lone-surrogate", { text })])), /Invalid/, "Lone UTF-16 surrogates cannot become replacement characters");
    }
    const invalidHTML = item("invalid-native-html"); invalidHTML.nativeRecord.bodyHTML = "\uD800";
    throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([invalidHTML])), /Invalid/, "Inert native HTML must also retain valid Unicode");
    throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([item("invalid-title", { title: "\uDC00" })])), /Invalid/, "Lone surrogate in title is refused");
  } finally { b.close(); }
}

for (const action of ["prepare", "start"]) {
  const b = await context(), { w, t, messages } = b;
  try {
    const oldBook = t.daten(), old = w.App.macOSBetaPrepareAppleNotesImport(payload([item("old-preview")]));
    w.MacBeta.receive("init", { daten: clone(initial), neu: false, regional: { language: "en", timeZone: "UTC" } });
    t.zustand().notizen.notizbuchId = "target-book";
    equal(t.daten() === oldBook, false, "Actual reinitialization changes document identity");
    if (action === "start") {
      w.App.macOSBetaStartAppleNotesImport(); await b.pump();
      equal(messages.filter(message => message.cmd === "macos_apple_notizen_importieren").length, 1, "New Start can discard an old-book prepared review");
    }
    const current = w.App.macOSBetaPrepareAppleNotesImport(payload([item("current-preview")]));
    equal(current.newCount, 1, "New Prepare can replace only the obsolete document's review: " + action);
    equal(w.App.macOSBetaCancelAppleNotesImport(old.token).cancelled, false, "Old-generation cancellation cannot clear new review");
    await rejects(w.App.macOSBetaCommitAppleNotesImport(old.token), /Invalid/, "Old-generation commit cannot consume new review");
    await commit(b, current);
    equal([oldBook.notizen.length, t.daten().notizen.at(-1).nativeAppleNotesImport.identifier], [1, "current-preview"], "Only current document receives the current reviewed copy");
  } finally { b.close(); }
}

for (const stage of ["checkpoint", "saving"]) {
  const b = await context(), { w, t, messages } = b;
  try {
    const review = w.App.macOSBetaPrepareAppleNotesImport(payload([item("in-flight")]));
    const pending = w.App.macOSBetaCommitAppleNotesImport(review.token).then(() => null, error => error);
    if (stage === "saving") await b.pump({ ackSaves: false });
    w.MacBeta.receive("init", { daten: clone(initial), neu: false, regional: { language: "en", timeZone: "UTC" } });
    t.zustand().notizen.notizbuchId = "target-book";
    throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([item("must-wait")])), /already/, "In-flight proposal remains owned after reinitialization: " + stage);
    w.App.macOSBetaStartAppleNotesImport();
    equal(messages.filter(message => message.cmd === "macos_apple_notizen_importieren").length, 0, "Start cannot replace an in-flight operation: " + stage);
    await b.pump(); const failure = await pending;
    assert.match(failure.message, /stale|document changed/i); checks++;
    equal(/copies were added|remain unsaved|saving was not confirmed/i.test(failure.message), false,
      "Pre-append rejection or observed save ACK keeps its specific document-change diagnosis: " + stage);
    equal(t.daten().notizen.length, 1, "Obsolete in-flight callback never appends to replacement document: " + stage);
    const current = w.App.macOSBetaPrepareAppleNotesImport(payload([item("after-completion")]));
    equal(w.App.macOSBetaCancelAppleNotesImport(current.token).cancelled, true, "New review works after old operation settles: " + stage);
  } finally { b.close(); }
}

{
  const b = await context(), { w, t, messages } = b;
  try {
    t.oeffneEinstellungen(); w.document.querySelector("#einst-tab-sync").click();
    const request = messages.filter(message => message.cmd === "eds_status" && message.requestId).at(-1);
    const button = () => w.document.querySelector("#macos-apple-notes-import");
    const starts = () => messages.filter(message => message.cmd === "macos_apple_notizen_importieren");
    equal(button().disabled, true, "Actual System Sources button waits for its outstanding source request");
    button().click(); equal(starts().length, 0, "Disabled source button cannot launch another native dialog");
    w.MacBeta.receive("edsStatus", { requestId: "stale", kalender: [], adressbuecher: [] });
    equal(button().disabled, true, "Unrelated source reply cannot enable the button");
    w.MacBeta.receive("edsStatus", { requestId: request.requestId, kalender: [], adressbuecher: [] });
    equal(button().disabled, false, "Matching source response releases the actual import button");
    t.daten().futureRoot.sourceButtonEdit = "save before picker";
    button().click();
    equal(starts().length, 0, "Picker waits for document save acknowledgement after actual button click");
    equal(w.document.querySelector("#einstellungen-schleier").classList.contains("verborgen"), false, "Settings remain open until save succeeds");
    await b.pump();
    equal(starts(), [{ cmd: "macos_apple_notizen_importieren" }], "Actual source button sends only the parameterless native selector");
    equal(w.document.querySelector("#einstellungen-schleier").classList.contains("verborgen"), true, "Canonical settings close clears its own parent modal before native selection");
    const review = w.App.macOSBetaPrepareAppleNotesImport(payload([item("from-source-button")]));
    equal(review.newCount, 1, "Native result can actually prepare after opening from Settings");
    await commit(b, review);
    equal(t.daten().notizen.at(-1).nativeAppleNotesImport.identifier, "from-source-button", "Source button flow reaches durable canonical append");
    t.oeffneTerminBlatt(null, "2026-05-10");
    const title = w.document.querySelector("#tb-titel");
    w.App.macOSBetaStartAppleNotesImport(); await b.pump();
    equal([title.isConnected, starts().length], [true, 1], "An unrelated open modal remains protected and prevents a second native picker");
  } finally { b.close(); }
}

for (const stage of ["before-start", "during-save"]) for (const fieldID of ["briefkasten-url", "briefkasten-kennwort"]) {
  const b = await context(), { w, t, messages } = b;
  try {
    t.oeffneEinstellungen(); w.document.querySelector("#einst-tab-sync").click();
    const account = { kontoArt: "nextcloud", davAktiv: false, briefkastenAktiv: false,
      url: "https://cloud.example.test", benutzer: "synthetic-user", kennwortVorhanden: false,
      revision: "1".repeat(64), zustand: "nicht_eingerichtet", fehler: "", fehlerCode: "none" };
    w.MacBeta.receive("baumBriefkastenStatus", account);
    const request = messages.filter(message => message.cmd === "eds_status" && message.requestId).at(-1);
    w.MacBeta.receive("edsStatus", { requestId: request.requestId, kalender: [], adressbuecher: [] });
    const button = () => w.document.querySelector("#macos-apple-notes-import");
    const visible = () => !w.document.querySelector("#einstellungen-schleier").classList.contains("verborgen");
    const starts = () => messages.filter(message => message.cmd === "macos_apple_notizen_importieren");
    const url = w.document.querySelector("#briefkasten-url"), password = w.document.querySelector("#briefkasten-kennwort");
    equal([url.disabled, password.disabled, button().disabled], [false, false, false], "Real DAV fields and Notes button are enabled with a valid native revision");
    t.daten().futureRoot.accountDraftRace = stage;
    const before = JSON.stringify(t.daten()), savesBefore = messages.filter(message => message.cmd === "speichern").length;
    if (stage === "during-save") button().click();
    const field = w.document.getElementById(fieldID), value = fieldID === "briefkasten-url"
      ? "https://unsaved.example.test/dav" : "public-synthetic-unsaved-app-password";
    field.value = value; field.dispatchEvent(new w.Event("input", { bubbles: true }));
    if (stage === "before-start") {
      button().click();
      equal(messages.filter(message => message.cmd === "speichern").length, savesBefore, "Existing account draft blocks Notes navigation/save before any document write");
    }
    await b.pump();
    equal([starts().length, visible(), field.isConnected, field.value, JSON.stringify(t.daten())], [0, true, true, value, before],
      "Notes start preserves account input without closing Settings or opening its picker: " + fieldID + "/" + stage);
    equal([url.value, password.value], fieldID === "briefkasten-url" ? [value, ""] : [account.url, value],
      "Password-only Notes case does not rely on a URL edit or changed-listener flag");
    equal(messages.filter(message => message.cmd === "baum_briefkasten_speichern").length, 0, "Notes start cannot save or discard the native account draft");
    equal(w.document.querySelector("#zettel").textContent, "Save or discard the account changes before importing.", "Blocked Notes start explains the pending account edit");
    if (stage === "before-start" && fieldID === "briefkasten-kennwort") {
      t.schliesseEinstellungen();
      equal([visible(), field.value], [false, value], "Conscious close can leave an old password in hidden DOM");
      w.App.macOSBetaStartAppleNotesImport(); await b.pump();
      equal(starts(), [{ cmd: "macos_apple_notizen_importieren" }], "Hidden stale password does not block a subsequent Notes menu start");
    }
  } finally { b.close(); }
}

{
  const b = await context(), { w, t } = b;
  try {
    const before = JSON.stringify(t.daten());
    const impossible = item("line-limit", { text: "line\n".repeat(20000) });
    const review = w.App.macOSBetaPrepareAppleNotesImport(payload([item("normal"), impossible], source(),
      [{ identifier: "locked", title: "Locked note", reasons: ["apple-note-password-protected"] }]));
    equal([review.newCount, review.excluded.length], [1, 2], "Native exclusions and renderer content limits stay visible");
    equal(review.excluded[1].reasons, ["canonical-note-content-would-change"], "Too many rendered lines are excluded without shortening source text");
    equal(JSON.stringify(t.daten()), before, "Exclusion preview does not mutate book");
    equal(w.App.macOSBetaCancelAppleNotesImport(review.token), { ok: true, cancelled: true }, "Cancel removes matching review");
    await rejects(w.App.macOSBetaCommitAppleNotesImport(review.token), /Invalid/, "Cancelled review cannot commit");
    throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([item("dup"), item("dup")])), /ambiguous/, "Duplicate source identifiers rejected");
    throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([item("dup")], source(), [{ identifier: "dup", title: "Excluded", reasons: ["failure"] }])), /ambiguous/, "Eligible and excluded same identity is ambiguous");
    for (const change of [value => { value.nativeRecord.passwordProtected = true; }, value => { value.nativeRecord.attachmentCount = 1; },
      value => { value.nativeRecord.failure = "read-failed"; }, value => { value.nativeRecord.plaintext = "Different"; },
      value => { value.nativeRecord.modified = null; }, value => { value.identity = ["a".repeat(64)]; }]) {
      const invalid = item("invalid"); change(invalid);
      throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([invalid])), /Invalid/, "Ineligible or inconsistent native record rejected");
    }
    throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload(Array.from({ length: 33 }, (_, i) => item("over-" + i)))), /Invalid/, "32-record bound");
    for (const [field, large] of [["title", "x".repeat(4097)], ["identifier", "x".repeat(16385)], ["text", "x".repeat(1024 * 1024 + 1)]]) {
      const invalid = item("size-limit", { [field]: large });
      if (field === "identifier") invalid.identifier = large;
      throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([invalid])), /Invalid/, "Native field byte bound: " + field);
    }
    const htmlLarge = item("html-limit"); htmlLarge.nativeRecord.bodyHTML = "x".repeat(1024 * 1024 + 1);
    throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([htmlLarge])), /Invalid/, "Native HTML byte bound");
    const byteLimit = payload([item("byte-limit")]); byteLimit.extra = "x".repeat(8 * 1024 * 1024);
    throws(() => w.App.macOSBetaPrepareAppleNotesImport(byteLimit), /byte limit/, "8MiB proposal bound before cloning");
    const escaped = "<&".repeat(524288), longReview = w.App.macOSBetaPrepareAppleNotesImport(payload([item("full-limit", { text: escaped })]));
    equal([longReview.newCount, longReview.preview[0].text.length], [1, escaped.length], "Full 1MiB literal text is reviewed without truncation");
    await commit(b, longReview);
    equal(t.daten().notizen.at(-1).text, escaped, "Full 1MiB literal text survives actual canonical save flow");
  } finally { b.close(); }
}

{
  const b = await context(), { w, t } = b;
  try {
    const stale = w.App.macOSBetaPrepareAppleNotesImport(payload([item("stale")]));
    t.daten().futureRoot.userEdit = "after preview";
    await rejects(w.App.macOSBetaCommitAppleNotesImport(stale.token), /stale/, "Book edit invalidates preview");
    const selected = w.App.macOSBetaPrepareAppleNotesImport(payload([item("selected")]));
    t.zustand().notizen.notizbuchId = "local-book";
    await rejects(w.App.macOSBetaCommitAppleNotesImport(selected.token), /stale/, "Changing selected notebook invalidates preview without changing DATEN");
    t.zustand().notizen.notizbuchId = "target-book";
    const renamed = w.App.macOSBetaPrepareAppleNotesImport(payload([item("renamed")]));
    t.daten().notizbuecher[1].name = "Renamed destination";
    await rejects(w.App.macOSBetaCommitAppleNotesImport(renamed.token), /stale/, "Changing target notebook content invalidates preview");
    const checkpoint = w.App.macOSBetaPrepareAppleNotesImport(payload([item("checkpoint")]));
    await rejects(commit(b, checkpoint, { snapshot: false }), /recovery/i, "Failed checkpoint refuses copy");
    equal(t.daten().notizen.length, 1, "No partial append after rejected review/checkpoint");
    const during = w.App.macOSBetaPrepareAppleNotesImport(payload([item("during-checkpoint")]));
    const waiting = w.App.macOSBetaCommitAppleNotesImport(during.token).then(() => null, error => error);
    t.zustand().notizen.notizbuchId = "local-book";
    await b.pump(); assert.match((await waiting).message, /stale/); checks++;
    equal(t.daten().notizen.length, 1, "Second target guard after checkpoint prevents append");
    t.zustand().notizen.notizbuchId = "target-book";
    const cancel = w.App.macOSBetaPrepareAppleNotesImport(payload([item("cancel-waiting")]));
    const cancelled = w.App.macOSBetaCommitAppleNotesImport(cancel.token).then(() => null, error => error);
    equal(w.App.macOSBetaCancelAppleNotesImport(cancel.token).cancelled, true, "Cancel during checkpoint prevents append");
    const newer = w.App.macOSBetaPrepareAppleNotesImport(payload([item("newer")]));
    await b.pump(); assert.match((await cancelled).message, /stale/); checks++;
    equal(w.App.macOSBetaCancelAppleNotesImport(newer.token).cancelled, true, "Old callback cannot discard newer proposal");
    const failedSave = w.App.macOSBetaPrepareAppleNotesImport(payload([item("unsaved")]));
    await rejects(commit(b, failedSave, { save: false }), /Imported notes remain unsaved/, "Final save failure is never copy success");
    equal(t.daten().notizen.length, 2, "Unsaved copy remains visible for save retry");
    t.speichereJetzt(); await b.pump();
    const retry = w.App.macOSBetaPrepareAppleNotesImport(payload([item("unsaved")]));
    equal([retry.newCount, retry.existingCount], [0, 1], "Save retry followed by repeat read cannot duplicate note");
    w.App.macOSBetaCancelAppleNotesImport(retry.token);
    const expired = w.App.macOSBetaPrepareAppleNotesImport(payload([item("expired")])); b.at("2026-05-01T12:05:01Z");
    await rejects(w.App.macOSBetaCommitAppleNotesImport(expired.token), /stale/, "Five-minute review deadline");
    const restoring = w.App.macOSBetaPrepareAppleNotesImport(payload([item("restoring")]));
    w.MacBeta.validateRestore(JSON.stringify(initial));
    await rejects(w.App.macOSBetaCommitAppleNotesImport(restoring.token), /stale/, "Restore fence blocks existing proposal");
    throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([item("blocked")])), /not available/, "Restore fence blocks preparation");
  } finally { b.close(); }
}

for (const stage of ["before-prepare", "before-commit", "during-checkpoint"]) {
  const b = await context(), { w, t } = b;
  try {
    let review, pending;
    if (stage !== "before-prepare") review = w.App.macOSBetaPrepareAppleNotesImport(payload([item("editor-race")]));
    if (stage === "during-checkpoint") pending = w.App.macOSBetaCommitAppleNotesImport(review.token).then(() => null, error => error);
    t.oeffneTerminBlatt(null, "2026-05-10");
    const title = w.document.querySelector("#tb-titel"); title.value = "Keep this open draft"; title.dispatchEvent(new w.Event("input", { bubbles: true }));
    if (stage === "before-prepare") throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([item("editor-race")])), /editor/, "Active editor blocks preview");
    else if (stage === "before-commit") await rejects(w.App.macOSBetaCommitAppleNotesImport(review.token), /stale/, "New editor blocks commit");
    else { await b.pump(); assert.match((await pending).message, /stale/); checks++; }
    equal([title.isConnected, title.value, t.daten().notizen.length], [true, "Keep this open draft", 1], "Editor draft survives import rejection: " + stage);
  } finally { b.close(); }
}

for (const stage of ["before-prepare", "before-commit", "during-checkpoint"]) {
  const b = await context(), { w, t } = b;
  try {
    t.zustand().notizen.notizbuchId = "local-book"; t.zustand().notizen.auswahlId = "local-note";
    await t.wechsel("notizen"); await b.pump();
    const surface = w.document.querySelector("#notiz-text");
    assert.ok(surface, "Actual canonical contenteditable note opened"); checks++;
    let review, pending;
    if (stage !== "before-prepare") review = w.App.macOSBetaPrepareAppleNotesImport(payload([item("pending-note")]));
    if (stage === "during-checkpoint") pending = w.App.macOSBetaCommitAppleNotesImport(review.token).then(() => null, error => error);
    surface.textContent = "Keep this pending note fragment";
    surface.dispatchEvent(new w.Event("input", { bubbles: true }));
    equal(t.daten().notizen[0].text, "Local text", "Real note input is still pending outside DATEN");
    if (stage === "before-prepare") throws(() => w.App.macOSBetaPrepareAppleNotesImport(payload([item("pending-note")])), /editor/, "Pending note snapshot blocks preview");
    else if (stage === "before-commit") await rejects(w.App.macOSBetaCommitAppleNotesImport(review.token), /stale/, "Pending note snapshot blocks commit");
    else { await b.pump(); assert.match((await pending).message, /stale/); checks++; }
    equal([surface.isConnected, surface.textContent, t.daten().notizen.length], [true, "Keep this pending note fragment", 1], "Pending note editor retained without import: " + stage);
    t.sichereNotizSnapshot();
    equal(t.daten().notizen[0].text, "Keep this pending note fragment", "Original note callback remains usable after rejection");
  } finally { b.close(); }
}

// #778: exercise the public renderer hook after the real canonical append.
for (const language of ["en", "de"]) {
  const b = await context(), { w, t, messages } = b;
  const appearance = w.MagnolieAppearance;
  try {
    w.MagnolieI18n.setLocale(language);
    t.speichereJetzt(); await b.pump();
    const original = JSON.stringify(t.daten().notizen), originalCount = t.daten().notizen.length;
    const review = w.App.macOSBetaPrepareAppleNotesImport(payload([item("render-failure")]));
    try {
      w.MagnolieAppearance = { ...appearance, update() { throw new Error("Synthetic renderer failure after append"); } };
      await rejects(commit(b, review), language === "de"
        ? /Notizkopien wurden hinzugefügt, ihre Speicherung wurde jedoch nicht bestätigt\..*Synthetic renderer failure after append/
        : /Note copies were added, but saving was not confirmed\..*Synthetic renderer failure after append/,
        "Actual renderer failure explains local mutation and unconfirmed persistence");
    } finally { w.MagnolieAppearance = appearance; }
    equal(t.daten().notizen.length, originalCount + 1, "Added copy survives renderer failure for save retry");
    equal(JSON.stringify(t.daten().notizen.slice(0, originalCount)), original, "Renderer failure preserves all pre-existing records and local edits");
    equal(t.daten().notizen.at(-1).nativeAppleNotesImport.identifier, "render-failure", "Renderer failure retains exact native provenance");
    t.speichereJetzt(); await b.pump();
    const saved = JSON.parse(messages.filter(message => message.cmd === "speichern").at(-1).text);
    equal(saved.notizen, t.daten().notizen, "Actual retry save contains both existing records and the added copy");
    const retry = w.App.macOSBetaPrepareAppleNotesImport(payload([item("render-failure")]));
    equal([retry.newCount, retry.existingCount], [0, 1], "Save retry preserves provenance and prevents duplicate import");
    w.App.macOSBetaCancelAppleNotesImport(retry.token);
    w.MacBeta.receive("init", { daten: saved, neu: false, regional: { language, timeZone: "UTC" } });
    t.zustand().notizen.notizbuchId = "target-book"; t.zustand().notizen.auswahlId = null;
    await b.pump();
    const reopened = w.App.macOSBetaPrepareAppleNotesImport(payload([item("render-failure")]));
    equal([reopened.newCount, reopened.existingCount], [0, 1], "Reopened retry-save bytes still prevent duplicate import");
    w.App.macOSBetaCancelAppleNotesImport(reopened.token);
  } finally { w.MagnolieAppearance = appearance; b.close(); }
}

console.log(`Mac Apple Notes plaintext copy: ${checks} projected UI checks; synthetic native records/transport, not AppleScript or macOS evidence.`);
