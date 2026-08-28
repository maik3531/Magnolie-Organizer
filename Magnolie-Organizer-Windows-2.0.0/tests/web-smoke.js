"use strict";

const assert = require("node:assert");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { JSDOM } = require("jsdom");

const web = path.resolve(__dirname, "..", "app", "web");
const root = path.resolve(web, "..", "..");
const poDir = path.join(root, "app", "po");
const html = fs.readFileSync(path.join(web, "index.html"), "utf8");
const application = fs.readFileSync(path.join(web, "anwendung.js"), "utf8");
const css = fs.readFileSync(path.join(web, "stil.css"), "utf8");
const i18n = fs.readFileSync(path.join(web, "i18n.js"), "utf8");
const catalogs = fs.readdirSync(path.join(web, "i18n"))
  .filter((name) => name.endsWith(".js")).sort();
const forbiddenLinuxBluetoothUi = /\b(?:BlueZ|bluetoothctl|D-Bus|DBus)\b/i;
assert.doesNotMatch(css, /\.gesundheit-(?:zellenfeld|bmi-zelle)[^{]*\{[^}]*var\(--hand\)/s,
  "health fields use an undefined font variable");
assert.match(css, /@font-face\s*\{[^}]*font-family:\s*"DejaVu Sans"/s,
  "Windows does not bundle the Linux UI font metrics");
assert.match(css, /font-family:\s*"Magnolie Handschrift"[\s\S]*?Z003-MediumItalic\.otf/s,
  "Windows does not load the bundled Linux handwriting font");
assert.match(css, /data-schrift="handwriting"[\s\S]*?font-family:\s*"Magnolie Handschrift"/s,
  "Windows handwriting selection does not use the bundled Linux font");
assert.match(css, /--sans:\s*"DejaVu Sans",\s*"Liberation Sans",\s*"Segoe UI",\s*sans-serif;/,
  "Windows does not use the same sans-serif family order as Linux");
const fontHash = (name) => crypto.createHash("sha256")
  .update(fs.readFileSync(path.join(web, "schriften", name))).digest("hex");
assert.strictEqual(fontHash("DejaVuSans.ttf"),
  "ae7b7855e115a5966d8b1b3f80f254ccc117ec86f9965e202ee2940453837280",
  "Windows regular UI font is not byte-identical to Linux DejaVu Sans");
assert.strictEqual(fontHash("DejaVuSans-Bold.ttf"),
  "5c1247acef7f2b8522a31742c76d6adcb5569bacc0be7ceaa4dc39dd252ce895",
  "Windows bold UI font is not byte-identical to Linux DejaVu Sans Bold");
assert.strictEqual(fontHash("DejaVuSans-Oblique.ttf"),
  "2d7b524ce7d51db78591b4e19c8185b89f3af0aa6534c5e524cf0c6f4ea673de",
  "Windows italic UI font is not byte-identical to Linux DejaVu Sans Oblique");
assert.strictEqual(fontHash("DejaVuSans-BoldOblique.ttf"),
  "58d78a24ddff9ab30427550d68f0b9b7dd28d6690f9f4b3e4ebac7105252e9b2",
  "Windows bold italic UI font is not byte-identical to Linux DejaVu Sans Bold Oblique");
assert.strictEqual(fontHash("NotoSerif-Regular.ttf"),
  "9d7583b7dc9e812afd32a14280c5cac3160012efe50c8d08938f4fea266ff67f",
  "Windows serif font is not byte-identical to Linux Noto Serif");
assert.strictEqual(fontHash("NotoSerif-Bold.ttf"),
  "0af0ff2be8f84910fb21ec5fe1b6b7395e3073250502a334baf6ca2f860c88fe",
  "Windows bold serif font is not byte-identical to Linux Noto Serif Bold");
assert.strictEqual(fontHash("NotoSerif-Italic.ttf"),
  "bc25600aa27cd409e1e5b3d86340df3a329bb860fcfbe57a03a95070b229e1b0",
  "Windows italic serif font is not byte-identical to Linux Noto Serif Italic");
assert.strictEqual(fontHash("NotoSerif-BoldItalic.ttf"),
  "78a6d685e5690b7dcda0f336b689193afc03b6bab5cf18fc1a9ecc3aa0600059",
  "Windows bold italic serif font is not byte-identical to Linux Noto Serif Bold Italic");
assert.strictEqual(fontHash("NotoSans-Regular.ttf"),
  "89c3c497f618fdaa0b2d1e98fef93582f28c71debd2c4a8cdf41f190ced2909d",
  "Windows handwriting fallback is not byte-identical to Linux Noto Sans");
assert.strictEqual(fontHash("Z003-MediumItalic.otf"),
  "a04947e59fc9339ea3c4b34c31fd46764f22af7512afc2c074ce190e79ed7a09",
  "Windows handwriting font is not byte-identical to Linux Z003");
assert.strictEqual(fontHash("DejaVuSansMono.ttf"),
  "c805f9436dbc268644c1d9584f01a601a653e028e08fd74b9b949f6cf8304d88",
  "Windows monospace font is not byte-identical to Linux DejaVu Sans Mono");
assert.strictEqual(fontHash("DejaVuSansMono-Bold.ttf"),
  "3a3c502eeff669a231549e80df9f7c49de109bafe303170409e905d0b31a38fe",
  "Windows bold monospace font is not byte-identical to Linux DejaVu Sans Mono Bold");
assert.match(css, /--serif:\s*"Noto Serif",\s*serif;/,
  "Windows does not use Linux Noto Serif globally");
assert.match(css, /--mono:\s*"DejaVu Sans Mono",\s*monospace;/,
  "Windows does not use Linux DejaVu Sans Mono globally");
assert.doesNotMatch(css, /font-weight:\s*\d+\s+\d+;/,
  "static Windows fonts are declared with unsupported variable-font weight ranges");
assert.match(html, /font-src 'self'/,
  "Windows CSP blocks the bundled Linux UI font");
assert.doesNotMatch(html, /font-src 'none'/,
  "Windows CSP still disables all bundled fonts");
for (const font of ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVu-LIZENZ.txt",
  "Z003-MediumItalic.otf", "Z003-LIZENZ.txt"]) {
  assert.ok(fs.existsSync(path.join(web, "schriften", font)), `bundled font resource missing: ${font}`);
}
const mainForm = fs.readFileSync(path.join(root, "MainForm.cs"), "utf8");
assert.match(mainForm, /ClientSize = new Size\(1440, 890\)/,
  "Windows normal start does not provide the intended larger client area");
assert.match(mainForm, /width == 1400 && height == 850[\s\S]*?width = 1440;[\s\S]*?height = 890;/,
  "existing Windows default window state is not migrated to the larger client area");
assert.match(css, /\.tb-eigene-daten-steuerung \.knopf\s*\{[^}]*flex:\s*0 0 auto;[^}]*white-space:\s*nowrap;/s,
  "localized custom-date button can shrink below its label");
assert.match(css, /\.gesundheit-insulinart-kopf\s*\{[^}]*grid-template-columns:\s*1fr 140px;/s,
  "insulin dose type clips the bundled Linux font");
assert.match(css, /\.termin-blatt\s+\.bis-wort\s*\{[^}]*inline-size:\s*18ch[^}]*text-align:\s*center/s,
  "date and time range labels do not share a fixed middle column");
assert.match(css, /button, input, select, textarea\s*\{\s*font-family:\s*inherit;/,
  "native appointment controls do not inherit the bundled Linux font");
assert.match(css, /\.termin-blatt input\[type="time"\]::\-webkit-datetime-edit,[\s\S]*?font-family:\s*inherit;/,
  "WebView2 time segments do not inherit the appointment font");
assert.match(css, /\*::\-webkit-scrollbar\s*\{\s*width:\s*6px;\s*height:\s*6px;/,
  "Windows scrollbars do not use the narrow fixed hit area");
assert.match(css, /\*::\-webkit-scrollbar-button\s*\{[^}]*display:\s*none;[^}]*width:\s*0;[^}]*height:\s*0;/,
  "Windows scrollbar arrow buttons remain visible");
assert.match(css, /\*::\-webkit-scrollbar-thumb\s*\{[^}]*border:\s*2px solid transparent;[^}]*background-clip:\s*padding-box;/s,
  "idle Windows scrollbar thumb is not reduced to a two-pixel line");
assert.match(css, /\*::\-webkit-scrollbar-thumb:hover,[^}]*border-width:\s*0;/s,
  "Windows scrollbar thumb does not widen inside its fixed hit area");
for (const file of [path.join(web, "anwendung.js"),
  path.join(poDir, "magnolie-organizer.pot"),
  ...catalogs.map((name) => path.join(web, "i18n", name)),
  ...fs.readdirSync(poDir).filter((name) => name.endsWith(".po"))
    .map((name) => path.join(poDir, name))]) {
  assert.doesNotMatch(fs.readFileSync(file, "utf8"), forbiddenLinuxBluetoothUi,
    `Windows UI source contains Linux Bluetooth terminology: ${path.relative(root, file)}`);
}
const messages = [];

const dom = new JSDOM(html, {
  runScripts: "outside-only",
  url: "https://app.magnolie.invalid/index.html",
  pretendToBeVisual: true
});
const { window } = dom;
window.__MAGNOLIE_BRUECKE__ = "windows_test_bridge";
window.__MAGNOLIE_SPRACHE__ = "de";
window.webkit = { messageHandlers: { windows_test_bridge: {
  postMessage: (text) => messages.push(JSON.parse(text))
} } };
window.eval(i18n);
for (const catalog of catalogs) {
  window.eval(fs.readFileSync(path.join(web, "i18n", catalog), "utf8"));
}
window.eval(application);
window.document.dispatchEvent(new window.Event("DOMContentLoaded", { bubbles: true }));

assert.ok(messages.some((message) => message.cmd === "bereit"),
  "randomized WebView bridge does not receive ready");
assert.strictEqual(catalogs.length, 19, "all 19 generated catalogs must ship");
const projectVersion = fs.readFileSync(path.join(root, "Directory.Build.props"), "utf8")
  .match(/<Version>([^<]+)<\/Version>/)[1];
const webVersion = application.match(/const FASSUNG = "([^"]+)"/)[1];
assert.strictEqual(webVersion, projectVersion, "web and native versions differ");
assert.match(fs.readFileSync(path.join(root, "LIESMICH.md"), "utf8"),
  /Oberfläche unter .+ ist\s+aus Magnolie Organizer 2\.0\.0 übernommen/,
  "README does not identify the web UI provenance");
assert.ok(!window.document.querySelector("#telefon-schleier") &&
  !window.document.querySelector("#sms-schleier"),
"obsolete static phone and SMS dialogs must not ship");

window.App.init({ daten: {}, neu: true, kennwort: false, gesperrt: false,
  regional: { language: "de", timezone: "Europe/Berlin" },
  trayVerfuegbar: true, teamsVerfuegbar: true,
  datenPfad: "C:\\Probe\\daten.json" });
const T = window.OrganizerTest;
assert.ok(window.document.querySelector("#buch") &&
  window.document.querySelector("#inhalt-links").children.length,
"organizer did not render");
window.document.querySelector("#knopf-drucken").click();
const printSearch = window.document.querySelector(".druck-suche");
assert.ok(printSearch && printSearch.placeholder === "Suche" &&
  printSearch.getAttribute("aria-label") === "Suche",
"print selection does not expose the localized search field on Windows");
window.document.querySelector("#druck-schleier button[aria-label='Schließen']").click();
const defaults = T.normalisiere({});
assert.strictEqual(defaults.einstellungen.adressen.karten, "google");
assert.strictEqual(defaults.einstellungen.kalender.gesundheitPlanung.vital.zeit, "",
  "health planning fabricates a default time");
assert.strictEqual(defaults.einstellungen.sync.adressbuchUid, "windows-contacts");
assert.strictEqual(T.normalisiere({ einstellungen: { sync: { adressbuchUid: "" } } })
  .einstellungen.sync.adressbuchUid, "", "calendar-only selection is replaced by Windows Contacts");
const recurrenceAndTask = T.normalisiere({
  termine: [
    { id: "interval", datum: "2026-08-01", titel: "Interval",
      wiederholung: { art: "daily", intervall: 14 } },
    { id: "custom", datum: "2026-08-01", titel: "Custom",
      wiederholung: { art: "custom", daten: ["2026-09-05", "2026-08-19", "2026-08-19"] } }
  ],
  aufgaben: [{ id: "timed", titel: "Timed", faellig: "2026-08-20",
    startZeit: "09:00", faelligZeit: "10:30" }]
});
assert.deepStrictEqual(recurrenceAndTask.termine[0].wiederholung,
  { art: "daily", bis: "", intervall: 14 }, "recurrence interval is lost during normalization");
assert.deepStrictEqual(recurrenceAndTask.termine[1].wiederholung,
  { art: "custom", bis: "", daten: ["2026-08-19", "2026-09-05"] },
  "custom recurrence dates are not canonicalized");
assert.strictEqual(recurrenceAndTask.aufgaben[0].startZeit, "09:00");
assert.strictEqual(recurrenceAndTask.aufgaben[0].faelligZeit, "10:30");
T.daten().gesundheit.vitalwerte.push(
  { id: "bmi-height", datum: "2026-08-18", zeit: "08:00", groesse: 180 },
  { id: "bmi-weight", datum: "2026-08-19", zeit: "08:00", gewicht: 81 });
T.wechsel("gesundheit");
assert.ok(Array.from(window.document.querySelectorAll(".gesundheit-zellenfeld"))
  .some((field) => field.value === "18.08.2026"), "the complete health date is not rendered");
const healthTimes = Array.from(window.document.querySelectorAll(".gesundheit-zeit"));
const filledHealthTime = healthTimes.find((field) => field.value === "08:00");
assert.ok(filledHealthTime && filledHealthTime.type === "text" &&
  !filledHealthTime.querySelector("input"),
  "health time is not rendered as one field");
const emptyHealthTime = healthTimes.find((field) => field.value === "");
assert.ok(emptyHealthTime && emptyHealthTime.type === "text" && emptyHealthTime.placeholder === "" &&
  emptyHealthTime.maxLength === 5,
  "blank health rows contain a fabricated time");
const healthDate = window.document.querySelector(".gesundheit-zellenfeld.datumsfeld");
let healthDatePickerOpened = false;
healthDate.showPicker = () => { healthDatePickerOpened = true; };
healthDate.click();
assert.ok(healthDate.getAttribute("list") === "gesundheit-datum-vorschlaege" &&
  window.document.querySelectorAll("#gesundheit-datum-vorschlaege option").length === 3 &&
  healthDatePickerOpened, "health date suggestions do not open by clicking the arrowless field");
filledHealthTime.setSelectionRange(3, 5);
filledHealthTime.dispatchEvent(new window.WheelEvent("wheel",
  { deltaY: -1, bubbles: true, cancelable: true }));
assert.strictEqual(filledHealthTime.value, "08:01",
  "mouse wheel does not adjust only the selected health time segment");
filledHealthTime.value = "08:00";
filledHealthTime.dispatchEvent(new window.Event("input", { bubbles: true }));
T.zustand().gesundheit.entwurf.dirty = false;
T.daten().einstellungen.regional.timeZone = "Europe/Berlin";
assert.strictEqual(T.aktuelleGesundheitsZeit(new window.Date("2026-08-20T12:37:00Z")), "14:37",
  "health marker does not use the current organizer time");
Array.from(window.document.querySelectorAll(".gesundheit-symbolknopf"))
  .find((button) => button.title === "Verlauf").click();
assert.ok(window.document.querySelector(".gesundheit-bmi").textContent.endsWith(": 25.0"),
  "BMI history does not use the latest stored weight and height");
T.wechsel("kalender");
Array.from(window.document.querySelectorAll("#ansicht-umschalter .u-knopf"))
  .find((button) => button.dataset.ansicht === "month").click();
const overviewDay = Array.from(window.document.querySelectorAll(
  ".kal-tag:not(.gewaehlt):not(.andermonat)"))
  .find((day) => !day.querySelector(".mini-termin"));
overviewDay.click();
assert.strictEqual(T.zustand().kalender.uebersichtAb, T.zustand().kalender.tag,
  "month-day selection does not set the appointment overview start");
const wholeMonth = Array.from(window.document.querySelectorAll("button"))
  .find((button) => button.textContent.trim() === "Ganzer Monat");
assert.ok(wholeMonth, "whole-month reset is unreachable after selecting a month day");
window.document.querySelector("#termin-schleier button[aria-label='Schließen']").click();
wholeMonth.click();
assert.strictEqual(T.zustand().kalender.uebersichtAb, null,
  "whole-month reset does not clear the appointment overview start");
const cursorFixture = { letzteSyncs: { kalender: { cloud: 123 }, adressbuecher: { cards: 456 } },
  syncMetadaten: { syncEpoch: "epoch", nextcloud: { kalender: { cloud: {
    initialisiert: true, letzterSync: 123, etags: { event: { href: "https://cloud.invalid/e.ics",
      etag: '"one"' } } } }, adressbuecher: { cards: { initialisiert: true,
        letzterSync: 456, etags: { person: '"two"' } } }, quarantinedDeletes: { cloud: ["gone"] },
    transaktionen: { run: { phase: "prepared" } } } } };
const cursorRoundtrip = T.normalisiere(JSON.parse(JSON.stringify(T.normalisiere(cursorFixture))));
assert.deepStrictEqual(cursorRoundtrip.letzteSyncs, cursorFixture.letzteSyncs,
  "nested UI cursor timestamps do not survive save/restart normalization");
assert.deepStrictEqual(cursorRoundtrip.syncMetadaten.nextcloud, cursorFixture.syncMetadaten.nextcloud,
  "Nextcloud ETags/initialization/quarantine/resume metadata are lost by UI normalization");
const remoteMapping = { id: "https://cloud.invalid/item", etag: '"etag"',
  geaendert: 123, eigen: true };
const mappingRoundtrip = T.normalisiere({ termine: [{ uid: "event", datum: "2026-08-17", sync: true,
  syncQuellen: { "nextcloud-calendar:x": remoteMapping } }], kontakte: [{ uid: "person", sync: true,
  syncQuellen: { "nextcloud-addressbook:x": remoteMapping } }], geloescht: {
  termine: [{ uid: "dead-event", zeit: 123, syncQuellen: { "nextcloud-calendar:x": remoteMapping } }],
  kontakte: [{ uid: "dead-person", zeit: 123, syncQuellen: { "nextcloud-addressbook:x": remoteMapping } }] } });
assert.deepStrictEqual(mappingRoundtrip.termine[0].syncQuellen["nextcloud-calendar:x"], remoteMapping,
  "appointment normalization loses Nextcloud delete identity");
assert.deepStrictEqual(mappingRoundtrip.kontakte[0].syncQuellen["nextcloud-addressbook:x"], remoteMapping,
  "contact normalization loses Nextcloud delete identity");
assert.deepStrictEqual(mappingRoundtrip.geloescht.termine[0].syncQuellen["nextcloud-calendar:x"], remoteMapping,
  "appointment tombstone normalization loses Nextcloud delete identity");
assert.deepStrictEqual(mappingRoundtrip.geloescht.kontakte[0].syncQuellen["nextcloud-addressbook:x"], remoteMapping,
  "contact tombstone normalization loses Nextcloud delete identity");
assert.ok(Array.isArray(defaults.smsVerlauf) && defaults.personalSync.entities,
  "current SMS/personal-sync schema is missing");
const ordinal = T.normalisiere({ termine: [{ id: "ordinal", datum: "2024-01-11",
  zeit: "", titel: "Forumserie", wiederholung: { art: "monthly_weekday", bis: "",
    ordinal: 2, wochentag: "TH", rruleForm: "bysetpos" }, icsKomplex: true,
  icsRoundtrip: ["RRULE:FREQ=MONTHLY;BYDAY=TH;BYSETPOS=2",
    "EXDATE;VALUE=DATE:20240208"] }] }).termine[0];
assert.deepStrictEqual(ordinal.icsRoundtrip, ["RRULE:FREQ=MONTHLY;BYDAY=TH;BYSETPOS=2",
  "EXDATE;VALUE=DATE:20240208"], "ICS exceptions are lost during restart normalization");
const todoRoundtrip = T.normalisiere({ aufgaben: [{ uid: "todo", titel: "Probe",
  icsRoundtrip: ["ATTACH:https://drive.google.com/file/d/1", "X-TODO:opaque"] }] }).aufgaben[0];
assert.deepStrictEqual(todoRoundtrip.icsRoundtrip,
  ["ATTACH:https://drive.google.com/file/d/1", "X-TODO:opaque"],
  "VTODO raw ICS data is lost during web normalization/restart");
const anniversaryRoundtrip = T.normalisiere({ jahrestage: [{ uid: "anniversary",
  name: "Mia", datum: "1990-08-12", typ: "birthday", syncKalenderUid: "cal-23",
  icsRoundtrip: ["LOCATION:Garten", "BEGIN:VALARM", "TRIGGER:-P1D", "END:VALARM"] }] }).jahrestage[0];
assert.deepStrictEqual(anniversaryRoundtrip.icsRoundtrip,
  ["LOCATION:Garten", "BEGIN:VALARM", "TRIGGER:-P1D", "END:VALARM"],
  "anniversary raw ICS data is lost during web normalization/restart");
assert.strictEqual(anniversaryRoundtrip.syncKalenderUid, "cal-23",
  "anniversary calendar source is lost during web normalization/restart");
assert.deepStrictEqual(["2024-02-08", "2024-03-14", "2024-04-11"].map((date) =>
  T.wiederholungTrifft(ordinal, date)), [true, true, true],
"second-Thursday occurrences are missing after normalization/restart");
assert.deepStrictEqual(["2024-02-01", "2024-02-15", "2024-03-07", "2024-04-12"].map((date) =>
  T.wiederholungTrifft(ordinal, date)), [false, false, false, false],
"non-second Thursdays or other weekdays match the ordinal series");
ordinal.kategorien = "Arbeit, http://schemas.google.com/g/2005#event, Privat";
T.daten().kontakte.push(...T.normalisiere({ kontakte: [{ id: "org-contact",
  vorname: "Anna", nachname: "Beispiel", emailEintraege: [
    { wert: "anna@example.test", typen: ["WORK"] },
    { wert: "privat@example.test", typen: ["HOME"] }
  ] }, { id: "org-contact-same", vorname: "Anna", nachname: "Beispiel",
    emailEintraege: [{ wert: "weitere@example.test", typen: ["WORK"] }] },
  { id: "org-contact-other", vorname: "Berta", nachname: "Anders",
    emailEintraege: [{ wert: "unbeteiligt@example.test", typen: ["WORK"] }] }
] }).kontakte);
T.daten().termine.push(ordinal);
T.oeffneTerminBlatt(ordinal, false);
assert.ok(Array.from(window.document.querySelector("#tb-wiederholung").options)
  .some((option) => option.value === "monthly-weekday" &&
    option.textContent === "jeden Monat am zweiten Donnerstag"),
"localized second-Thursday series cannot be selected");
assert.strictEqual(window.document.querySelector("#tb-wiederholung-hinweis").textContent,
  "jeden Monat am zweiten Donnerstag",
"localized ordinal series description is missing");
assert.strictEqual(window.document.querySelector("#tb-datum-von").parentElement,
  window.document.querySelector("#tb-datum-bis").parentElement,
"date range is not displayed in one row");
assert.strictEqual(window.document.querySelector("#tb-datum-bis").getAttribute("aria-label"),
  "Bis einschließlich", "end date has no accessible label");
assert.ok(window.document.querySelector("#tb-datum-von").type === "text" &&
  window.document.querySelector("#tb-datum-von").value === "11.01.2024" &&
  window.document.querySelector("#tb-datum-bis").type === "text",
"appointment dates still depend on wider native Windows date segments");
assert.strictEqual(window.document.querySelector("#tb-zeit").parentElement,
  window.document.querySelector("#tb-endzeit").parentElement,
"time range is not displayed in one row");
assert.ok(window.document.querySelector("#tb-wiederholung-hinweis").compareDocumentPosition(
  window.document.querySelector("#tb-erinnerungsbereich")) & window.Node.DOCUMENT_POSITION_FOLLOWING,
"reminders are not separated below recurrence");
assert.strictEqual(window.document.querySelector(".tb-aufklapper").textContent,
  "▾ Weitere Felder", "Lotus suffix remains visible");
assert.strictEqual(window.document.querySelector(".tb-aufklapper").getAttribute("aria-controls"),
  "tb-weitere-felder", "additional-fields disclosure has no target");
assert.strictEqual(window.document.querySelector(".tb-aufklapper").getAttribute("aria-expanded"),
  "true", "additional-fields disclosure state is missing");
assert.deepStrictEqual(Array.from(window.document.querySelector("#tb-kategorien-vorschlaege").options,
  (option) => option.value), ["Arbeit", "Privat"], "category suggestions are missing");
assert.ok(Array.from(window.document.querySelector("#tb-organisator-namen").options,
  (option) => option.value).includes("Anna Beispiel"), "organizer suggestion is missing");
const organizerName = window.document.querySelector("#tb-organisator-name");
organizerName.value = "Anna Beispiel";
organizerName.dispatchEvent(new window.Event("input", { bubbles: true }));
assert.deepStrictEqual(Array.from(window.document.querySelector("#tb-organisator-emails").options,
  (option) => option.value), ["anna@example.test", "privat@example.test",
    "weitere@example.test"],
"organizer email suggestions do not follow the selected contact");
window.document.querySelector("#termin-schleier")?.remove();
const readOnlyAppointment = T.normalisiere({ termine: [{ id: "readonly-appointment",
  datum: "2026-01-13", titel: "Nur lesen", icsReadOnly: true,
  icsQuelleName: "EDS-Kalender" }] }).termine[0];
T.oeffneTerminBlatt(readOnlyAppointment, false);
assert.ok(window.document.querySelector(".tb-links .einst-warnung").textContent
  .includes("EDS-Kalender"), "read-only calendar warning is missing");
assert.strictEqual(window.document.querySelector("#tb-fertig").textContent, "Schließen",
  "read-only appointment does not offer Close");
assert.ok(!window.document.querySelector("#tb-loeschen") &&
  Array.from(window.document.querySelectorAll(".tb-spalten input, .tb-spalten textarea, " +
    ".tb-spalten select, .tb-spalten button")).every((field) => field.disabled),
"read-only appointment can still be edited or deleted");
window.document.querySelector("#termin-schleier")?.remove();
const timedTwoDay = T.normalisiere({ termine: [{ id: "timed-two-day",
  datum: "2026-01-13", endDatum: "2026-01-14", zeit: "09:15", endZeit: "10:45",
  titel: "Zweitägig", wiederholung: { art: "monthly", bis: "", ordinal: 2,
    wochentag: "TU", rruleForm: "byday" } }] }).termine[0];
T.daten().termine.push(timedTwoDay);
T.planeSpeichern();
const timedOccurrence = T.termineAm("2026-02-11").find((item) => item.id === "timed-two-day");
assert.ok(timedOccurrence && timedOccurrence.datum === "2026-02-10" &&
  timedOccurrence.endDatum === "2026-02-11" && timedOccurrence.zeit === "09:15" &&
  timedOccurrence.endZeit === "10:45", "timed two-day recurrence loses its duration");
const timedRdate = T.normalisiere({ termine: [{ id: "timed-rdate", datum: "2026-08-17",
  zeit: "09:00", endZeit: "10:30", titel: "Zusatztermin",
  wiederholung: { art: "weekly", bis: "" },
  icsZusatzDaten: ["2026-08-19", "2026-08-24"],
  icsZusatzTermine: [{ datum: "2026-08-19", zeit: "15:00" },
    { datum: "2026-08-19", zeit: "18:00" },
    { datum: "2026-08-24", zeit: "15:00" }] }] }).termine[0];
T.daten().termine.push(timedRdate);
T.planeSpeichern();
const rdateOccurrences = T.termineAm("2026-08-19").filter((item) => item.id === "timed-rdate");
assert.deepStrictEqual(rdateOccurrences.map((item) => [item.zeit, item.endZeit]),
  [["15:00", "16:30"], ["18:00", "19:30"]],
"timed RDATE loses its individual time or inherited duration");
const regularAndRdate = T.termineAm("2026-08-24").filter((item) => item.id === "timed-rdate");
assert.deepStrictEqual(regularAndRdate.map((item) => item.zeit), ["09:00", "15:00"],
  "RDATE replaced the regular RRULE occurrence on the same day");
const sourceAppointmentsBefore = T.daten().termine.length;
assert.deepStrictEqual(T.mergeTermine([
  { uid: "source-collision", datum: "2026-09-01", zeit: "09:00", titel: "Quelle A",
    icsQuelleId: "thunderbird:a", geaendert: 10 },
  { uid: "source-collision", datum: "2026-09-02", zeit: "09:00", titel: "Quelle B",
    icsQuelleId: "thunderbird:b", geaendert: 10 }
]), { neu: 2, doppelt: 0 }, "same UID from separate calendars was merged");
assert.strictEqual(T.daten().termine.length, sourceAppointmentsBefore + 2,
  "source-isolated appointments were not both retained");
const sourceAnniversariesBefore = T.daten().jahrestage.length;
assert.deepStrictEqual(T.mergeJahrestage([
  { uid: "anniversary-collision", icsSerienUid: "anniversary-collision", name: "Mia A",
    datum: "1990-09-01", typ: "birthday", icsQuelleId: "thunderbird:a", geaendert: 10 },
  { uid: "anniversary-collision", icsSerienUid: "anniversary-collision", name: "Mia B",
    datum: "1990-09-02", typ: "birthday", icsQuelleId: "thunderbird:b", geaendert: 10 }
]), { neu: 2, doppelt: 0 }, "same anniversary UID from separate calendars was merged");
assert.strictEqual(T.daten().jahrestage.length, sourceAnniversariesBefore + 2,
  "source-isolated anniversaries were not both retained");
assert.deepStrictEqual(T.mergeJahrestage([
  { uid: "anniversary-collision", icsSerienUid: "anniversary-collision", name: "Mia A neu",
    datum: "1990-09-03", typ: "birthday", icsQuelleId: "thunderbird:a", geaendert: 20 }
]), { neu: 1, doppelt: 0 }, "newer anniversary series was not updated");
assert.strictEqual(T.daten().jahrestage.find((item) =>
  item.uid === "anniversary-collision" && item.icsQuelleId === "thunderbird:a").name, "Mia A neu");

const teamsContact = T.normalisiere({ kontakte: [{ id: "teams-contact",
  vorname: "Mia", nachname: "Muster", telefone: [{ wert: "+49 170 1234567",
    typen: ["CELL"] }], sozialeMedien: [{ dienst: "teams-call",
    wert: "+49 170 1234567" }] }] }).kontakte[0];
T.daten().kontakte.push(teamsContact);
T.zustand().adressen.auswahlId = teamsContact.id;
T.wechsel("adressen");
Array.from(window.document.querySelectorAll("button"))
  .find((button) => button.textContent === "Bearbeiten").click();
assert.ok(Array.from(window.document.querySelector(".kontakt-sozial-dienst").options)
  .some((option) => option.value === "teams-call"),
"installed Microsoft Teams is not offered by the contact editor");
T.wechsel("kalender");

T.oeffneEinstellungen();
assert.ok(!window.document.querySelector("#einst-tab-regional") &&
  !Array.from(window.document.querySelectorAll(".einst-reiter-knopf"))
    .some((button) => button.textContent === "Sprache & Region"),
"regionale Einstellungen sind unter Windows weiterhin als Reiter sichtbar");
window.document.querySelector("#einst-tab-adressen").click();
assert.deepStrictEqual(Array.from(window.document.querySelector("#adressen-karten").options,
  (option) => option.value), ["google", "openstreetmap"],
"Windows map choices changed");
assert.ok(!window.document.querySelector("#einstellungen-inhalt").textContent.includes("GNOME"));
window.document.querySelector("#einst-tab-sync").click();
window.App.edsStatus({ windows: true, verfuegbar: true, buchOk: true,
  adressbuecher: [{ uid: "windows-contacts", name: "Windows-Kontakteordner" },
    { uid: "microsoft-graph", name: "Outlook.com / Microsoft 365" }],
  graph: { eingerichtet: true, angemeldet: false } });
assert.ok(window.document.querySelector("#sync-windows-quelle"));
assert.ok(Array.from(window.document.querySelectorAll("button"))
  .some((button) => button.textContent === window.MagnolieI18n.gettext("Sign in to Microsoft")));
assert.ok(!window.document.body.textContent.includes("Client-ID") &&
  !window.document.body.textContent.includes("sudo apt install"));

assert.ok(!window.document.querySelector("#einst-tab-nextcloud"),
  "separate Nextcloud settings tab still exists");
assert.ok(messages.some((message) => message.cmd === "baum_briefkasten_status"),
  "synchronization page does not request Nextcloud status");
window.App.baumBriefkastenStatus({ davAktiv: false, briefkastenAktiv: false,
  aktiv: false, url: "", benutzer: "",
  kennwortVorhanden: false, zustand: "aus", fehler: "" });
assert.ok(window.document.querySelector("#einst-seite-sync") &&
  window.document.querySelector("#nextcloud-konto") &&
  window.document.querySelector("#nextcloud-kalender-kontakte") &&
  window.document.querySelector("#nextcloud-briefkasten") &&
  window.document.querySelector("#briefkasten-url") &&
  window.document.querySelector("#briefkasten-benutzer") &&
  window.document.querySelector("#briefkasten-kennwort"),
"Nextcloud synchronization sections or account fields are missing");
const nextcloudText = window.document.querySelector("#einst-seite-sync").textContent;
assert.ok(nextcloudText.includes("baum-1") && /encrypted|verschlüsselt/i.test(nextcloudText) &&
  /does not synchronize|keine Kalender|synchronisiert keine/i.test(nextcloudText) &&
  /Nextcloud/i.test(nextcloudText),
"Nextcloud page does not clearly delimit the encrypted fallback");
assert.strictEqual(window.document.querySelectorAll("#briefkasten-url").length, 1,
  "Nextcloud mailbox field IDs are duplicated");
assert.strictEqual(window.document.querySelector("#nextcloud-dav-an").checked, true,
  "fresh Nextcloud setup does not enable calendar and contact synchronization");
window.App.baumBriefkastenStatus({ davAktiv: false, briefkastenAktiv: false,
  aktiv: false, url: "https://cloud.example", benutzer: "user",
  kennwortVorhanden: true, zustand: "aus", fehler: "" });
const saveCount = messages.filter((message) => message.cmd === "baum_briefkasten_speichern").length;
Array.from(window.document.querySelectorAll("#einst-seite-sync button"))
  .find((button) => button.textContent === "Speichern").click();
assert.strictEqual(messages.filter((message) => message.cmd === "baum_briefkasten_speichern").length,
  saveCount + 1, "intentional Nextcloud deactivation was blocked");
assert.ok(messages.some((message) => message.cmd === "baum_briefkasten_speichern" &&
  message.davAktiv === false && message.briefkastenAktiv === false),
"disabled Nextcloud configuration changed during save");
window.document.querySelector("#briefkasten-url").value = "https://cloud.example";
window.document.querySelector("#briefkasten-benutzer").value = "user";
window.document.querySelector("#briefkasten-kennwort").value = "app-password";
window.document.querySelector("#nextcloud-dav-an").checked = true;
window.document.querySelector("#briefkasten-an").checked = false;
Array.from(window.document.querySelectorAll("#einst-seite-sync button"))
  .find((button) => button.textContent === "Speichern").click();
assert.strictEqual(window.document.querySelector("#briefkasten-kennwort").value, "",
  "app password was not cleared immediately");
Array.from(window.document.querySelectorAll("#einst-seite-sync button"))
  .find((button) => button.textContent === "Verbindung prüfen").click();
assert.ok(messages.some((message) => message.cmd === "baum_briefkasten_speichern" &&
  message.davAktiv === true && message.briefkastenAktiv === false &&
  message.url === "https://cloud.example" && message.benutzer === "user" &&
  message.anwendungskennwort === "app-password") &&
  messages.some((message) => message.cmd === "baum_briefkasten_pruefen"),
"Nextcloud page changed the mailbox save or test bridge commands");
window.document.querySelector("#einst-tab-sync").click();
window.App.graphAnmeldung({ ok: true, fertig: false, code: "AB<12>",
  url: "javascript:alert(1)", nachricht: "<img src=x onerror=alert(1)>" });
assert.ok(window.document.querySelector("#graph-status").textContent.includes("AB<12>") &&
  window.document.querySelector("#graph-status").textContent.includes("<img"),
"Graph device-code payload is not displayed as text");
assert.ok(!window.document.querySelector("#graph-status img") &&
  !window.document.querySelector("#graph-status a"),
"unsafe Graph payload created active content");
window.App.graphAnmeldung({ ok: true, fertig: false, code: "ABCD-EFGH",
  url: "https://microsoft.com/devicelogin", nachricht: "Continue in the browser." });
assert.strictEqual(window.document.querySelector("#graph-status a").protocol, "https:");
window.App.graphAnmeldung({ ok: true, fertig: true, code: "", url: "",
  nachricht: "Microsoft-Anmeldung abgeschlossen." });
window.App.graphKonfiguration({ ok: true, fehler: "" });
window.App.graphAbmeldung({ ok: true, fehler: "" });
assert.ok(messages.filter((message) => message.cmd === "eds_status").length >= 3,
  "Graph completion callbacks do not refresh source state");
window.App.telefonFehler({ fehler: "PHONE-ERROR-SENTINEL" });
assert.ok(window.document.body.textContent.includes("PHONE-ERROR-SENTINEL"),
  "phone errors are not shown");

window.document.querySelector("#einst-tab-baum").click();
window.App.telefonStand({ enabled: true, listening: true, port: 8741,
  bluetooth: { available: false, devices: [] },
  peers: [{ device_id: "phone-1", display_name: "Pixel", state: "online_wifi",
    transport: "wifi", fingerprint: "AAAA-BBBB", own_device: true,
    remote_own_device: true, auto_wifi: true,
    local_grants: { grants: { selected_notifications_readonly: true,
      personal_notes_sync: true, personal_tasks_sync: true,
      personal_deletions_sync: true } },
    grants: { grants: { personal_notes_sync: true, personal_tasks_sync: true,
      personal_deletions_sync: true } }, capabilities: { items: {
      personal_notes_sync: { versions: [1, 2] } } } }],
  kdeconnect: { available: true, paired: true, listening: true, listen_port: 1716 } });
assert.ok(window.document.querySelector(".telefon-karte") &&
  window.document.querySelector(".telefon-kde-karte"));
assert.ok(window.document.body.textContent.includes("Pixel") &&
  window.document.body.textContent.includes("KDE Connect"));
assert.ok(window.document.body.textContent.includes("WLAN"));
const phoneRow = window.document.querySelector(".telefon-liste .baum-zeile");
assert.ok(phoneRow && !Array.from(phoneRow.children).some((element) =>
  element.matches("span.einst-hinweis") && element.textContent.includes(
    window.MagnolieI18n.gettext("Selected notifications"))),
"the redundant selected-notifications peer summary remains visible");

const statusButton = Array.from(window.document.querySelectorAll("button"))
  .find((button) => button.textContent.includes("Gerätestatus"));
assert.ok(statusButton, "dynamic device status action is missing");
statusButton.click();
assert.ok(window.document.querySelectorAll("#geraet-dialog .telefon-freigaben input").length >= 4,
  "device grants and personal synchronization settings are missing");
const personalDetails = window.document.querySelector("#geraet-dialog details.telefon-personal-sync");
assert.ok(personalDetails && !personalDetails.open &&
  personalDetails.querySelector("summary").textContent.includes(
    window.MagnolieI18n.gettext("Personal synchronization")),
"personal synchronization is not presented as closed details");
window.App.geraetStatus({ kennung: "phone-1", status: { online: true,
  model: "Pixel 9", manufacturer: "Google", app_version: "1.0.7", os_version: "16",
  battery_percent: 73, charging: "charging", network_transport: "wifi" } });
assert.ok(window.document.querySelector("#geraet-dialog").textContent.includes("Pixel 9") &&
  window.document.querySelector("#geraet-dialog").textContent.includes("73 %") &&
  window.document.querySelector('[data-geraet="app_version"]').textContent === "1.0.7" &&
  !window.document.querySelector('[data-geraet="last_contact_ms"]'),
"device status does not show Magnolie Notes version in place of last contact");
Array.from(window.document.querySelectorAll("#geraet-dialog button"))
  .find((button) => button.textContent === "Aktualisieren").click();
assert.ok(messages.some((message) => message.cmd === "telefon_status_anfordern" &&
  message.kennung === "phone-1"));

/* Die Sicherheitsseite fragt den Journalstand an, und die Antwort baute die
   Einstellungen neu auf – was erneut anfragte. Der Reiter flackerte dadurch
   endlos und war nicht bedienbar. Beides darf sich nicht gegenseitig auslösen. */
const journalVorher = messages.filter((message) => message.cmd === "journal_liste").length;
window.document.querySelector("#einst-tab-sicherheit").click();
assert.strictEqual(messages.filter((message) => message.cmd === "journal_liste").length,
  journalVorher + 1, "the security page must request the journal state exactly once");
const journalAntwort = { intervall: "weekly", letzte: "2026-08-01T10:00:00.0000000+00:00",
  naechste: "2026-08-08T10:00:00.0000000+00:00", status: "ok", fehler: "",
  snapshots: [{ snapshotId: "s1", createdAt: "2026-08-01T10:00:00.0000000+00:00",
    reason: "weekly", integrity: "ok", summary: { termine: 3 }, payload: { size: 4096 } }] };
for (let runde = 0; runde < 5; runde++) window.App.journalStand(journalAntwort);
assert.strictEqual(messages.filter((message) => message.cmd === "journal_liste").length,
  journalVorher + 1, "the journal state answer retriggers itself and makes the tab flicker");
assert.ok(window.document.querySelector("#journal-jetzt") &&
  window.document.querySelector("#einst-seite-sicherheit").textContent.includes("4 KiB"),
"the security page does not show the recovery snapshots");
/* Ein geänderter Stand muss weiterhin ankommen. */
window.App.journalStand(Object.assign({}, journalAntwort, { snapshots: [] }));
assert.ok(window.document.querySelector("#einst-seite-sicherheit").textContent
  .includes(window.MagnolieI18n.gettext("No snapshots yet.")),
"a changed journal state no longer refreshes the security page");

const noteData = T.leereDaten();
for (let i = 0; i < 520; i++) noteData.notizen.push({ id: `note-${i}`,
  titel: `Notiz ${i}`, text: "Text", html: "<p>Text</p>", anhaenge: [],
  notizbuchId: noteData.notizbuecher[0].id, geaendert: "2026-08-14" });
window.App.init({ daten: noteData, neu: false, regional: { language: "de" },
  trayVerfuegbar: true, teamsVerfuegbar: true });
T.wechsel("notizen");
assert.strictEqual(window.document.querySelectorAll(".notiz-seiten > li").length, 250,
  "optimized note chunk renderer does not cap the initial DOM");
assert.ok(Array.from(window.document.querySelectorAll("button"))
  .some((button) => button.textContent === "Mehr anzeigen"),
"note chunk renderer has no continuation action");

for (const token of [
  'cmd: "kde_sms_senden"', 'cmd: "telefon_waehlen"',
  'cmd: "telefon_auflegen"', 'cmd: "telefon_anruf_anzeigen"',
  'cmd: "personal_sync_senden"', 'cmd: "personal_sync_lauf_senden"',
  "personalSyncEntscheidungAnwenden", "personalSyncAutoBeiSicheremWlan",
  "telefonSmsEmpfangen", "telefonEingehenderAnruf", "zeigeAnrufDialog"
]) assert.ok(application.includes(token), `current communication feature missing: ${token}`);
assert.ok(/\.anruf-aktiv-dialog/.test(css) && /\.anruf-chip/.test(css) &&
  /\.sms-verlauf/.test(css) && /\.telefon-pairing-dialog/.test(css));
window.document.querySelector("#telefon-pairing-dialog")?.remove();
window.App.telefonPairingCode({ attempt_id: "probe", code: "123 456",
  display_name: "Magnolie Notes", fingerprint: "AAAA-BBBB" });
assert.ok(window.document.querySelector("#telefon-pairing-dialog")?.textContent.includes("123 456"),
  "automatic phone pairing code is discarded without an existing waiting dialog");
assert.ok(!application.includes("telefon_sms_senden"),
  "obsolete Magnolie SMS transport remains in the web UI");
assert.ok(!application.includes("window.chrome.webview"),
  "a second Windows bridge bypasses the shim contract");
const escapePairing = window.document.querySelector("#telefon-pairing-dialog");
if (escapePairing) window.document.dispatchEvent(new window.KeyboardEvent("keydown",
  { key: "Escape", bubbles: true, cancelable: true }));
window.document.querySelector("#einstellungen-zu")?.click();
for (let index = 0; index < 5; index++) window.document.dispatchEvent(
  new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));

const searchData = T.leereDaten();
const searchYear = new Date().getFullYear();
searchData.termine.push({ id: "search-event", titel: "Alpha meeting", notiz: "Beta note",
  datum: `${searchYear}-06-12`, zeit: "09:00", endZeit: "10:00", kostenstelle: "K-17",
  wiederholung: { art: "none", bis: "" } });
searchData.aufgaben.push({ id: "search-task", titel: "Gamma task", notiz: "Delta",
  faellig: `${searchYear}-06-13`, prio: 1, erledigt: false, personen: [] });
searchData.aufgaben.push({ id: "search-task-done", titel: "Omega task", notiz: "",
  faellig: `${searchYear}-06-14`, prio: 2, erledigt: true, personen: [] });
searchData.kontakte.push({ id: "search-contact", nachname: "Muster", vorname: "Mia",
  notiz: "Epsilon", geburtstag: "1980-04-03" });
searchData.notizen.push({ id: "search-note", titel: "Zeta", text: "Eta",
  html: "<p>Eta</p>", anhaenge: [], notizbuchId: searchData.notizbuecher[0].id,
  geaendert: `${searchYear}-01-01` });
searchData.jahrestage.push({ id: "search-anniversary", name: "Theta",
  datum: "2000-07-14", typ: "birthday" });
searchData.gesundheit.vitalwerte.push({ id: "search-vital", datum: `${searchYear}-01-02`,
  zeit: "08:00", puls: 71, temperatur: 36.5, notiz: "Iota", seite: 987,
  interneKennung: "health-secret" });
window.App.init({ daten: searchData, neu: false, regional: { language: "de" },
  trayVerfuegbar: true, teamsVerfuegbar: true });
const openTask = T.suchTrefferFuer("aufgaben").find((entry) => entry.titel === "Gamma task");
const doneTask = T.suchTrefferFuer("aufgaben").find((entry) => entry.titel === "Omega task");
assert.ok(openTask.text.includes(`13.06.${searchYear}`) && openTask.text.includes("offen") &&
  !openTask.text.includes("erledigt"), "open task indexes the wrong status or date");
assert.ok(doneTask.text.includes("erledigt") && !doneTask.text.includes("als erledigt"),
  "completed task indexes its inverse action");
const healthEntry = T.suchTrefferFuer("gesundheit")[0];
assert.ok(healthEntry.text.includes(`02.01.${searchYear}`) && healthEntry.text.includes("36,5") &&
  healthEntry.meta.includes("36,5"), "localized health date/decimal is absent");
assert.ok(!healthEntry.text.includes("health-secret") && !healthEntry.text.includes("987") &&
  !healthEntry.text.includes("search-vital"), "health search exposes internal fields");
for (const locale of ["de-DE", "en-US", "fr-FR", "ar-EG"]) {
  const language = locale.slice(0, 2);
  if (language === "fr" || language === "ar") window.eval(
    fs.readFileSync(path.join(web, "i18n", language + ".js"), "utf8"));
  window.MagnolieI18n.setLocale(language);
  T.daten().einstellungen.regional.formatLocale = locale;
  const indexed = T.suchTrefferFuer("gesundheit")[0].text;
  const date = new Intl.DateTimeFormat(locale,
    { day: "2-digit", month: "2-digit", year: "numeric" })
    .format(new Date(searchYear, 0, 2)).toLocaleLowerCase(locale);
  const decimal = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 })
    .format(36.5).toLocaleLowerCase(locale);
  assert.ok(indexed.includes(date) && indexed.includes(decimal),
    `localized search values missing for ${locale}`);
}
window.MagnolieI18n.setLocale("de");
T.daten().einstellungen.regional.formatLocale = "de-DE";
const originalSetTimeout = window.setTimeout;
const searchTimers = [];
window.setTimeout = (callback, delay, ...args) => delay === 150
  ? searchTimers.push(() => callback(...args))
  : originalSetTimeout(callback, delay, ...args);
const flushSearch = () => searchTimers.splice(0).forEach((callback) => callback());
const pressFind = () => {
  const event = new window.KeyboardEvent("keydown", { key: "f", ctrlKey: true,
    bubbles: true, cancelable: true });
  window.document.dispatchEvent(event);
  assert.ok(event.defaultPrevented, "Ctrl+F does not suppress browser find");
};
const escape = () => window.document.dispatchEvent(new window.KeyboardEvent("keydown",
  { key: "Escape", bubbles: true, cancelable: true }));
for (const section of ["kalender", "aufgaben", "jahrestage", "planer", "gesundheit"]) {
  T.wechsel(section);
  if (section === "kalender" || section === "planer") {
    const entry = window.document.querySelector(".kalender-suchknopf");
    assert.ok(entry && entry.querySelector("svg") && entry.title === "Suche",
      `visible search button missing for ${section}`);
  }
  const returnFocus = window.document.querySelector('.registerknopf[aria-current="page"]');
  returnFocus.focus(); pressFind();
  const field = window.document.querySelector("#globale-suche");
  pressFind();
  assert.ok(field && window.document.activeElement === field, `search modal missing for ${section}`);
  field.value = section === "gesundheit" ? "Iota 71" : section === "planer"
    ? "Alpha meeting" : section === "kalender" ? "Alpha K-17"
      : section === "aufgaben" ? "Gamma Delta" : "Theta";
  field.dispatchEvent(new window.Event("input", { bubbles: true }));
  flushSearch();
  assert.ok(window.document.querySelector(".such-treffer-knopf"), `search has no result for ${section}`);
  const nextMatch = window.document.querySelector(".such-weiter");
  const previousMatch = window.document.querySelector(".such-zurueck");
  assert.ok(nextMatch && previousMatch && !nextMatch.disabled && !previousMatch.disabled,
    `match navigation missing for ${section}`);
  nextMatch.click();
  assert.ok(window.document.activeElement.classList.contains("such-treffer-knopf") &&
    window.document.activeElement.classList.contains("aktiv") &&
    /^1 \/ /.test(window.document.querySelector(".such-position").textContent),
  `next match is not focused for ${section}`);
  previousMatch.click();
  assert.ok(window.document.activeElement.classList.contains("aktiv"),
    `previous match is not focused for ${section}`);
  escape();
  assert.strictEqual(window.document.activeElement, returnFocus,
    `search does not restore focus for ${section}`);
}
T.wechsel("adressen"); pressFind();
assert.strictEqual(window.document.activeElement,
  window.document.querySelector("#kopf-links input[type=search]"));
T.wechsel("notizen"); pressFind();
assert.strictEqual(window.document.activeElement, window.document.querySelector("#notiz-suche"));
const noteSearch = window.document.querySelector("#notiz-suche");
noteSearch.value = "Eta Zeta";
noteSearch.dispatchEvent(new window.Event("input", { bubbles: true }));
assert.ok(window.document.querySelector('[data-fokus="notiz:search-note"]'),
  "notes do not use multi-word AND matching");
T.wechsel("kalender");
for (const view of ["month", "week", "day"]) {
  T.zustand().kalender.ansicht = view; T.wechsel("aufgaben"); T.wechsel("kalender");
  const today = Array.from(window.document.querySelectorAll("button"))
    .find((button) => button.textContent.trim() === "Heute");
  const searchEntry = window.document.querySelector(".kalender-suchknopf");
  assert.ok(searchEntry && searchEntry.querySelector("svg"), `search button missing in ${view}`);
  searchEntry.click();
  assert.ok(window.document.querySelector("#such-schleier"), `search button does not open in ${view}`);
  escape();
  const context = new window.MouseEvent("contextmenu", { bubbles: true, cancelable: true });
  today.dispatchEvent(context);
  assert.ok(context.defaultPrevented && window.document.querySelector("#such-schleier"),
    `Today context search missing in ${view}`);
  escape();
}
assert.ok(!/console\.(?:log|debug)\([^\n]*such/i.test(application),
  "search code may log sensitive values");
pressFind();
const raceField = window.document.querySelector("#globale-suche");
raceField.value = "Alpha";
raceField.dispatchEvent(new window.Event("input", { bubbles: true }));
raceField.value = "NewestNoMatch";
raceField.dispatchEvent(new window.Event("input", { bubbles: true }));
flushSearch();
assert.ok(!window.document.querySelector(".such-treffer-knopf") &&
  window.document.querySelector("#such-stand").textContent.includes("Nichts gefunden"),
  "an aborted search overwrites the latest input");
escape();
window.setTimeout = originalSetTimeout;

const oldEvents = T.daten().termine;
const oldContacts = T.daten().kontakte;
T.daten().kontakte = Array.from({ length: 10000 }, (_, index) => ({
  id: `load-contact-${index}`, nachname: `Contact ${index}`
}));
T.daten().termine = Array.from({ length: 10000 }, (_, index) => ({
  id: `load-event-${index}`, titel: index === 9999 ? "NeedleCore" : `Event ${index}`,
  datum: "2026-06-12", zeit: "09:00", endZeit: "10:00",
  kontaktId: `load-contact-${index}`, wiederholung: { art: "none", bis: "" }
}));
const searchStart = performance.now();
const loadMatches = T.suchTrefferFuer("kalender", ["needlecore"], 101);
const searchDuration = performance.now() - searchStart;
assert.strictEqual(loadMatches.length, 1, "10,000-record core search loses its match");
assert.ok(searchDuration < 150, `10,000-record core search took ${searchDuration.toFixed(1)} ms`);
T.daten().termine = oldEvents;
T.daten().kontakte = oldContacts;

window.close();

function poValue(block, field) {
  const lines = block.split("\n");
  const start = lines.findIndex((line) => line.startsWith(field + " "));
  if (start < 0) return null;
  let value = JSON.parse(lines[start].slice(field.length + 1));
  for (let index = start + 1; index < lines.length && lines[index].startsWith('"'); index++)
    value += JSON.parse(lines[index]);
  return value;
}

function poEntries(text) {
  const entries = new Map();
  /* Zeilenenden vereinheitlichen: Unter Windows liefert die Prozessausgabe von
     xgettext CRLF, die PO-Dateien im Quellbaum dagegen LF. Ohne diesen Schritt
     zerfaellt der Text nicht in Bloecke und die Extraktion wirkt leer -- der
     Vergleich meldete dann faelschlich saemtliche Zeichenketten als fehlend. */
  for (const block of String(text).replace(/\r\n/g, "\n").split("\n\n")) {
    if (!block || block.startsWith("#~")) continue;
    const id = poValue(block, "msgid");
    if (!id) continue;
    const context = poValue(block, "msgctxt");
    entries.set(context ? context + "\u0004" + id : id, { block,
      value: poValue(block, "msgstr"), plural: poValue(block, "msgid_plural") });
  }
  return entries;
}

const extraction = spawnSync("xgettext", ["--language=JavaScript", "--from-code=UTF-8",
  "--keyword=_", "--keyword=gettext", "--keyword=msgid", "--keyword=pgettext:1c,2",
  "--keyword=ngettext:1,2", "--keyword=uebersetzt:1", "--keyword=uebersetztMehrzahl:1,2",
  "--output=-", path.join(web, "i18n-markers.js"),
  path.join(web, "anwendung.js")], { encoding: "utf8" });
assert.strictEqual(extraction.status, 0, extraction.stderr || "xgettext failed");
const extracted = poEntries(extraction.stdout);
const nativeSources = fs.readdirSync(root).filter((name) => name.endsWith(".cs")).sort()
  .map((name) => path.join(root, name))
  .filter((name) => /^BridgeDispatcher(?:\.|$)/.test(path.basename(name)) ||
    fs.readFileSync(name, "utf8").includes("NativeLocalization.Gettext"));
const nativeExtraction = spawnSync("xgettext", ["--language=C#", "--from-code=UTF-8",
  "--keyword=T", "--keyword=Gettext", "--output=-", ...nativeSources], { encoding: "utf8" });
assert.strictEqual(nativeExtraction.status, 0, nativeExtraction.stderr || "native xgettext failed");
for (const [key, entry] of poEntries(nativeExtraction.stdout)) extracted.set(key, entry);
const template = poEntries(fs.readFileSync(path.join(poDir, "magnolie-organizer.pot"), "utf8"));
assert.deepStrictEqual(Array.from(template.keys()).sort(), Array.from(extracted.keys()).sort(),
  "POT does not match the web source extraction");
assert.ok(template.has("Could not answer"), "answer-call error is absent from POT");

const requiredWindows = ["Could not answer", "Device code: %(code)s",
  "Microsoft sign-in completed.", "Phone error: %(error)s", "Sign in to Microsoft",
  "The phone operation failed.", "Windows Contacts folder"];
const german = poEntries(fs.readFileSync(path.join(poDir, "de.po"), "utf8"));
for (const locale of fs.readFileSync(path.join(poDir, "LINGUAS"), "utf8").trim().split(/\s+/)) {
  const file = path.join(poDir, locale + ".po");
  const check = spawnSync(process.env.MAGNOLIE_MSGFMT || "msgfmt",
    ["--check", "--check-format", "--output-file=/dev/null", file],
    { encoding: "utf8" });
  assert.strictEqual(check.status, 0, check.stderr || `${locale}.po is invalid`);
  const entries = poEntries(fs.readFileSync(file, "utf8"));
  for (const key of template.keys()) {
    const entry = entries.get(key);
    assert.ok(entry && !/^#,.*\bfuzzy\b/m.test(entry.block), `${locale}: missing/fuzzy ${key}`);
    if (!entry.plural) assert.ok(entry.value, `${locale}: untranslated ${key}`);
  }
  if (locale !== "de") for (const key of requiredWindows) {
    assert.ok(entries.has(key) && german.has(key), `${locale}: required Windows translation is missing: ${key}`);
    assert.notStrictEqual(entries.get(key).value, german.get(key).value,
      `${locale}: Windows translation copied from German: ${key}`);
  }
}

const python = process.env.MAGNOLIE_PYTHON;
assert.ok(python, "MAGNOLIE_PYTHON was not passed by the test runner");
const catalogTool = path.join(root, "werkzeuge", "po_zu_js.py");
const generated = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-i18n-check-"));
try {
  for (const locale of fs.readFileSync(path.join(poDir, "LINGUAS"), "utf8").trim().split(/\s+/)) {
    const target = path.join(generated, locale + ".js");
    const result = spawnSync(python, [catalogTool, locale, path.join(poDir, locale + ".po"), target],
      { encoding: "utf8" });
    assert.strictEqual(result.status, 0, result.stderr || `${locale}: catalog generation failed`);
    assert.deepStrictEqual(fs.readFileSync(target), fs.readFileSync(path.join(web, "i18n", locale + ".js")),
      `${locale}: generated runtime catalog is stale`);
  }
} finally {
  fs.rmSync(generated, { recursive: true, force: true });
}
console.log("WEB SMOKE TEST PASSED");
