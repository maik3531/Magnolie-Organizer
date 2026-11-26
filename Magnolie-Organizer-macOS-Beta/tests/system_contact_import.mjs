import assert from "node:assert/strict";
import fs from "node:fs";
import { createHash, webcrypto } from "node:crypto";
import { boot, tick } from "./ui_harness.mjs";

const clone = value => JSON.parse(JSON.stringify(value));
const digest = value => createHash("sha256").update(JSON.stringify(value)).digest("hex");
const fixture = JSON.parse(fs.readFileSync(new URL("../Tests/BetaCoreTests/Fixtures/system-contact-copy.json", import.meta.url), "utf8"));
let checks = 0;
const equal = (actual, expected, label) => { assert.deepEqual(clone(actual), clone(expected), label); checks++; };
const ok = (value, label) => { assert.ok(value, label); checks++; };
const throws = (action, pattern, label) => { assert.throws(action, pattern, label); checks++; };
const rejects = async (action, pattern, label) => { await assert.rejects(action, pattern, label); checks++; };
const initial = { termine: [], aufgaben: [],
  kontakte: [{ id: "local-contact", uid: "independent-local-uid", vorname: "Local", nachname: "Existing", email: "ada@example.test",
    telefone: [{ wert: "+44 20 7946 0958", typen: ["HOME", "VOICE"] }], future: { keep: [1, 2] } }],
  jahrestage: [{ id: "namesake", uid: "namesake-uid", name: "Ada Lovelace", datum: "1990-02-28", typ: "birthday", kontaktId: "", future: { keep: 3 } }],
  notizen: [{ id: "local-note", titel: "Local note", text: "Original note", html: "Original note", notizbuchId: "local-book" }],
  notizgruppen: [{ id: "group", name: "Notebooks" }], notizbuecher: [{ id: "local-book", gruppeId: "group", name: "Notes" }],
  futureRoot: { keep: ["opaque", { value: 17 }] }, einstellungen: { allgemein: { handbuchHinweisGezeigt: true } } };
const source = (id = "container-one") => ({ ...clone(fixture.source), sourceUID: "macos-contacts:" + Buffer.from(id).toString("base64"), containerID: id });
function item(identifier = "contact-one", { origin = source(), change = () => {} } = {}) {
  // Shared full reader/Core-shaped fixture. Revisions below are synthetic test
  // tokens: this suite executes canonical JS, not Swift or native Contacts.
  const nativeRecord = clone(fixture.records[0]); nativeRecord.identifier = identifier;
  const contact = clone(fixture.expectedContact);
  const value = { identifier, title: nativeRecord.title, contact, nativeRecord, notices: fixture.expectedNotices.slice() };
  change(value);
  return { ...value, identity: identifier === "contact-one" && origin.containerID === "container-one"
    ? fixture.expectedIdentity : digest([origin.sourceUID, identifier]), revision: digest([origin, value.nativeRecord, value.contact]) };
}
function payload(contacts, origin = source(), excluded = []) {
  return { version: 1, source: origin, contacts, excluded, snapshotRevision: digest([origin, contacts, excluded]) };
}
async function context(book = initial) {
  const b = await boot(process.argv[2], Date.parse("2026-05-01T12:00:00Z")), seen = new Set();
  const { w, t, messages } = b;
  Object.defineProperty(w.crypto, "subtle", { value: webcrypto.subtle });
  w.MacBeta.receive("init", { daten: clone(book), neu: false, regional: { language: "en", timeZone: "UTC" } });
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
  const pending = b.w.App.macOSBetaCommitContactImport(review.token).then(value => ({ value }), error => ({ error }));
  await b.pump(options); const outcome = await pending;
  if (outcome.error) throw outcome.error;
  return outcome.value;
}
function changeInput(w, field, value) {
  field.value = value; field.dispatchEvent(new w.Event("input", { bubbles: true }));
}
async function editContact(b, contact) {
  if (b.t.zustand().sektion === "adressen") await b.t.wechsel("planer");
  b.t.zustand().adressen.auswahlId = contact.id; b.t.zustand().adressen.modus = "bearbeiten";
  await b.t.wechsel("adressen");
  const form = b.w.document.querySelector(".kontakt-formular"); ok(form, "Actual canonical contact editor opens"); return form;
}
async function saveContact(b, form) {
  const save = [...form.querySelectorAll(".kontakt-form-knoepfe button")].find(button => button.textContent === "Save changes");
  ok(save, "Actual canonical save action exists"); save.click(); b.t.speichereJetzt(); await b.pump();
  ok(!form.isConnected, "Successful canonical edit leaves the editor");
}

let reopened;
{
  const b = await context(), { w, t, messages } = b;
  try {
    t.daten().einstellungen.futureContact = { keep: true }; t.daten().gesundheit.futureContact = [1, 2];
    t.speichereJetzt(); await b.pump();
    const before = JSON.stringify(t.daten()), local = JSON.stringify(t.daten().kontakte[0]);
    const annuals = JSON.stringify(t.daten().jahrestage), other = JSON.stringify([t.daten().einstellungen, t.daten().gesundheit, t.daten().notizen]);
    const incoming = payload([item(), item("second")]), review = w.App.macOSBetaPrepareContactImport(incoming);
    equal(JSON.stringify(t.daten()), before, "Preparation never modifies any existing document field");
    equal([review.newCount, review.existingCount, review.changedCount, review.addressbookTitle], [2, 0, 0, "Contacts"], "Full actual Core-shape fixture normalizes as two additive copies");
    equal(review.source, source(), "Review names the exact selected native container");
    equal(review.preview[0].notices, [...fixture.expectedNotices, "native-contact-email-case-normalized"].sort(), "Only explicit email-case conversion is added to Core notices");
    equal(review.preview[0].photo, fixture.expectedContact.foto, "Preview uses the exact original photo data, without re-encoding");
    for (const text of ["Ada", "Lovelace", "Analytical Society", "+44 20 7946 0958", "+44 7700 900123", "Studio", "+44 20 7946 0959",
      "ada@example.test", "Research desk", "research@example.test", "12 St James Square\nSecond floor", "London", "Greater London", "SW1Y 4LB", "United Kingdom", "https://example.test/ada?x=1&y=2"])
      ok(review.preview[0].text.includes(text), "Full active value is reviewable: " + text);
    ok(review.preview[0].text.includes("Birthday stored with this contact; no calendar entry."), "Birthday copy limitation is shown with the active date");
    incoming.contacts[0].contact.vorname = "Outside mutation"; review.preview[0].text = "Outside mutation";
    throws(() => w.App.macOSBetaPrepareContactImport(payload([item("parallel")])), /already/, "Only one review may be active");
    await rejects(w.App.macOSBetaCommitContactImport("wrong-token"), /Invalid/, "Wrong token does not clear the current review");
    let finished = false;
    const pending = w.App.macOSBetaCommitContactImport(review.token).then(value => { finished = true; return value; });
    equal(JSON.stringify(t.daten()), before, "No append before recovery checkpoint acknowledgement");
    await b.pump({ ackSaves: false });
    equal([finished, t.daten().kontakte.length], [false, 3], "Appending awaits the actual durable save acknowledgement");
    equal(w.App.macOSBetaCancelContactImport(review.token).cancelled, false, "A save in progress cannot be cancelled or replaced");
    await b.pump(); equal((await pending).count, 2, "Durable save returns exact appended count");
    equal(JSON.stringify(t.daten().kontakte[0]), local, "Existing same-email/phone contact is not matched or modified");
    equal(JSON.stringify(t.daten().jahrestage), annuals, "No birthday creation or namesake anniversary assignment");
    equal(JSON.stringify([t.daten().einstellungen, t.daten().gesundheit, t.daten().notizen]), other, "All unrelated domains remain exact");
    const copy = t.daten().kontakte[1];
    equal([copy.vorname, copy.geburtstag, copy.geburtstagJahrUnbekannt], ["Ada", "--02-29", true], "Private proposal retains active leap-day birthday without inventing a year");
    equal(copy.nativeContactRecord, fixture.records[0], "All public raw fields, labels and original email spellings are retained inertly");
    equal(copy.nativeContactImport, { version: 1, identity: fixture.expectedIdentity, sourceUID: source().sourceUID, containerID: source().containerID,
      sourceTitle: source().title, nativeType: source().nativeType, identifier: "contact-one", revision: item().revision,
      copyKind: "public-fields", revisionCoverage: "serialized-fields-only", birthdayPolicy: "contact-only" }, "Complete versioned provenance contract retained");
    equal([copy.sync, copy.syncQuellen, copy.importBindungen], [false, {}, []], "Copy metadata creates no synchronization or provider binding");
    ok(/^mag-.+@magnolie-organizer$/.test(copy.uid) && copy.uid !== t.daten().kontakte[2].uid, "Fresh independent canonical local UIDs");
    equal(new Set(t.daten().kontakte.map(value => value.id)).size, 3, "Fresh independent local IDs");
    const normalized = t.normalisiere(clone(t.daten()));
    equal(normalized.jahrestage, t.daten().jahrestage, "Reload normalization neither matches nor creates birthday annuals");
    equal(normalized.kontakte[1], copy, "Full copied contact is a canonical normalization fixed point");
    await rejects(w.App.macOSBetaCommitContactImport(review.token), /Invalid/, "Consumed review cannot be replayed");
    copy.vorname = "Edited locally"; copy.emailEintraege[0].wert = "local@example.test";
    copy.email = "local@example.test"; copy.emails[0] = "local@example.test"; copy.future = { keep: 42 };
    const edited = JSON.stringify(copy), repeat = w.App.macOSBetaPrepareContactImport(payload([item(), item("second")]));
    equal([repeat.newCount, repeat.existingCount, repeat.changedCount], [0, 2, 0], "Unchanged native source is recognized despite local edits");
    equal((await commit(b, repeat)).count, 0, "An empty append review is valid");
    equal(JSON.stringify(copy), edited, "Repeated native read never overwrites local edits");
    const changed = item("contact-one", { change: value => { value.nativeRecord.fields.jobTitle = "Changed native role"; } });
    const sourceChange = w.App.macOSBetaPrepareContactImport(payload([changed]));
    equal([sourceChange.newCount, sourceChange.changedCount, sourceChange.changedPreview[0].title], [0, 1, changed.title], "Source revision changes are visible and not overwritten");
    await commit(b, sourceChange); equal(JSON.stringify(copy), edited, "Changed native fields leave local record exact");
    const otherSource = source("another-container"), foreign = w.App.macOSBetaPrepareContactImport(payload([item("contact-one", { origin: otherSource })], otherSource));
    equal(foreign.newCount, 1, "Same native contact identifier in another container is independent");
    await commit(b, foreign);
    const conflict = item("foreign-id"); conflict.identity = fixture.expectedIdentity;
    throws(() => w.App.macOSBetaPrepareContactImport(payload([conflict])), /identity/, "Foreign record cannot reuse an existing identity");
    t.daten().kontakte.push({ ...clone(copy), id: "ambiguous-local" });
    throws(() => w.App.macOSBetaPrepareContactImport(payload([item()])), /Multiple/, "Multiple local copies of one provenance fail closed"); t.daten().kontakte.pop();
    const trash = t.daten().kontakte.splice(2, 1)[0];
    t.daten().papierkorb.push({ id: "contact-trash", art: "kontakt", eintrag: clone(trash), name: "Copy", geloescht: Date.now() });
    const trashed = w.App.macOSBetaPrepareContactImport(payload([item("second")]));
    equal([trashed.newCount, trashed.excluded[0].reasons[0]], [0, "local-contact-copy-in-trash"], "Deliberately deleted copy is never silently restored");
    w.App.macOSBetaCancelContactImport(trashed.token);
    equal(messages.filter(message => message.cmd === "sync" || message.cmd === "eds_speichern").length, 0, "Copying issues no native source writes");
    reopened = clone(t.daten());
  } finally { b.close(); }
}

{
  const b = await context(reopened), { w, t } = b;
  try {
    const annuals = JSON.stringify(t.daten().jahrestage), copy = t.daten().kontakte[1];
    const review = w.App.macOSBetaPrepareContactImport(payload([item(), item("second")]));
    equal([review.newCount, review.existingCount, review.excluded[0].reasons[0]], [0, 1, "local-contact-copy-in-trash"], "Actual initialization retains active and trash identities");
    await commit(b, review);
    equal(JSON.stringify(t.daten().jahrestage), annuals, "Actual reopen creates no birthday links");
    let form = await editContact(b, copy);
    const birthday = w.document.querySelector("#kontakt-geburtstag");
    ok(birthday && birthday.dataset.datumIso === "--02-29", "Real editor exposes contact-only birthday with no invented year");
    equal(form.querySelectorAll(".kontakt-ereignis-datum").length, 1, "No synthetic yearly entry is added to the ordinary anniversary editor");
    for (const invalid of ["31.02.2000", "12."]) {
      const before = JSON.stringify(copy);
      changeInput(w, birthday, invalid); birthday.dispatchEvent(new w.Event("change", { bubbles: true }));
      const displayed = birthday.value;
      [...form.querySelectorAll(".kontakt-form-knoepfe button")].find(button => button.textContent === "Save changes").click();
      equal([form.isConnected, birthday.value, JSON.stringify(copy)], [true, displayed, before], "Invalid/incomplete date cannot silently clear the old birthday: " + invalid);
      ok(w.document.activeElement === birthday, "Invalid birthday keeps focus in the actual date field");
      equal(w.document.querySelector("#zettel").textContent, "Please enter a valid birth date.", "Invalid birthday is explained without saving");
    }
    changeInput(w, birthday, "29.02."); birthday.dispatchEvent(new w.Event("change", { bubbles: true }));
    equal(birthday.dataset.datumIso, "--02-29", "Actual date field accepts a yearless leap day after the invalid drafts");
    changeInput(w, w.document.querySelector("#kontakt-notiz"), "Edited in the actual contact form");
    await saveContact(b, form);
    equal([copy.notiz, copy.geburtstag, copy.geburtstagJahrUnbekannt], ["Edited in the actual contact form", "--02-29", true], "Ordinary text edit preserves standalone birthday");
    equal(JSON.stringify(t.daten().jahrestage), annuals, "Text edit cannot assign or change namesake yearly entry");
    ok(w.document.querySelector("#inhalt-rechts").textContent.includes("Birthday"), "Contact card shows the active contact-only birthday");
    const nativeBefore = JSON.stringify(copy.nativeContactRecord);
    for (const [date, unknown] of [["1988-02-29", false], ["--02-29", true], ["1604-02-29", false], ["", false]]) {
      form = await editContact(b, copy);
      const field = w.document.querySelector("#kontakt-geburtstag");
      changeInput(w, field, date); field.dispatchEvent(new w.Event("change", { bubbles: true }));
      await saveContact(b, form);
      equal([copy.geburtstag, copy.geburtstagJahrUnbekannt], [date, unknown], "Explicit local birthday edit: " + (date || "clear"));
      equal(JSON.stringify(t.daten().jahrestage), annuals, "Birthday edit remains contact-only: " + (date || "clear"));
      equal(t.normalisiere(clone(t.daten())).kontakte[1].geburtstag, date, "Edited birthday survives canonical reload: " + (date || "clear"));
    }
    equal(JSON.stringify(copy.nativeContactRecord), nativeBefore, "Local birthday edits never rewrite source evidence");
    copy.vorname = "Ada";
    const ods = t.adressenOdsNutzlast([copy], ["geburtstag"]);
    equal([ods.spalten, ods.zeilen], [[], [[]]], "ODS export cannot fill a deliberately empty copied birthday from a namesake annual");
    const ordinaryODS = t.adressenOdsNutzlast([{ id: "unmarked-namesake", vorname: "Ada", nachname: "Lovelace" }], ["geburtstag"]);
    equal(ordinaryODS.spalten.length, 1, "Ordinary contact ODS fallback remains unchanged");
    const ordinary = t.normalisiere({ kontakte: [{ id: "ordinary", vorname: "Ordinary", nachname: "Birthday", geburtstag: "--02-29" }] });
    equal([ordinary.jahrestage.length, ordinary.jahrestage[0].kontaktId, ordinary.jahrestage[0].datum], [1, "ordinary", "--02-29"], "Unmarked canonical contacts retain their normal automatic birthday behavior");
  } finally { b.close(); }
}

{
  const b = await context(), { w, t } = b;
  try {
    const losses = [
      ["trim-email", value => { value.contact.emailEintraege[0].wert = " Ada@Example.Test"; }],
      ["email-wrapper", value => { value.contact.emailEintraege[0].wert = "Ada <Ada@Example.Test>"; }],
      ["email-invalid", value => { value.contact.emailEintraege[0].wert = "ada@example.invalid"; }],
      ["duplicate-email", value => { value.contact.emailEintraege.push(clone(value.contact.emailEintraege[0])); }],
      ["trim-phone", value => { value.contact.telefone[0].wert += " "; }],
      ["tel-prefix", value => { value.contact.telefone[0].wert = "tel:" + value.contact.telefone[0].wert; }],
      ["duplicate-phone", value => { value.contact.telefone.push(clone(value.contact.telefone[0])); }],
      ["private-phone", value => { value.contact.telefone[0].label = "private"; }],
      ["privat-email", value => { value.contact.emailEintraege[0].label = "privat"; }],
      ["long-label", value => { value.contact.telefone[0].label = "x".repeat(81); }],
      ["trim-address", value => { value.contact.anschriften[0].ort += " "; }],
      ["duplicate-address", value => { value.contact.anschriften.push(clone(value.contact.anschriften[0])); }],
      ["unsupported-photo", value => { value.contact.foto = "data:image/tiff;base64,AAAA"; }],
      ["invalid-date", value => { value.contact.geburtstag = "--02-30"; }]
    ].map(([id, change]) => item(id, { change }));
    for (const url of ["https://example.test/path with space", "https://user:secret@example.test", "https://example.test/\u202Ehidden",
      "https://example.test/" + "a".repeat(4096), "https://[broken.example.test/", "https://example.test\\path"]) {
      losses.push(item("url-" + losses.length, { change: value => {
        value.nativeRecord.fields.urlAddresses[0].value = url;
        value.contact.vcardRoundtrip[value.contact.vcardRoundtrip.length - 1] = "URL:" + url;
      } }));
    }
    const unicode = item("unicode", { change: value => {
      value.contact.vorname = "Cafe\u0301 👩‍💻"; value.nativeRecord.fields.givenName = value.contact.vorname;
    } });
    const normalizedURL = item("url-active", { change: value => {
      value.nativeRecord.fields.urlAddresses[0].value = "HTTPS://EXAMPLE.TEST:443/KeepCase?X=1";
      value.contact.vcardRoundtrip[value.contact.vcardRoundtrip.length - 1] = "URL:HTTPS://EXAMPLE.TEST:443/KeepCase?X=1";
    } });
    const year1604 = item("native-1604", { change: value => {
      value.contact.geburtstag = "1604-02-29"; value.contact.geburtstagJahrUnbekannt = false;
      value.nativeRecord.fields.birthday.year = 1604;
    } });
    const before = JSON.stringify(t.daten());
    const review = w.App.macOSBetaPrepareContactImport(payload([unicode, normalizedURL, year1604, ...losses], source(),
      [{ identifier: "reader-excluded", title: "Unavailable contact", reasons: ["native-contact-read-failed"] }]));
    equal(review.newCount, 3, "Compatible Unicode, URL opening normalization and explicit native year 1604 remain eligible");
    equal(review.excluded.map(value => value.identifier), ["reader-excluded", ...losses.map(value => value.identifier)], "Every real field loss remains visible per contact");
    equal(review.excluded.slice(1).every(value => value.reasons[0] === "canonical-contact-content-would-change"), true, "Only explicit email-case conversion is allowed");
    equal(JSON.stringify(t.daten()), before, "All exclusions are review-only");
    await commit(b, review);
    equal(t.daten().kontakte[1].vorname, "Cafe\u0301 👩‍💻", "No NFC coercion or Unicode replacement");
    equal(t.daten().kontakte[2].vcardRoundtrip.at(-1), "URL:HTTPS://EXAMPLE.TEST:443/KeepCase?X=1", "Opening URL normalization never rewrites original retained URL");
    equal([t.daten().kontakte[3].geburtstag, t.daten().kontakte[3].geburtstagJahrUnbekannt], ["1604-02-29", false], "Real native-shaped 1604 proposal preserves its explicit year");
    equal(t.normalisiere(clone(t.daten())).kontakte[3].geburtstag, "1604-02-29", "Explicit native year 1604 survives actual canonical reload");
    throws(() => w.App.macOSBetaPrepareContactImport(payload([item("dup"), item("dup")])), /ambiguous/, "Repeated source identifiers rejected");
    throws(() => w.App.macOSBetaPrepareContactImport(payload([item("dup")], source(), [{ identifier: "dup", title: "Excluded", reasons: ["failure"] }])), /ambiguous/, "Included/excluded duplicate source identity rejected");
    for (const change of [value => { value.identity = ["a".repeat(64)]; }, value => { value.nativeRecord.identifier = "different"; },
      value => { value.nativeRecord.failure = "read failed"; }, value => { value.contact.sync = true; },
      value => { value.nativeRecord.fields.note = "unrequested private note"; }, value => { value.nativeRecord.fields.unavailableKeys.push("birthday"); },
      value => { value.nativeRecord.fields.givenName = "\uD800"; }, value => { value.contact.vcardRoundtrip.push("NOTE:unreviewed"); },
      value => { value.contact.vcardRoundtrip.push("URL:https://example.test\nNOTE:injected"); }]) {
      const invalid = item("invalid"); change(invalid);
      throws(() => w.App.macOSBetaPrepareContactImport(payload([invalid])), /Invalid/, "Malformed/ineligible/foreign-field native proposal refused");
    }
    const invalidSource = source(); invalidSource.containerID = "another-container";
    throws(() => w.App.macOSBetaPrepareContactImport(payload([item()], invalidSource)), /Invalid/, "Container and base64 source UID must agree byte for byte");
    const unicodeSource = source("Cafe\u0301 🪷"), unicodeReview = w.App.macOSBetaPrepareContactImport(payload([item("unicode-source", { origin: unicodeSource })], unicodeSource));
    equal(unicodeReview.source, unicodeSource, "Source identity preserves non-ASCII UTF-8 bytes"); w.App.macOSBetaCancelContactImport(unicodeReview.token);
    throws(() => w.App.macOSBetaPrepareContactImport(payload(Array.from({ length: 101 }, (_, i) => item("many-" + i)))), /Invalid/, "100 total selected contacts bound");
    for (const [field, large] of [["title", "x".repeat(4097)], ["identifier", "x".repeat(16385)]]) {
      const invalid = item("too-large"); invalid[field] = large;
      throws(() => w.App.macOSBetaPrepareContactImport(payload([invalid])), /Invalid/, "Native identity/title bound: " + field);
    }
    const tooMany = item("too-many-values"); tooMany.nativeRecord.fields.phoneNumbers = Array(1001).fill(tooMany.nativeRecord.fields.phoneNumbers[0]);
    throws(() => w.App.macOSBetaPrepareContactImport(payload([tooMany])), /Invalid/, "Per native-field value count bound");
    const largeScalar = item("scalar"); largeScalar.nativeRecord.fields.jobTitle = "é".repeat(32769);
    throws(() => w.App.macOSBetaPrepareContactImport(payload([largeScalar])), /Invalid/, "Scalar bound is UTF-8 bytes, not just JS length");
    const oversized = payload([item()]); oversized.extra = "x".repeat(16 * 1024 * 1024);
    throws(() => w.App.macOSBetaPrepareContactImport(oversized), /byte limit/, "16MiB serialized payload bound before cloning");
    const hundred = w.App.macOSBetaPrepareContactImport(payload(Array.from({ length: 100 }, (_, i) => item("allowed-" + i))));
    equal(hundred.newCount, 100, "Exactly 100 source-shaped contacts are accepted without name/email collapse"); w.App.macOSBetaCancelContactImport(hundred.token);
  } finally { b.close(); }
}

{
  const b = await context(), { w, t } = b;
  try {
    const stale = w.App.macOSBetaPrepareContactImport(payload([item("stale")])); t.daten().futureRoot.userEdit = "after preview";
    await rejects(w.App.macOSBetaCommitContactImport(stale.token), /stale/, "Any document edit invalidates the review");
    const checkpoint = w.App.macOSBetaPrepareContactImport(payload([item("checkpoint")]));
    await rejects(commit(b, checkpoint, { snapshot: false }), /recovery/i, "Failed checkpoint cannot append");
    equal(t.daten().kontakte.length, 1, "Rejected review/checkpoint leaves all original contacts");
    const during = w.App.macOSBetaPrepareContactImport(payload([item("during-checkpoint")]));
    const waiting = w.App.macOSBetaCommitContactImport(during.token).then(() => null, error => error);
    t.daten().futureRoot.duringCheckpoint = true;
    await b.pump(); ok(/stale/.test((await waiting).message), "Document binding is rechecked after checkpoint");
    equal(t.daten().kontakte.length, 1, "Checkpoint race never appends to a changed book");
    const cancel = w.App.macOSBetaPrepareContactImport(payload([item("cancel-checkpoint")]));
    const cancelled = w.App.macOSBetaCommitContactImport(cancel.token).then(() => null, error => error);
    equal(w.App.macOSBetaCancelContactImport(cancel.token).cancelled, true, "Matching cancellation during checkpoint prevents append");
    const newer = w.App.macOSBetaPrepareContactImport(payload([item("newer")]));
    await b.pump(); ok(/stale/.test((await cancelled).message), "Cancelled old checkpoint cannot commit");
    equal(w.App.macOSBetaCancelContactImport(newer.token).cancelled, true, "Old callback cannot discard newer proposal");
    const failedSave = w.App.macOSBetaPrepareContactImport(payload([item("unsaved")]));
    await rejects(commit(b, failedSave, { save: false }), /Imported contacts remain unsaved/, "Failed document save is never a successful import");
    equal(t.daten().kontakte.length, 2, "Unsaved appended contact remains visible for a save retry");
    t.speichereJetzt(); await b.pump();
    const retry = w.App.macOSBetaPrepareContactImport(payload([item("unsaved")]));
    equal([retry.newCount, retry.existingCount], [0, 1], "Successful save retry then repeated read creates no duplicate"); w.App.macOSBetaCancelContactImport(retry.token);
    const expired = w.App.macOSBetaPrepareContactImport(payload([item("expired")])); b.at("2026-05-01T12:05:01Z");
    await rejects(w.App.macOSBetaCommitContactImport(expired.token), /stale/, "Review expires after five minutes");
    const restoring = w.App.macOSBetaPrepareContactImport(payload([item("restoring")])); w.MacBeta.validateRestore(JSON.stringify(initial));
    await rejects(w.App.macOSBetaCommitContactImport(restoring.token), /stale/, "Restore fence invalidates prepared contact review");
    throws(() => w.App.macOSBetaPrepareContactImport(payload([item("blocked")])), /not available/, "Restore fence blocks preparation");
  } finally { b.close(); }
}

for (const stage of ["prepared", "checkpoint", "saving"]) {
  const b = await context(), { w, t, messages } = b;
  try {
    const old = w.App.macOSBetaPrepareContactImport(payload([item("old-generation")]));
    const pending = stage === "prepared" ? null : w.App.macOSBetaCommitContactImport(old.token).then(() => null, error => error);
    if (stage === "saving") await b.pump({ ackSaves: false });
    w.MacBeta.receive("init", { daten: clone(initial), neu: false, regional: { language: "en", timeZone: "UTC" } });
    if (stage === "prepared") {
      const current = w.App.macOSBetaPrepareContactImport(payload([item("new-generation")]));
      await rejects(w.App.macOSBetaCommitContactImport(old.token), /Invalid/, "Obsolete generation cannot consume new review");
      equal(w.App.macOSBetaCancelContactImport(current.token).cancelled, true, "Idle old review releases a new initialized document");
    } else {
      throws(() => w.App.macOSBetaPrepareContactImport(payload([item("wait")])), /already/, "In-flight review remains owned across initialization: " + stage);
      w.App.macOSBetaStartContactImport();
      equal(messages.filter(message => message.cmd === "macos_kontakte_importieren").length, 0, "In-flight state cannot open another native picker");
      await b.pump(); const failure = await pending;
      ok(/stale|document changed/i.test(failure.message), "Old generation's completion is rejected: " + stage);
      equal(/copies were added|remain unsaved|saving was not confirmed/i.test(failure.message), false,
        "Pre-append rejection or observed save ACK keeps its specific document-change diagnosis: " + stage);
      equal(t.daten().kontakte.length, 1, "Replacement document never receives old-generation candidates");
    }
  } finally { b.close(); }
}

for (const kind of ["contact", "note", "modal"]) for (const stage of ["before-prepare", "before-commit", "during-checkpoint"]) {
  const b = await context(), { w, t } = b;
  try {
    if (kind === "contact") await editContact(b, t.daten().kontakte[0]);
    if (kind === "note") {
      t.zustand().notizen.notizbuchId = "local-book"; t.zustand().notizen.auswahlId = "local-note"; await t.wechsel("notizen"); await b.pump();
    }
    let review, pending;
    if (stage !== "before-prepare") review = w.App.macOSBetaPrepareContactImport(payload([item("draft-race")]));
    if (stage === "during-checkpoint") pending = w.App.macOSBetaCommitContactImport(review.token).then(() => null, error => error);
    let field;
    if (kind === "contact") { field = w.document.querySelector("#kontakt-notiz"); changeInput(w, field, "Pending contact draft"); }
    if (kind === "note") {
      field = w.document.querySelector("#notiz-text"); field.textContent = "Pending note fragment"; field.dispatchEvent(new w.Event("input", { bubbles: true }));
      equal(t.daten().notizen[0].text, "Original note", "Real note fragment is still outside DATEN");
    }
    if (kind === "modal") { t.oeffneTerminBlatt(null, "2026-05-10"); field = w.document.querySelector("#tb-titel"); changeInput(w, field, "Pending appointment draft"); }
    const displayed = kind === "note" ? field.textContent : field.value;
    if (stage === "before-prepare") throws(() => w.App.macOSBetaPrepareContactImport(payload([item("draft-race")])), /editor/, "Open draft blocks preparation: " + kind);
    else if (stage === "before-commit") await rejects(w.App.macOSBetaCommitContactImport(review.token), /stale/, "New draft blocks commit: " + kind);
    else { await b.pump(); ok(/stale/.test((await pending).message), "Draft race is rechecked after checkpoint: " + kind); }
    equal([field.isConnected, kind === "note" ? field.textContent : field.value, t.daten().kontakte.length], [true, displayed, 1], "Draft DOM and text survive rejection: " + kind + "/" + stage);
    if (kind === "note") { t.sichereNotizSnapshot(); equal(t.daten().notizen[0].text, displayed, "Pending note callback remains usable"); }
  } finally { b.close(); }
}

{
  const b = await context(), { w, t, messages } = b;
  try {
    t.oeffneEinstellungen(); w.document.querySelector("#einst-tab-sync").click();
    const request = messages.filter(message => message.cmd === "eds_status" && message.requestId).at(-1);
    const button = () => w.document.querySelector("#macos-system-contact-import");
    const starts = () => messages.filter(message => message.cmd === "macos_kontakte_importieren");
    equal(button().disabled, true, "Actual System Sources contact button waits for its source request");
    button().click(); equal(starts().length, 0, "Pending source request prevents another picker");
    w.MacBeta.receive("edsStatus", { requestId: "foreign", kalender: [], adressbuecher: [] });
    equal(button().disabled, true, "Unrelated source reply cannot enable contact button");
    w.MacBeta.receive("edsStatus", { requestId: request.requestId, kalender: [], adressbuecher: [] });
    equal(button().disabled, false, "Matching response enables contact button");
    t.daten().futureRoot.buttonEdit = true; button().click();
    equal(starts().length, 0, "Native picker waits for save acknowledgement");
    equal(w.document.querySelector("#einstellungen-schleier").classList.contains("verborgen"), false, "Settings remain until save succeeds");
    await b.pump();
    equal(starts(), [{ cmd: "macos_kontakte_importieren" }], "Actual contact button sends only parameterless native selector");
    equal(w.document.querySelector("#einstellungen-schleier").classList.contains("verborgen"), true, "Canonical close removes only the parent settings modal");
    const review = w.App.macOSBetaPrepareContactImport(payload([item("from-button")])); await commit(b, review);
    equal(t.daten().kontakte.at(-1).nativeContactImport.identifier, "from-button", "Actual button flow reaches durable canonical append");
    t.oeffneTerminBlatt(null, "2026-05-10"); const title = w.document.querySelector("#tb-titel");
    w.App.macOSBetaStartContactImport(); await b.pump();
    equal([title.isConnected, starts().length], [true, 1], "Unrelated modal is retained and prevents another picker");
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
    const button = () => w.document.querySelector("#macos-system-contact-import"), visible = () => !w.document.querySelector("#einstellungen-schleier").classList.contains("verborgen");
    const starts = () => messages.filter(message => message.cmd === "macos_kontakte_importieren");
    const url = w.document.querySelector("#briefkasten-url"), password = w.document.querySelector("#briefkasten-kennwort");
    equal([url.disabled, password.disabled, button().disabled], [false, false, false], "Actual DAV fields enabled with valid native account revision");
    t.daten().futureRoot.accountDraftRace = stage;
    const before = JSON.stringify(t.daten()), savesBefore = messages.filter(message => message.cmd === "speichern").length;
    if (stage === "during-save") button().click();
    const field = w.document.getElementById(fieldID), value = fieldID === "briefkasten-url" ? "https://unsaved.example.test/dav" : "public-synthetic-unsaved-password";
    changeInput(w, field, value);
    if (stage === "before-start") { button().click(); equal(messages.filter(message => message.cmd === "speichern").length, savesBefore, "Account draft blocks before document save"); }
    await b.pump();
    equal([starts().length, visible(), field.isConnected, field.value, JSON.stringify(t.daten())], [0, true, true, value, before], "Contacts start preserves account input and the model: " + fieldID + "/" + stage);
    equal([url.value, password.value], fieldID === "briefkasten-url" ? [value, ""] : [account.url, value], "Password-only protection is independent of DAV changed flag");
    equal(messages.filter(message => message.cmd === "baum_briefkasten_speichern").length, 0, "Contact copy does not save account drafts");
    equal(w.document.querySelector("#zettel").textContent, "Save or discard the account changes before importing.", "Pending account input is explained");
    if (stage === "before-start" && fieldID === "briefkasten-kennwort") {
      t.schliesseEinstellungen(); w.App.macOSBetaStartContactImport(); await b.pump();
      equal(starts(), [{ cmd: "macos_kontakte_importieren" }], "Consciously closed hidden password cannot block a later menu start");
    }
  } finally { b.close(); }
}

{
  const b = await context(), { w, t, messages } = b;
  try {
    t.oeffneEinstellungen(); t.daten().futureRoot.pendingSave = true;
    w.App.macOSBetaStartContactImport(); await b.pump({ save: false });
    equal(messages.filter(message => message.cmd === "macos_kontakte_importieren").length, 0, "Failed pre-picker save cannot launch native read");
    equal(w.document.querySelector("#einstellungen-schleier").classList.contains("verborgen"), false, "Failed save retains settings");
  } finally { b.close(); }
}

{
  const b = await context(), { w, t } = b;
  try {
    await commit(b, w.App.macOSBetaPrepareContactImport(payload([item("mcp-copy")])));
    const copy = t.daten().kontakte[1], native = clone(copy.nativeContactRecord), annuals = clone(t.daten().jahrestage);
    // Capture the real canonical session at the published App entrypoint. Only
    // its native JSON-RPC transport is bypassed; registration, input validation,
    // revision checks, product mutation and durable save remain the actual code.
    const module = w.MagnolieMcp; let session;
    w.MagnolieMcp = { ...module, createSession(options) { session = module.createSession(options); return session; } };
    await w.App.mcpRequest({ session: "a".repeat(48), invocation: "b".repeat(48), message: {
      jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-11-25", capabilities: {}, clientInfo: { name: "Contact copy test", version: "1" } } } });
    ok(session, "Actual App registers the canonical MCP contact handlers");
    await session.dispatch({ jsonrpc: "2.0", method: "notifications/initialized" });
    let id = 2;
    const invoke = async (name, args, options) => {
      const pending = session.dispatch({ jsonrpc: "2.0", id: id++, method: "tools/call", params: { name, arguments: args } });
      await b.pump(options); const result = await pending;
      if (result.error || result.result?.isError) throw new Error(JSON.stringify(result));
      return result.result.structuredContent;
    };
    const update = async fields => {
      const before = await invoke("organizer_contact_read", { id: copy.id });
      return invoke("organizer_contact_update", { id: copy.id, expected_revision: before.revision, ...fields });
    };
    const edited = await update({ birth_date: "1604-02-29" });
    equal(edited.persisted, true, "Explicit MCP birthday update passes the real save acknowledgement");
    equal([copy.geburtstag, copy.geburtstagJahrUnbekannt], ["1604-02-29", false], "MCP contact birth date remains active and exact");
    equal(t.daten().jahrestage, annuals, "MCP birth_date cannot silently create a yearly entry for contact-only copy");
    equal(t.normalisiere(clone(t.daten())).kontakte[1].geburtstag, "1604-02-29", "MCP-edited explicit year survives actual normalization");
    const beforeInvalid = JSON.stringify(copy);
    for (const invalid of ["2000-02-31", "--02-30", "12."]) {
      await rejects(update({ birth_date: invalid }), /invalid_date|Invalid tool arguments/, "MCP validates calendar date and syntax: " + invalid);
      equal(JSON.stringify(copy), beforeInvalid, "Invalid MCP date leaves full contact exact");
    }
    await update({ birth_date: "--02-29" });
    equal([copy.geburtstag, copy.geburtstagJahrUnbekannt], ["--02-29", true], "MCP can deliberately remove the year without inventing one");
    await update({ anniversaries: [{ type: "birthday", date: "--03-01" }, { type: "anniversary", date: "2001-06-15" }] });
    const deliberate = t.daten().jahrestage.filter(value => value.kontaktId === copy.id);
    equal(deliberate.map(value => [value.typ, value.datum]), [["birthday", "--03-01"], ["anniversary", "2001-06-15"]], "Explicitly requested MCP anniversaries retain normal calendar behavior");
    equal(copy.geburtstag, "--02-29", "Explicit annual entries do not overwrite the separate contact-only birthday");
    const annualValues = values => values.map(value => Object.fromEntries(["id", "uid", "kontaktId", "datum", "jahrUnbekannt", "name", "typ"].map(key => [key, value[key]])));
    equal(annualValues(t.normalisiere(clone(t.daten())).jahrestage.filter(value => value.kontaktId === copy.id)), annualValues(deliberate), "Reload does not reconcile deliberately separate annual entries to contact-only birthday");
    equal(copy.nativeContactRecord, native, "MCP edits preserve the original native source evidence");
    session.close();
  } finally { b.close(); }
}

{
  const b = await context(), { w, t } = b;
  try {
    // Only the new supplemental German strings are tested here. This does not
    // substitute for generating/testing the complete shared gettext catalogs.
    w.MagnolieI18n.setLocale("de");
    t.oeffneEinstellungen(); w.document.querySelector("#einst-tab-sync").click();
    equal(w.document.querySelector("#macos-system-contact-import").textContent, "Mac-Kontakte übernehmen", "Actual source button uses the supplementary German translation");
    t.schliesseEinstellungen();
    const review = w.App.macOSBetaPrepareContactImport(payload([item("de-copy")]));
    ok(review.preview[0].text.includes("Geburtstag am Kontakt gespeichert; kein Kalendereintrag."), "Native review receives translated contact-only explanation");
    await commit(b, review);
    const form = await editContact(b, t.daten().kontakte[1]);
    ok(form.textContent.includes("Geburtstag am Kontakt gespeichert; kein Kalendereintrag."), "Actual contact editor shows the same German explanation");
    changeInput(w, w.document.querySelector("#kontakt-geburtstag"), "31.02.2000");
    form.querySelector(".kontakt-form-knoepfe button").click();
    equal(w.document.querySelector("#zettel").textContent, "Geben Sie ein gültiges Geburtsdatum ein.", "Actual date validation uses the supplementary German error text");
  } finally { b.close(); }
}

// #778: exercise the public renderer hook after the real canonical append.
for (const language of ["en", "de"]) {
  const b = await context(), { w, t, messages } = b;
  const appearance = w.MagnolieAppearance;
  try {
    w.MagnolieI18n.setLocale(language);
    t.speichereJetzt(); await b.pump();
    const original = JSON.stringify(t.daten().kontakte), originalCount = t.daten().kontakte.length;
    const review = w.App.macOSBetaPrepareContactImport(payload([item("render-failure")]));
    try {
      w.MagnolieAppearance = { ...appearance, update() { throw new Error("Synthetic renderer failure after append"); } };
      await rejects(commit(b, review), language === "de"
        ? /Kontaktkopien wurden hinzugefügt, ihre Speicherung wurde jedoch nicht bestätigt\..*Synthetic renderer failure after append/
        : /Contact copies were added, but saving was not confirmed\..*Synthetic renderer failure after append/,
        "Actual renderer failure explains local mutation and unconfirmed persistence");
    } finally { w.MagnolieAppearance = appearance; }
    equal(t.daten().kontakte.length, originalCount + 1, "Added copy survives renderer failure for save retry");
    equal(JSON.stringify(t.daten().kontakte.slice(0, originalCount)), original, "Renderer failure preserves all pre-existing records and local edits");
    equal(t.daten().kontakte.at(-1).nativeContactImport.identifier, "render-failure", "Renderer failure retains exact native provenance");
    t.speichereJetzt(); await b.pump();
    const saved = JSON.parse(messages.filter(message => message.cmd === "speichern").at(-1).text);
    equal(saved.kontakte, t.daten().kontakte, "Actual retry save contains both existing records and the added copy");
    const retry = w.App.macOSBetaPrepareContactImport(payload([item("render-failure")]));
    equal([retry.newCount, retry.existingCount], [0, 1], "Save retry preserves provenance and prevents duplicate import");
    w.App.macOSBetaCancelContactImport(retry.token);
    w.MacBeta.receive("init", { daten: saved, neu: false, regional: { language, timeZone: "UTC" } });
    await b.pump();
    const reopened = w.App.macOSBetaPrepareContactImport(payload([item("render-failure")]));
    equal([reopened.newCount, reopened.existingCount], [0, 1], "Reopened retry-save bytes still prevent duplicate import");
    w.App.macOSBetaCancelContactImport(reopened.token);
  } finally { w.MagnolieAppearance = appearance; b.close(); }
}

console.log(`Mac system Contacts copy: ${checks} projected UI checks; full synthetic native records/transport, not Contacts.framework or macOS evidence.`);
