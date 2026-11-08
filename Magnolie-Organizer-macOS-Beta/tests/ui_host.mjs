import assert from "node:assert/strict";
import { boot, tick } from "./ui_harness.mjs";

const root = process.argv[2];
assert.ok(root, "Pass a disposable generated UI directory, never stable product files.");
let assertions = 0;

const a = await boot(root); assertions++;
try {
  const { w, messages, t } = a;
  assert.equal(w.document.title, "Magnolie Organizer macOS Beta"); assertions++;
  assert.ok(w.document.getElementById("buch")); assertions++;
  assert.ok(w.document.getElementById("macos-beta-capabilities")); assertions++;
  w.MacBeta.send({ cmd: "speichern", id: 7, text: "{}" }, "hostTest");
  await tick();
  assert.equal(messages.some(m => m.cmd === "speichern"), false); assertions++;
  const original = { termine: [], aufgaben: [{ id: "task", titel: "Synthetic task", futureTask: { keep: 17 } }],
    kontakte: [], notizen: [{ id: "note", titel: "Synthetic note", text: "original", html: "original", futureNote: [true, null] }],
    futureRoot: { opaque: "AA==" }, einstellungen: { allgemein: { handbuchHinweisGezeigt: true } } };
  w.MacBeta.receive("init", { daten: original, neu: false, regional: { language: "en", timeZone: "UTC" } });
  assert.equal(t.daten().futureRoot.opaque, "AA=="); assertions++;
  assert.equal(t.daten().aufgaben[0].futureTask.keep, 17); assertions++;
  assert.equal(JSON.stringify(t.daten().notizen[0].futureNote), "[true,null]"); assertions++;
  // Render the canonical sections, not a replacement landing page.
  for (const section of ["kalender", "aufgaben", "notizen", "adressen", "jahrestage", "planer", "gesundheit"]) {
    await t.wechsel(section);
    assert.ok(w.document.getElementById("inhalt-links").childNodes.length, section); assertions++;
  }
  t.baueEinstellungen();
  w.document.getElementById("einst-tab-sync").click();
  const accountPage = w.document.getElementById("einst-seite-sync");
  assert.match(accountPage.textContent, /Full synchronization is not available/); assertions++;
  assert.equal(accountPage.querySelector("#sync-jetzt").disabled, true); assertions++;
  assert.equal(accountPage.querySelectorAll("[data-system-access]").length, 3); assertions++;
  assert.ok(messages.some(m => m.cmd === "eds_status")); assertions++;
  assert.doesNotMatch(accountPage.textContent, /sudo apt install/); assertions++;
  const firstStatus = messages.filter(m => m.cmd === "eds_status").at(-1);
  const oldSync = t.daten().einstellungen.sync;
  oldSync.kalenderUids = ["legacy-calendar"]; oldSync.kalenderUid = "legacy-calendar";
  oldSync.adressbuchUid = "legacy-addressbook"; oldSync.futureNative = { keep: 42 };
  w.MacBeta.receive("edsStatus", { requestId: "stale", kalender: [], adressbuecher: [] });
  assert.equal(accountPage.querySelector("#macos-system-refresh").disabled, true); assertions++;
  w.MacBeta.receive("edsStatus", { requestId: firstStatus.requestId, permissions: { events: "denied", reminders: "restricted", contacts: "not_determined" },
    fehler: "macOS events: denied.", kalender: [], adressbuecher: [] });
  assert.equal(accountPage.querySelector("#macos-system-refresh").disabled, false); assertions++;
  assert.equal(oldSync.kalenderUids[0], "legacy-calendar"); assertions++;
  assert.equal(accountPage.querySelector("#macos-system-addressbook").value, "legacy-addressbook"); assertions++;
  accountPage.querySelector('[data-system-access="events"]').click();
  const permission = messages.filter(m => m.cmd === "macos_systemzugriff").at(-1);
  assert.equal(permission.art, "events"); assertions++;
  assert.equal(messages.some(m => m.cmd === "sync"), false); assertions++;
  w.MacBeta.receive("edsStatus", { requestId: permission.requestId, permissions: { events: "authorized" },
    kalender: [{ uid: "macos-events:one", name: "<img onerror='bad()'>", readOnly: true }],
    adressbuecher: [{ uid: "macos-contacts:one", name: "Synthetic contacts" }] });
  assert.equal(accountPage.querySelector("img"), null); assertions++;
  assert.match(accountPage.textContent, /<img onerror/); assertions++;
  const selected = accountPage.querySelector('input[value="macos-events:one"]');
  selected.checked = true; selected.dispatchEvent(new w.Event("change"));
  assert.equal(JSON.stringify(oldSync.kalenderUids), '["macos-events:one","legacy-calendar"]'); assertions++;
  const addressBook = accountPage.querySelector("#macos-system-addressbook");
  addressBook.value = "macos-contacts:one"; addressBook.dispatchEvent(new w.Event("change"));
  assert.equal(oldSync.adressbuchUid, "macos-contacts:one"); assertions++;
  assert.equal(oldSync.futureNative.keep, 42); assertions++;
  t.speichereJetzt();
  const sourceSave = messages.filter(m => m.cmd === "speichern").at(-1);
  assert.equal(JSON.parse(sourceSave.text).einstellungen.sync.adressbuchUid, "macos-contacts:one"); assertions++;
  w.MacBeta.receive("gespeichert", { id: sourceSave.id, ok: true });
  assert.equal(accountPage.querySelector("#sync-jetzt").disabled, true); assertions++;
  accountPage.querySelector("#macos-system-refresh").click();
  const failedRead = messages.filter(m => m.cmd === "eds_status").at(-1);
  w.MacBeta.receive("edsStatus", { requestId: failedRead.requestId, fehler: "Synthetic permission revoked", ok: false });
  assert.equal(accountPage.querySelector("#macos-system-addressbook").value, "macos-contacts:one"); assertions++;
  assert.equal(JSON.stringify(oldSync.kalenderUids), '["macos-events:one","legacy-calendar"]'); assertions++;
  assert.equal(messages.filter(m => m.cmd === "macos_systemzugriff").length, 1); assertions++;
  const oldHeader = { version: 1, sourceSHA256: "b".repeat(64), calendarProperties: ["X-OLD:retain"] };
  t.daten().icsImportSources = { [oldHeader.sourceSHA256]: oldHeader };
  const importedHeader = { version: 1, sourceSHA256: "a".repeat(64), calendarProperties: ["METHOD:PUBLISH", "X-PROVIDER:retain"] };
  const calendarPayload = { termine: [{ uid: "synthetic-import", titel: "Imported source", datum: "2030-03-28", zeit: "10:00",
    icsRoundtrip: ["UID:synthetic-import", "DTSTART:20300328T100000", "SUMMARY:Imported source", "X-OPAQUE:retain"] }],
    aufgaben: [], jahrestage: [], icsImportMetadata: importedHeader };
  w.MacBeta.receive("importErgebnis", calendarPayload);
  assert.ok(t.daten().termine.some(item => item.uid === "synthetic-import")); assertions++;
  assert.equal(t.daten().icsImportSources[oldHeader.sourceSHA256].calendarProperties[0], "X-OLD:retain"); assertions++;
  assert.equal(t.daten().icsImportSources[importedHeader.sourceSHA256].calendarProperties[1], "X-PROVIDER:retain"); assertions++;
  t.speichereJetzt();
  const calendarSave = messages.filter(m => m.cmd === "speichern").at(-1);
  assert.equal(JSON.parse(calendarSave.text).icsImportSources[importedHeader.sourceSHA256].calendarProperties[0], "METHOD:PUBLISH"); assertions++;
  w.MacBeta.receive("gespeichert", { id: calendarSave.id, ok: true });
  const importedCount = t.daten().termine.length;
  w.MacBeta.receive("importErgebnis", calendarPayload);
  assert.equal(t.daten().termine.length, importedCount); assertions++;
  const beforeRejected = JSON.stringify(t.daten().icsImportSources);
  w.MacBeta.receive("importErgebnis", { fehler: "Synthetic invalid calendar", icsImportMetadata: { ...importedHeader, sourceSHA256: "c".repeat(64) } });
  assert.equal(JSON.stringify(t.daten().icsImportSources), beforeRejected); assertions++;
  assert.throws(() => w.MacBeta.calendarMetadata(t.daten(), { icsImportMetadata: { ...importedHeader, sourceSHA256: "__proto__" } }, false)); assertions++;
  assert.throws(() => w.MacBeta.receive("importErgebnis", { ...calendarPayload, icsImportMetadata: { ...importedHeader, calendarProperties: ["X-CONFLICT:reject"] } })); assertions++;
  assert.equal(t.daten().termine.length, importedCount); assertions++;
  t.oeffneEinstellungen();
  const davRevision = "1".repeat(64), savedDAVRevision = "2".repeat(64);
  const davBase = { kontoArt: "nextcloud", davAktiv: false, briefkastenAktiv: false, url: "", benutzer: "",
    kennwortVorhanden: false, revision: davRevision, zustand: "nicht_eingerichtet", fehler: "", fehlerCode: "none" };
  const profileBeforeDAV = JSON.stringify(t.daten());
  assert.ok(messages.some(m => m.cmd === "baum_briefkasten_status")); assertions++;
  w.MacBeta.receive("baumBriefkastenStatus", { fehler: "Synthetic Keychain unavailable", revision: null });
  assert.ok([...w.document.querySelectorAll("#nextcloud-konto input")].every(input => input.disabled)); assertions++;
  const beforeDAVRefresh = messages.length;
  w.document.getElementById("macos-dav-refresh").click();
  assert.equal(messages[beforeDAVRefresh].cmd, "baum_briefkasten_status"); assertions++;
  w.MacBeta.receive("baumBriefkastenStatus", davBase);
  assert.equal(w.document.getElementById("macos-dav-refresh"), null); assertions++;
  assert.equal(w.document.getElementById("briefkasten-url").disabled, false); assertions++;
  const davForm = w.document.getElementById("nextcloud-konto");
  assert.ok(davForm); assertions++;
  for (const [id, value] of [["briefkasten-url", "https://cloud.example.test"], ["briefkasten-benutzer", "synthetic-user"]]) {
    const field = w.document.getElementById(id); field.value = value; field.dispatchEvent(new w.Event("input"));
  }
  w.document.getElementById("nextcloud-dav-an").checked = true;
  w.document.getElementById("briefkasten-kennwort").value = "public-synthetic-app-password";
  [...davForm.querySelectorAll("button")].find(button => button.textContent === "Save").click();
  const saveDAV = messages.filter(m => m.cmd === "baum_briefkasten_speichern").at(-1);
  assert.equal(saveDAV.expectedRevision, davRevision); assertions++;
  assert.equal(saveDAV.anwendungskennwort, "public-synthetic-app-password"); assertions++;
  assert.equal(saveDAV.briefkastenAktiv, false); assertions++;
  assert.equal(w.document.getElementById("briefkasten-kennwort").value, ""); assertions++;
  assert.equal(JSON.stringify(t.daten()), profileBeforeDAV); assertions++;
  const savedDAV = { ...davBase, url: saveDAV.url, benutzer: saveDAV.benutzer, davAktiv: true,
    kennwortVorhanden: true, revision: savedDAVRevision, zustand: "bereit", persisted: true };
  w.MacBeta.receive("baumBriefkastenGespeichert", savedDAV);
  const testDAVButton = [...w.document.getElementById("nextcloud-konto").querySelectorAll("button")]
    .find(button => button.textContent === "Test connection");
  testDAVButton.click();
  assert.equal(messages.filter(m => m.cmd === "baum_briefkasten_pruefen").at(-1).expectedRevision, savedDAVRevision); assertions++;
  w.MacBeta.receive("baumBriefkastenPruefung", { ...savedDAV, connectivityChecked: true, kalender: [], adressbuecher: [] });
  assert.equal(JSON.stringify(t.daten()), profileBeforeDAV); assertions++;
  assert.equal(w.document.getElementById("sync-jetzt").disabled, true); assertions++;
  // Ensure encryption still waits for a real pending native save.
  t.daten().notizen[0].text = "pending native save before encryption";
  t.speichereJetzt();
  // The canonical security form must actually emit the Beta-supported encryption scope.
  w.document.getElementById("einst-tab-sicherheit").click();
  w.document.getElementById("kennwort-neu").value = "public synthetic password";
  w.document.getElementById("kennwort-neu2").value = "public synthetic password";
  w.document.getElementById("kennwort-an").click();
  w.document.getElementById("dialog-ja").click();
  await tick();
  const beforeEncryption = messages.filter(m => m.cmd === "speichern").at(-1);
  assert.ok(beforeEncryption); assertions++;
  assert.equal(messages.some(m => m.cmd === "kennwort_setzen"), false); assertions++;
  w.MacBeta.receive("gespeichert", { id: beforeEncryption.id, ok: true });
  const enable = messages.find(m => m.cmd === "kennwort_setzen");
  assert.equal(enable?.sicherungen, false); assertions++;
  // No recurrence parity claim: this reuses only the desktop open-app due-item checker.
  const now = new Date();
  t.daten().einstellungen.erinnerung.an = true;
  t.daten().einstellungen.erinnerung.vorlauf = 0;
  t.daten().termine.push({ id: "due", titel: "Synthetic due appointment", datum: t.isoHeute(),
    zeit: String(now.getUTCHours()).padStart(2, "0") + ":" + String(now.getUTCMinutes()).padStart(2, "0") });
  t.pruefeErinnerungen();
  assert.ok(messages.some(m => m.cmd === "erinnerung_zeigen")); assertions++;
  t.daten().notizen[0].text = "edited";
  t.speichereJetzt();
  const save = messages.filter(m => m.cmd === "speichern").at(-1);
  assert.ok(Number.isSafeInteger(save.id)); assertions++;
  assert.equal(JSON.parse(save.text).notizen[0].text, "edited"); assertions++;
  assert.equal(JSON.parse(save.text).futureRoot.opaque, "AA=="); assertions++;
  w.MacBeta.receive("gespeichert", { id: save.id + 9, ok: true });
  assert.equal(messages.some(m => m.cmd === "beenden_bereit"), false); assertions++;
  w.MacBeta.receive("gespeichert", { id: save.id, ok: true });
  for (const command of ["sync", "kennwort_entfernen", "update_installieren", "telefon_stand", "journal_liste"]) {
    const count = messages.length;
    w.MacBeta.send({ cmd: command, token: "synthetic", pfad: "/must-not-open" }, "hostTest");
    await tick();
    assert.equal(messages.length, count, command + " must not reach native code"); assertions++;
  }
  assert.match(w.document.getElementById("macos-beta-status").textContent, /Not implemented/); assertions++;
  assert.throws(() => w.MacBeta.receive("arbitraryNativeCallback", {})); assertions++;
  assert.throws(() => w.MacBeta.preserve({ items: [{ id: "a", x: 1 }] }, { items: [] })); assertions++;
  assert.throws(() => w.MacBeta.preserve({ items: [{ id: "a" }] }, { items: [{ id: "b" }] })); assertions++;
  const next = {};
  w.MacBeta.preserve(JSON.parse('{"__proto__":{"polluted":true}}'), next);
  assert.equal({}.polluted, undefined); assertions++;
  assert.equal(Object.hasOwn(next, "__proto__"), true); assertions++;
  // Use actual canonical save-on-close handshake, not a mock implementation of it.
  t.daten().notizen[0].text = "pending close";
  t.speichereJetzt(true);
  const pending = messages.filter(m => m.cmd === "speichern").at(-1);
  assert.equal(messages.at(-1).cmd, "speichern"); assertions++;
  w.MacBeta.receive("failure", { cmd: "speichern", id: pending.id, ok: false, fehler: "Synthetic disk failure" });
  assert.equal(messages.at(-1).cmd, "beenden_abgebrochen"); assertions++;
} finally { a.close(); }

const b = await boot(root); assertions++;
try {
  b.w.MacBeta.receive("init", { gesperrt: true });
  b.t.speichereJetzt();
  b.w.MacBeta.send({ cmd: "speichern", id: 1, text: "{}" }, "hostTest");
  await tick();
  assert.equal(b.messages.some(m => m.cmd === "speichern"), false); assertions++;
} finally { b.close(); }
console.log(`macOS Beta host UI: ${assertions} assertions passed. jsdom/V8 only; NOT macOS or WKWebView validation.`);
