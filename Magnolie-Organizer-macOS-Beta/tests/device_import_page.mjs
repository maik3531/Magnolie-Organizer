import assert from "node:assert/strict";
import { boot, tick } from "./ui_harness.mjs";

// #784: real generated settings and import entry points; native replies are synthetic.
let checks = 0;
const clone = value => JSON.parse(JSON.stringify(value));
const equal = (actual, expected, label) => { assert.deepEqual(clone(actual), clone(expected), label); checks++; };
const ok = (value, label) => { assert.ok(value, label); checks++; };
const actions = [
  ["macos-device-note-files", { cmd: "notiz_dateien_importieren" }],
  ["macos-device-calendar-file", { cmd: "import", art: "ics" }],
  ["macos-device-calendar-copy", { cmd: "macos_kalender_importieren" }],
  ["macos-device-contact-copy", { cmd: "macos_kontakte_importieren" }],
  ["macos-device-reminder-copy", { cmd: "macos_erinnerungen_importieren" }],
  ["macos-device-apple-notes-copy", { cmd: "macos_apple_notizen_importieren" }]
];
const actionCommands = new Set(actions.map(([, message]) => message.cmd));
async function context(locale = "en") {
  const b = await boot(process.argv[2]), seen = new Set();
  b.pump = async (save = true) => {
    for (let step = 0; step < 8; step++) {
      for (const message of [...b.messages]) {
        const key = message.cmd + ":" + (message.id || message.token || "");
        if (seen.has(key)) continue;
        if (message.cmd === "speichern") {
          seen.add(key); b.w.MacBeta.receive("gespeichert", { id: message.id, ok: save, fehler: save ? "" : "Synthetic save failure" });
        }
      }
      await tick();
    }
  };
  b.w.MacBeta.receive("init", { daten: { termine: [], aufgaben: [], kontakte: [], notizen: [], futureRoot: { keep: true },
    einstellungen: { allgemein: { handbuchHinweisGezeigt: true } } }, neu: false, regional: { language: locale, timeZone: "UTC" } });
  b.t.speichereJetzt(); await b.pump();
  b.page = () => {
    b.t.oeffneEinstellungen(); b.w.document.getElementById("einst-tab-baum").click();
    return b.w.document.getElementById("einst-seite-baum");
  };
  b.visible = () => !b.w.document.getElementById("einstellungen-schleier").classList.contains("verborgen");
  b.starts = () => b.messages.filter(message => actionCommands.has(message.cmd));
  return b;
}

for (const [locale, title, text] of [["en", "Devices and imports", "Save files received with KDE Connect or AirDrop on this Mac"],
                                   ["de", "Geräte und Importe", "Speichern Sie mit KDE Connect oder AirDrop empfangene Dateien"]]) {
  const b = await context(locale);
  try {
    const before = JSON.stringify(b.t.daten());
    b.t.oeffneEinstellungen(); const count = b.messages.length;
    const page = b.page(); await tick();
    equal(b.w.document.getElementById("einst-tab-baum").textContent, title, "Device settings have an accurate localized tab label");
    ok(page.textContent.includes(text), "Actual page explains the existing external file route: " + locale);
    ok(page.textContent.includes(locale === "de" ? "noch nicht verfügbar" : "not available"), "Direct control limitation is explicit: " + locale);
    ok(page.textContent.includes(locale === "de" ? "nicht zurücksynchronisiert" : "do not synchronize back"), "Apple source copies remain local: " + locale);
    equal([...page.querySelectorAll("button")].map(button => button.id), actions.map(([id]) => id), "Only six implemented import entry points are offered");
    equal(page.querySelectorAll('[data-telefon-backend], [data-media-backup-recovery], a[href$=".apk"], #telefon-an').length, 0, "No companion download, phone pairing or unsupported media controls");
    assert.doesNotMatch(page.textContent, /Magnolie Notes|One moment|Einen Moment|Loading|Wird geladen/); checks++;
    equal(b.messages.length, count, "Opening the device page starts no native discovery, pairing or media service");
    equal(JSON.stringify(b.t.daten()), before, "Rendering leaves existing settings, records and grants unchanged");
  } finally { b.close(); }
}

for (const [id, request] of actions) {
  const b = await context();
  try {
    b.page(); b.t.daten().futureRoot.pending = id;
    const before = JSON.stringify(b.t.daten());
    b.w.document.getElementById(id).click(); await tick();
    equal(b.starts(), [], "Picker waits for the pending save ACK: " + id);
    equal(b.visible(), true, "Settings stay open while the pending save is unconfirmed: " + id);
    const save = b.messages.filter(message => message.cmd === "speichern").at(-1);
    equal(JSON.parse(save.text).futureRoot.pending, id, "Actual start-save preserves the pending local change: " + id);
    await b.pump();
    equal(b.starts(), [request], "Existing typed request is dispatched exactly once: " + id);
    equal(b.visible(), false, "Settings close before the existing picker/review path: " + id);
    equal(JSON.stringify(b.t.daten()), before, "Opening a picker imports no data and grants no source rights: " + id);
    b.w.MacBeta.receive("failure", { cmd: request.cmd, ok: false, fehler: "Synthetic picker unavailable" }); await tick();
    ok(b.w.document.getElementById("macos-beta-status").textContent.includes("Synthetic picker unavailable"), "Native rejection is visible, never an import success: " + id);
    equal(JSON.stringify(b.t.daten()), before, "Failed native opening preserves the entire book: " + id);
  } finally { b.close(); }
}

for (const [id, request] of actions) {
  const b = await context();
  try {
    b.page(); b.t.daten().futureRoot.pending = "double-start:" + id;
    const button = b.w.document.getElementById(id);
    button.click(); button.click();
    button.dispatchEvent(new b.w.MouseEvent("click", { bubbles: true }));
    b.page();
    for (const [other] of actions) b.w.document.getElementById(other).dispatchEvent(new b.w.MouseEvent("click", { bubbles: true }));
    equal([...b.w.document.querySelectorAll("[data-macos-device-import]")].every(item => item.disabled), true, "All rebuilt page controls share the pending-start latch: " + id);
    await tick(); equal(b.starts(), [], "Repeated and competing starts remain behind the save ACK: " + id);
    await b.pump(); equal(b.starts(), [request], "One save ACK releases exactly the first selected import: " + id);
    b.page();
    equal([...b.w.document.querySelectorAll("[data-macos-device-import]")].some(item => item.disabled), false, "Completed entry does not leave the page permanently disabled: " + id);
  } finally { b.close(); }
}

for (const [id, request] of actions.slice(0, 2)) {
  const b = await context();
  try {
    b.page(); b.t.daten().futureRoot.pending = id;
    const before = JSON.stringify(b.t.daten());
    b.w.document.getElementById(id).click(); await b.pump(false);
    equal([b.starts(), b.visible(), JSON.stringify(b.t.daten())], [[], true, before], "Save failure retains page and pending data without a picker: " + id);
    equal(b.w.document.getElementById(id).disabled, false, "Save failure releases the pending-start latch: " + id);
    b.t.speichereJetzt(); await b.pump();
    b.w.document.getElementById(id).click(); await b.pump();
    equal(b.starts(), [request], "Explicit save retry permits a fresh file import: " + id);
  } finally { b.close(); }

  const draft = await context();
  try {
    draft.page(); draft.t.oeffneTerminBlatt(null, "2026-12-01");
    const field = draft.w.document.getElementById("tb-titel"); field.value = "Retain this draft";
    field.dispatchEvent(new draft.w.Event("input", { bubbles: true }));
    draft.w.document.getElementById(id).click();
    const cancel = [...draft.w.document.querySelectorAll("#aenderungen-schleier button")].find(button => button.textContent === "Cancel");
    ok(cancel, "Existing unsaved-editor decision is required before file selection: " + id);
    cancel.click(); await draft.pump();
    equal([draft.starts(), draft.visible(), field.isConnected, field.value], [[], true, true, "Retain this draft"], "Cancelled navigation retains the exact draft: " + id);
    equal(draft.w.document.getElementById(id).disabled, false, "Cancelled navigation allows an explicit retry: " + id);
    draft.w.document.getElementById(id).click();
    const discard = [...draft.w.document.querySelectorAll("#aenderungen-schleier button")].find(button => button.textContent === "Discard");
    ok(discard, "Retry uses the same real editor guard: " + id);
    discard.click(); await draft.pump();
    equal(draft.starts(), [request], "Explicit discard reaches the existing starter after its outer guard has finished: " + id);
  } finally { draft.close(); }

  const late = await context();
  try {
    late.page(); late.t.daten().futureRoot.pending = "late-modal:" + id;
    late.w.document.getElementById(id).click(); await tick();
    late.t.oeffneTerminBlatt(null, "2026-12-01");
    const field = late.w.document.getElementById("tb-titel"); field.value = "Draft opened while saving";
    field.dispatchEvent(new late.w.Event("input", { bubbles: true }));
    await late.pump();
    equal([late.starts(), late.visible(), field.isConnected, field.value], [[], true, true, "Draft opened while saving"], "An editor opened during the save keeps its draft and blocks the picker: " + id);
    ok(late.w.document.getElementById("zettel").textContent.includes("Finish or close the current editor"), "Post-ACK modal guard explains why selection did not start: " + id);
    equal(late.w.document.getElementById(id).disabled, false, "Post-ACK rejection releases the pending-start latch: " + id);
  } finally { late.close(); }

  const account = await context();
  try {
    account.page(); account.w.document.getElementById("einst-tab-sync").click();
    account.w.MacBeta.receive("baumBriefkastenStatus", { kontoArt: "nextcloud", davAktiv: false, briefkastenAktiv: false,
      url: "https://cloud.example.invalid", benutzer: "synthetic", kennwortVorhanden: false, revision: "1".repeat(64),
      zustand: "nicht_eingerichtet", fehler: "", fehlerCode: "none" });
    const field = account.w.document.getElementById("briefkasten-url"); field.value = "https://changed.example.invalid";
    field.dispatchEvent(new account.w.Event("input", { bubbles: true }));
    account.w.document.getElementById("einst-tab-baum").click(); account.w.document.getElementById(id).click(); await account.pump();
    equal([account.starts(), account.visible()], [[], true], "A retained account draft blocks file entry: " + id);
    ok(account.w.document.getElementById("zettel").textContent.includes("Save or discard the account changes"), "Account draft guard explains the required action: " + id);
  } finally { account.close(); }
}

{
  const b = await context();
  try {
    b.page(); const before = JSON.stringify(b.t.daten());
    b.w.MacBeta.send({ cmd: "sicherung_wiederherstellen", pfad: "synthetic-pending-restore.json", kennwort: "" }, "hostTest");
    for (const [id] of actions) b.w.document.getElementById(id).click();
    await b.pump();
    equal(b.starts(), [], "Stale page controls cannot start imports during native restore");
    equal(JSON.stringify(b.t.daten()), before, "Restore latch preserves existing book and grants");
  } finally { b.close(); }
}
console.log(JSON.stringify({ issue: 784, projectedDevicePageChecks: checks, locales: ["en", "de"],
  existingImportActions: actions.length, syntheticNativeTransport: true, nativeExecution: false }));
