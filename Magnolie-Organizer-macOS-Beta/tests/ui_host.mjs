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
  assert.match(accountPage.textContent, /macOS Internet Accounts are not integrated/); assertions++;
  assert.equal(accountPage.querySelector("input,button,select"), null); assertions++;
  assert.doesNotMatch(accountPage.textContent, /sudo apt install/); assertions++;
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
  for (const command of ["sync", "eds_status", "kennwort_entfernen", "update_installieren", "telefon_stand", "journal_liste"]) {
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
