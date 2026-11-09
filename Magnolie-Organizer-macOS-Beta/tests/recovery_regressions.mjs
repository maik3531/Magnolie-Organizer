import assert from "node:assert/strict";
import { boot, tick } from "./ui_harness.mjs";

const b = await boot(process.argv[2]);
const { w, t, messages } = b;
const clone = value => JSON.parse(JSON.stringify(value));
let checks = 0;
const equal = (actual, expected, label) => { assert.deepEqual(clone(actual), clone(expected), label); checks++; };
const saveAck = () => {
  const save = messages.filter(m => m.cmd === "speichern").at(-1);
  assert.ok(save);
  w.MacBeta.receive("gespeichert", { id: save.id, ok: true });
};
try {
  const initial = { termine: [], aufgaben: [], kontakte: [{ id: "contact", vorname: "Synthetic", nachname: "Contact" }], notizen: [],
    future: { keep: "original" }, einstellungen: { allgemein: { handbuchHinweisGezeigt: true, sicherungsordner: "/old/desktop/path" } } };
  w.MacBeta.receive("init", { daten: initial, neu: false, regional: { language: "en", timeZone: "UTC" } });
  t.baueEinstellungen();
  w.document.getElementById("einst-tab-sicherheit").click();
  const page = w.document.getElementById("einst-seite-sicherheit");
  const restore = [...page.querySelectorAll("button")].find(el => el.textContent === "Restore backup …");
  assert.ok(restore); checks++;
  restore.click();
  equal(messages.at(-1), { cmd: "sicherung_waehlen" }, "native picker, no web-supplied path");
  w.MacBeta.receive("sicherungAusgewaehlt", { ok: false, abgebrochen: true });
  equal(w.document.getElementById("sicherung-schleier").classList.contains("verborgen"), true, "cancel opens no restore dialog");
  w.MacBeta.receive("sicherungAusgewaehlt", { ok: true, pfad: "/selected/backup.json", verschluesselt: false });
  equal(w.document.getElementById("sicherung-schleier").classList.contains("verborgen"), false, "canonical confirmation opens");
  w.document.getElementById("sicherung-bestaetigen").click();
  equal(messages.some(m => m.cmd === "sicherung_wiederherstellen"), false, "restore waits for save acknowledgement");
  saveAck();
  equal(messages.at(-1).cmd, "sicherung_wiederherstellen", "durable-save then restore");
  equal(messages.at(-1).pfad, "/selected/backup.json", "selected capability echoed");
  const incoming = { termine: [], aufgaben: [], kontakte: [], notizen: [{ id: "imported", titel: "Imported", text: "Exact", futureAttachment: "AA==" }],
    future: { keep: "imported" }, einstellungen: { allgemein: { handbuchHinweisGezeigt: true } } };
  assert.throws(() => w.MacBeta.validateRestore(JSON.stringify({ ...incoming, notizen: [null] }))); checks++;
  equal(t.daten().future.keep, "original", "failed preflight does not replace data");
  equal(w.MacBeta.validateRestore(JSON.stringify(incoming)), true, "current canonical normalizer preflight");
  const count = messages.length;
  w.MacBeta.send({ cmd: "speichern", id: 900, text: "{}" }, "hostTest");
  await tick();
  equal(messages.length, count, "save fenced during restore");
  const restoreOperation = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
  const expectedRestore = w.MacBeta.prepareNativeRestore(JSON.stringify(incoming), restoreOperation);
  equal(w.document.body.inert, true, "editors remain inert during native restore");
  equal(w.MacBeta.applyNativeRestore(restoreOperation, true).snapshot, expectedRestore.snapshot, "actual callback returns exact validated model");
  equal(w.document.body.inert, true, "model apply alone cannot release editors");
  equal(w.MacBeta.finishNativeRestore(restoreOperation).released, true, "native final handoff releases current operation");
  equal(w.document.body.inert, false, "editors released only after final native handoff");
  equal(t.daten().future.keep, "imported", "committed document displayed");
  equal(t.daten().notizen[0].futureAttachment, "AA==", "opaque attachment retained");
  equal(w.document.getElementById("sicherung-schleier").classList.contains("verborgen"), true, "confirmation closes on committed success");
  t.daten().notizen[0].text = "Changed after restore";
  t.speichereJetzt(); saveAck();
  equal(JSON.parse(messages.filter(m => m.cmd === "speichern").at(-1).text).future.keep, "imported", "post-restore save uses new document");
  // Current desktop time-zone controls must not start unavailable native MCP
  // transactions or mutate imported preferences in this port.
  t.baueEinstellungen(); w.document.getElementById("einst-tab-ort").click();
  const timeZoneBefore = clone(t.daten().einstellungen.regional), nativeBefore = messages.length;
  w.document.getElementById("ort-zeitzonenmanagement").click(); await tick();
  equal(w.document.getElementById("zeitzonenverwaltung"), null, "unsupported native time-zone dialog stays closed");
  equal(messages.length, nativeBefore, "unsupported time-zone management sends no native command");
  equal(t.daten().einstellungen.regional, timeZoneBefore, "unsupported management retains regional preferences");
  assert.match(w.document.getElementById("zettel").textContent, /native time zone management is unavailable/); checks++;
  t.daten().einstellungen.regional.timeZoneManagement = "automatic";
  w.dispatchEvent(new w.Event("focus")); await tick();
  equal(messages.length, nativeBefore, "imported automatic mode does not query unavailable native detection");
  t.daten().einstellungen.regional.timeZoneManagement = timeZoneBefore.timeZoneManagement;
  // Actual desktop regional form also waits for the profile save before the native command.
  t.baueEinstellungen(); w.document.getElementById("einst-tab-regional").click();
  const regionalBeforeFailure = clone(t.daten().einstellungen.regional);
  t.daten().notizen[0].text = "Regional save failure boundary";
  w.document.getElementById("regional-speichern").click();
  const rejectedSave = messages.filter(m => m.cmd === "speichern").at(-1);
  w.MacBeta.receive("gespeichert", { id: rejectedSave.id, ok: false, fehler: "Synthetic disk failure" });
  equal(messages.some(m => m.cmd === "regional_einstellungen"), false, "failed profile save blocks native regional mutation");
  equal(w.document.getElementById("regional-speichern").disabled, false, "failed profile save unlocks regional retry");
  equal(t.daten().einstellungen.regional, regionalBeforeFailure, "failed profile save retains regional choices");
  w.document.getElementById("regional-sprache").value = "ar";
  w.document.getElementById("regional-formatgebiet").value = "de-DE";
  w.document.getElementById("regional-stunden").value = "h12";
  w.document.getElementById("regional-wochenanfang").value = "sunday";
  w.document.getElementById("regional-temperatur").value = "fahrenheit";
  t.daten().notizen[0].text = "Unsaved regional boundary";
  w.document.getElementById("regional-speichern").click();
  equal(messages.some(m => m.cmd === "regional_einstellungen"), false, "regional write waits for save");
  equal(w.document.getElementById("regional-speichern").disabled, true, "regional form fenced until native result");
  w.document.getElementById("regional-speichern").click();
  saveAck();
  equal(messages.at(-1).regional, { language: "ar", formatLocale: "de-DE", hourCycle: "h12",
    firstDayOfWeek: "sunday", weekRule: "iso", temperatureUnit: "fahrenheit", timeZone: "system", homeCountry: "DE" },
    "current shared form maps all fields to the strict Beta native contract");
  equal(messages.filter(m => m.cmd === "regional_einstellungen").length, 1, "duplicate click cannot dispatch a second regional write");
  w.MacBeta.receive("regionalErgebnis", { ok: true, regional: messages.at(-1).regional });
  equal(t.daten().einstellungen.regional.language, "ar", "regional callback retains chosen language");
  for (const language of ["en", "de", "fr", "es", "it", "nl", "pt", "ru", "cs", "pl", "hsb", "da", "nb", "hi", "zh_CN", "ja", "ar", "uk", "be", "tr"]) {
    w.MagnolieI18n.setLocale(language);
    const root = w.document.createElement("section");
    w.MacBeta.backupControls(root, () => {}, () => {});
    equal(root.querySelector("button").textContent, w.MagnolieI18n.gettext("Create backup"), "localized recovery controls " + language);
    equal(w.document.documentElement.dir, language === "ar" ? "rtl" : "ltr", "locale direction " + language);
  }
  w.MagnolieI18n.setLocale("en");
  // Cmd+digit uses the real desktop section handler.
  w.document.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  w.document.dispatchEvent(new w.KeyboardEvent("keydown", { key: "2", metaKey: true, bubbles: true, cancelable: true }));
  equal(t.zustand().sektion, "aufgaben", "Command+2 switches section");
  // The original shared contact deletion waits for its token-correlated recovery ACK.
  t.daten().kontakte.push({ id: "delete-me", vorname: "Delete", nachname: "Synthetic" });
  t.zustand().adressen.auswahlId = "delete-me"; t.zustand().adressen.modus = "ansehen";
  await t.wechsel("adressen");
  const remove = [...w.document.querySelectorAll("button.rot")].find(el => el.textContent === "Delete");
  assert.ok(remove); checks++;
  remove.click(); w.document.getElementById("dialog-ja").click(); await tick();
  saveAck();
  const snapshot = messages.filter(m => m.cmd === "mutations_snapshot").at(-1);
  assert.ok(snapshot); checks++;
  equal(t.daten().kontakte.some(c => c.id === "delete-me"), true, "no premature deletion");
  w.MacBeta.receive("mutationsSnapshot", { ok: true, token: "wrong-token" });
  equal(t.daten().kontakte.some(c => c.id === "delete-me"), true, "wrong token ignored");
  w.MacBeta.receive("mutationsSnapshot", { ok: true, token: snapshot.token });
  equal(t.daten().kontakte.some(c => c.id === "delete-me"), false, "checkpoint acknowledged then deleted");
  equal(t.daten().papierkorb.some(item => item.eintrag.id === "delete-me"), true, "canonical recycle bin retains item");
} catch (error) {
  console.error("Recovery host failed after " + checks + " checks", error);
  throw error;
} finally { await tick(); b.close(); }
// Mirror the production Host's fresh-profile and reopen init/close payloads.
// Compare the actual serialized whole documents, retaining all metadata checks.
let firstProfile;
const fresh = await boot(process.argv[2]);
try {
  fresh.w.MacBeta.receive("init", { daten: {}, neu: true, echterErststart: true,
    regional: { language: "system" }, datenPfad: "/synthetic/macOS-Beta/organizer.json",
    kennwort: false, trayVerfuegbar: false, handbuchInstalliert: false, contributorAktiv: false });
  fresh.w.MacBeta.receive("vorBeenden", {});
  const save = fresh.messages.filter(message => message.cmd === "speichern").at(-1);
  assert.ok(save); checks++;
  firstProfile = JSON.parse(save.text);
  equal(firstProfile.notizen.length, 1, "fresh native startup creates one welcome note");
  fresh.w.MacBeta.receive("gespeichert", { id: save.id, ok: true });
  equal(fresh.messages.at(-1).cmd, "beenden_bereit", "fresh native close follows durable-save acknowledgment");
} finally { await tick(); fresh.close(); }
const reopened = await boot(process.argv[2]);
try {
  reopened.w.MacBeta.receive("init", { daten: firstProfile, neu: false,
    regional: firstProfile.einstellungen.regional, datenPfad: "/synthetic/macOS-Beta/organizer.json",
    kennwort: false, trayVerfuegbar: false, handbuchInstalliert: false, contributorAktiv: false });
  reopened.w.MacBeta.receive("vorBeenden", {});
  const save = reopened.messages.filter(message => message.cmd === "speichern").at(-1);
  assert.ok(save); checks++;
  equal(JSON.parse(save.text), firstProfile, "reopen and normal quit preserve the complete fresh profile exactly");
  reopened.w.MacBeta.receive("gespeichert", { id: save.id, ok: true });
  equal(reopened.messages.at(-1).cmd, "beenden_bereit", "reopened native close follows durable-save acknowledgment");
} finally { await tick(); reopened.close(); }
console.log(`macOS Beta recovery/regional/keyboard: ${checks} host checks. Fake native transport, NOT WKWebView validation.`);
