"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const windowsRoot = path.resolve(__dirname, "..");
const linuxRoot = path.resolve(windowsRoot, "..", "magnolie-organizer-2.0.0");

function lade(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://appointment.test/", pretendToBeVisual: true
  });
  const window = dom.window;
  window.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  window.MagnolieI18n.setLocale("en");
  window.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
  window.document.dispatchEvent(new window.Event("DOMContentLoaded", { bubbles: true }));
  window.App.init({ daten: {}, neu: true, regional: { language: "en" } });
  return { dom, window, T: window.OrganizerTest };
}

const linuxWeb = path.join(linuxRoot, "web");
const apps = [["Windows", lade(path.join(windowsRoot, "app", "web"))]];
if (fs.existsSync(path.join(linuxWeb, "index.html"))) apps.unshift(["Linux", lade(linuxWeb)]);

const ics = ["BEGIN:VEVENT", "X-PROVIDER-SAFE:keep", "LOCATION:Raum 7",
  "ORGANIZER;CN=Alex Example:mailto:alex@example.test",
  "ATTENDEE;CN=Bea Example;PARTSTAT=ACCEPTED;ROLE=CHAIR;RSVP=TRUE:mailto:bea@example.test",
  "ATTACH;FMTTYPE=application/pdf;FILENAME=Plan.pdf;SIZE=2048:https://drive.google.com/file/d/1",
  "BEGIN:VALARM", "TRIGGER:-PT15M", "ACTION:DISPLAY", "END:VALARM",
  "BEGIN:VALARM", "TRIGGER:-PT2H", "ACTION:DISPLAY", "END:VALARM",
  "BEGIN:VALARM", "TRIGGER:-P3D", "ACTION:DISPLAY", "END:VALARM",
  "BEGIN:VALARM", "TRIGGER;VALUE=DATE-TIME:20260820T070000Z", "ACTION:EMAIL",
  "X-ALARM-SAFE:keep", "END:VALARM", "END:VEVENT"];

const normalisierte = [];
for (const [name, app] of apps) {
  const { T, window } = app;
  const termin = T.normalisiere(window.JSON.parse(JSON.stringify({ termine: [{ id: "event", uid: "event@example.test",
    datum: "2026-08-20", zeit: "10:00", endZeit: "11:00", titel: "Planung",
    wiederholung: { art: "monthly", bis: "", ordinal: 2, wochentag: "TU" },
    individuelleErinnerungTage: 3, icsRoundtrip: ics,
    kalenderQuelle: { id: "work", name: "Arbeit", gruppe: "Team", farbe: "#336699",
      anbieter: "Nextcloud" }, providerMetadaten: { google: { eventId: "42", accessToken: "weg" },
      bad_token: { value: "weg" } } }] }))).termine[0];
  assert.strictEqual(termin.ort, "Raum 7", `${name}: LOCATION fehlt`);
  assert.deepStrictEqual(termin.alarme.filter(alarm => alarm.bearbeitbar)
    .map(alarm => alarm.offsetMinuten).sort((a, b) => a - b), [15, 120, 4320],
  `${name}: relative Alarme oder Legacy-Deduplizierung falsch`);
  assert.ok(termin.alarme.some(alarm => !alarm.bearbeitbar &&
    alarm.triggerRaw === "20260820T070000Z"), `${name}: absoluter Alarm nicht sichtbar`);
  assert.deepStrictEqual([termin.organisator.name, termin.organisator.email],
    ["Alex Example", "alex@example.test"], `${name}: ORGANIZER falsch`);
  assert.deepStrictEqual([termin.teilnehmer[0].status, termin.teilnehmer[0].rolle,
    termin.teilnehmer[0].rsvp], ["ACCEPTED", "CHAIR", true], `${name}: ATTENDEE falsch`);
  assert.deepStrictEqual([termin.kalenderAnhaenge[0].name, termin.kalenderAnhaenge[0].mimeType,
    termin.kalenderAnhaenge[0].groesse, termin.kalenderAnhaenge[0].anbieter],
  ["Plan.pdf", "application/pdf", 2048, "Google Drive"], `${name}: ATTACH falsch`);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(T.saubereProviderMetadaten(
    { google: { eventId: "42", accessToken: "weg" }, bad_token: { value: "weg" } }))),
    { google: { eventId: "42" } }, `${name}: direkter Provider-Filter falsch`);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(termin.providerMetadaten)),
    { google: { eventId: "42" } },
    `${name}: Provider-Metadaten nicht sicher begrenzt`);
  assert.deepStrictEqual(T.normalisiere({ termine: [termin] }).termine[0], termin,
    `${name}: Normalisierung ist nicht idempotent`);
  const syncMeta = T.normalisiere({ termine: [{ id: "sync", datum: "2026-08-20",
    zeit: "08:00:59", endZeit: "09:15:01", icsSequence: 7,
    icsAenderungszeitFehlt: true, icsEndeFehlt: true, icsNullDauer: true,
    syncKonflikte: Array.from({ length: 20 }, (_, i) => ({ id: `k${i}` })) }] }).termine[0];
  assert.deepStrictEqual([syncMeta.zeit, syncMeta.endZeit, syncMeta.icsSequence,
    syncMeta.icsAenderungszeitFehlt, syncMeta.icsEndeFehlt, syncMeta.icsNullDauer,
    syncMeta.syncKonflikte.length, syncMeta.syncKonflikte[0].id],
  ["08:00", "09:15", 7, true, true, true, 16, "k4"],
  `${name}: Sync-Metadaten oder Sekundenzeiten gehen verloren`);
  const taskTimes = T.normalisiere({ aufgaben: [{ id: "task-times",
    startZeit: "07:30:45", faelligZeit: "17:05:01" }] }).aufgaben[0];
  assert.deepStrictEqual([taskTimes.startZeit, taskTimes.faelligZeit], ["07:30", "17:05"],
    `${name}: Aufgabenzeiten mit Sekunden gehen verloren`);
  const ersteAusnahme = T.normalisiere({ termine: [{ id: "first-exception",
    datum: "2026-08-03", titel: "Gelöschter Serienstart",
    wiederholung: { art: "weekly" }, icsAusnahmen: ["2026-08-03"] }] }).termine[0];
  T.daten().termine.push(ersteAusnahme);
  T.planeSpeichern();
  assert.ok(!T.termineAm("2026-08-03").some(eintrag => eintrag.id === ersteAusnahme.id),
    `${name}: erste gelöschte Serieninstanz bleibt sichtbar`);
  T.daten().termine = T.daten().termine.filter(eintrag => eintrag.id !== ersteAusnahme.id);
  T.planeSpeichern();

  const bearbeitet = JSON.parse(JSON.stringify(termin));
  bearbeitet.ort = "Raum 9";
  bearbeitet.organisator.name = "Alex Neu";
  bearbeitet.teilnehmer[0].status = "TENTATIVE";
  bearbeitet.kalenderAnhaenge[0].name = "Neu.pdf";
  bearbeitet.icsRoundtrip = T.spiegeleTerminInIcs(bearbeitet);
  assert.strictEqual(bearbeitet.icsRoundtrip.filter(line => line.startsWith("LOCATION:")).length, 1,
    `${name}: LOCATION dupliziert`);
  assert.ok(bearbeitet.icsRoundtrip.includes("LOCATION:Raum 9") &&
    bearbeitet.icsRoundtrip.includes("X-PROVIDER-SAFE:keep") &&
    bearbeitet.icsRoundtrip.includes("X-ALARM-SAFE:keep") &&
    bearbeitet.icsRoundtrip.includes("TRIGGER;VALUE=DATE-TIME:20260820T070000Z"),
  `${name}: Bearbeitung verliert unbekannte ICS-Daten`);
  assert.strictEqual(bearbeitet.icsRoundtrip.filter(line => line === "BEGIN:VALARM").length, 4,
    `${name}: Alarmblöcke dupliziert oder verloren`);
  const serienZeilen = ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE", "RDATE:20260901T100000",
    "EXDATE:20260908T100000", "EXRULE:FREQ=MONTHLY",
    "RECURRENCE-ID:20260915T100000"];
  const komplexeSerie = Object.assign({}, termin, { icsKomplex: true,
    wiederholung: { art: "none", bis: "" }, icsRoundtrip: serienZeilen });
  assert.deepStrictEqual(T.spiegeleTerminInIcs(komplexeSerie).filter(line =>
    serienZeilen.includes(line)), serienZeilen,
  `${name}: Speichern zerstört die Struktur einer komplexen importierten Serie`);
  const einfacheSerie = Object.assign({}, komplexeSerie, { icsKomplex: false });
  assert.strictEqual(T.spiegeleTerminInIcs(einfacheSerie).filter(line =>
    serienZeilen.includes(line)).length, 0,
  `${name}: intern erzeugte Serien behalten veraltete rohe Serienfelder`);

  assert.deepStrictEqual([
    T.anbieterAusUri("https://drive.google.com/file/d/1"),
    T.anbieterAusUri("https://onedrive.live.com/x"),
    T.anbieterAusUri("https://dropbox.com/x"),
    T.anbieterAusUri("https://cloud.example/remote.php/dav/files/a"),
    T.anbieterAusUri("https://example.test/x"), T.anbieterAusUri("file:///tmp/a"),
    T.anbieterAusUri("javascript:alert(1)")
  ], ["Google Drive", "OneDrive", "Dropbox", "Nextcloud/WebDAV", "Web", "lokal", "unbekannt"],
  `${name}: Provider-Matrix falsch`);

  T.daten().termine = [termin];
  for (const begriff of ["Raum", "Arbeit", "Team", "Alex", "Bea", "Plan.pdf"]) {
    assert.strictEqual(T.suchTrefferFuer("kalender", [begriff.toLowerCase()]).length, 1,
      `${name}: Suche findet ${begriff} nicht`);
  }
  const druck = T.oeffneDruckvorschau(termin, "kalender");
  assert.ok(druck.textContent.includes("Raum 7") && druck.textContent.includes("Arbeit") &&
    druck.textContent.includes("Alex Example") && druck.textContent.includes("Bea Example") &&
    druck.textContent.includes("Plan.pdf"), `${name}: Druckprojektion unvollständig`);
  druck.remove();

  const baum = T.begrenzeBaumTermin(Object.assign({}, termin, { titel: "x".repeat(1000),
    notiz: "n".repeat(30000), providerMetadaten: { google: { token: "secret" } },
    icsRoundtrip: Array.from({ length: 400 }, () => "X:" + "y".repeat(3000)) }));
  assert.strictEqual(baum.titel.length, 500, `${name}: Baumtitel unbegrenzt`);
  assert.strictEqual(baum.notiz.length, 20000, `${name}: Baumnotiz unbegrenzt`);
  assert.ok(baum.icsRoundtrip.length <= 256 && baum.icsRoundtrip.every(line => line.length <= 2000),
    `${name}: Baum-ICS unbegrenzt`);
  assert.ok(!("providerMetadaten" in baum) && !JSON.stringify(baum).includes("secret"),
    `${name}: Baum enthält Provider-Secrets`);
  const baumGeheim = T.begrenzeBaumTermin(Object.assign({}, termin, {
    icsRoundtrip: ["X-ACCESS-TOKEN:secret", "X-SAFE:keep"],
    kalenderAnhaenge: [{ uri: "https://example.test/a?access_token=secret", name: "privat" }]
  }));
  assert.deepStrictEqual(baumGeheim.icsRoundtrip, ["X-SAFE:keep"],
    `${name}: Baum-ICS enthält ein Token`);
  assert.strictEqual(baumGeheim.kalenderAnhaenge.length, 0,
    `${name}: Baum-Anhang enthält eine signierte URI`);

  const lokal = T.normalisiere({ termine: [{ id: "local", datum: "2026-08-21", titel: "Lokal",
    kalenderAnhaenge: [{ uri: "file:///tmp/private.pdf", name: "private.pdf" }] }] }).termine[0];
  T.oeffneTerminBlatt(lokal, lokal.datum);
  const anhangZeile = window.document.querySelector(".tb-kalender-anhang");
  assert.ok(anhangZeile.textContent.includes("local / not opened") &&
    !Array.from(anhangZeile.querySelectorAll("button")).some(button => button.textContent === "Open"),
  `${name}: lokale URI kann geöffnet werden`);
  window.document.querySelector("#termin-schleier").remove();

  const verschoben = T.normalisiere({ termine: [{ id: "move", uid: "move@example.test",
    datum: "2026-08-22", titel: "Verschieben", sync: true, syncKalenderUid: "remote",
    syncQuellen: { remote: { id: "remote-object", etag: "old" } },
    kalenderQuelle: { id: "remote", name: "Remote" } }] }).termine[0];
  T.daten().termine.push(verschoben);
  T.oeffneTerminBlatt(verschoben, verschoben.datum);
  window.document.querySelector("#tb-kalenderquelle").value = "";
  window.document.querySelector("#tb-fertig").click();
  assert.strictEqual(verschoben.syncKalenderUid, "", `${name}: Kalenderwechsel bleibt gebunden`);
  assert.strictEqual(verschoben.sync, false, `${name}: Kalenderwechsel bleibt synchronisiert`);
  assert.ok(T.daten().geloescht.termine.some(eintrag => eintrag.uid === verschoben.uid &&
    eintrag.syncKalenderUid === "remote"), `${name}: alter Kalender erhält keine Löschung`);
  assert.ok(!("remote" in verschoben.syncQuellen),
    `${name}: gelöschte Remote-Zuordnung bleibt am Live-Termin`);
  normalisierte.push(JSON.parse(JSON.stringify(termin)));
}

if (normalisierte.length === 2) {
  assert.deepStrictEqual(normalisierte[0], normalisierte[1],
    "Linux- und Windows-Terminmodell sind fachlich nicht identisch");
}

for (const [, app] of apps) app.dom.window.close();
console.log(normalisierte.length === 2
  ? "STRUCTURED APPOINTMENT PARITY PASSED"
  : "WINDOWS STRUCTURED APPOINTMENT MODEL PASSED (standalone source archive)");
