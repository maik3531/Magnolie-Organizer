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
  w.MacBeta.receive("sicherungWiederhergestellt", { ok: true, daten: incoming, kennwort: true });
  equal(t.daten().future.keep, "imported", "committed document displayed");
  equal(t.daten().notizen[0].futureAttachment, "AA==", "opaque attachment retained");
  equal(w.document.getElementById("sicherung-schleier").classList.contains("verborgen"), true, "confirmation closes on committed success");
  t.daten().notizen[0].text = "Changed after restore";
  t.speichereJetzt(); saveAck();
  equal(JSON.parse(messages.filter(m => m.cmd === "speichern").at(-1).text).future.keep, "imported", "post-restore save uses new document");
  // Actual desktop regional form also waits for the profile save before the native command.
  t.baueEinstellungen(); w.document.getElementById("einst-tab-regional").click();
  w.document.getElementById("regional-sprache").value = "ar";
  t.daten().notizen[0].text = "Unsaved regional boundary";
  w.document.getElementById("regional-speichern").click();
  equal(messages.some(m => m.cmd === "regional_einstellungen"), false, "regional write waits for save");
  saveAck();
  equal(messages.at(-1).regional.language, "ar", "selected regional value reaches native");
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
console.log(`macOS Beta recovery/regional/keyboard: ${checks} host checks. Fake native transport, NOT WKWebView validation.`);
