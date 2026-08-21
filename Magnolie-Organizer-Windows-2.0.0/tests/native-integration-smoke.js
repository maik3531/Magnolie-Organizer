"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), "utf8");
const bridge = read("BridgeDispatcher.cs");
const mainForm = read("MainForm.cs");
const application = read("app", "web", "anwendung.js");
const html = read("app", "web", "index.html");

assert.match(mainForm, /__MAGNOLIE_BRUECKE__/,
  "native host must inject the randomized bridge name");
assert.match(application, /window\.__MAGNOLIE_BRUECKE__/);
assert.match(application, /messageHandlers\[this\.name\]/);
assert.doesNotMatch(application, /window\.chrome\.webview/);

for (const command of [
  "speichern", "beenden_abgebrochen", "beenden_bereit", "tray_einstellungen",
  "gesamtarchiv_waehlen", "gesamtarchiv_pruefen", "gesamtarchiv_importieren",
  "gesamtarchiv_exportieren", "notiz_anhang_datei", "graph_anmelden",
  "graph_abmelden", "sync", "sozial"
]) assert.match(bridge, new RegExp(`case "${command}"`),
  `Windows bridge command missing: ${command}`);

assert.match(application, /notiz_anhang_datei/,
  "note attachment open/save must still use the Windows host");
assert.match(application, /graph_anmelden/);
assert.match(application, /sync-windows-quelle/);
assert.match(application, /teamsVerfuegbar/);
assert.match(application, /teams-call/);
assert.match(application, /gesamtarchiv_exportieren/);
assert.match(application, /contributor_pruefen/);
assert.match(application, /trayEinstellungen/);

for (const command of [
  "telefon_stand", "telefon_ein", "telefon_pairing_oeffnen",
  "telefon_pairing_bestaetigen", "telefon_freigabe", "telefon_status_anfordern",
  "telefon_waehlen", "telefon_annehmen", "telefon_auflegen", "telefon_bluetooth_schalten",
  "telefon_anruf_anzeigen", "telefon_anruf_lautstaerke_wiederherstellen",
  "telefon_sms_benachrichtigen", "telefon_meldung_anzeigen",
  "kde_pairing_start", "kde_pairing_confirm", "kde_pairing_complete",
  "kde_reconnect", "kde_sms_senden", "personal_sync_einstellungen",
  "personal_sync_senden", "personal_sync_lauf_senden",
  "personal_sync_attachment_index", "telefon_personal_sync_commit"
]) assert.ok(application.includes(`cmd: "${command}"`),
  `expected native command contract missing from web UI: ${command}`);

const communicationCommands = new Set(Array.from(application.matchAll(
  /cmd:\s*"((?:telefon|kde|personal_sync)_[a-z0-9_]+)"/g), (match) => match[1]));
for (const command of communicationCommands) assert.match(bridge,
  new RegExp(`case "${command}"`),
  `Windows bridge does not dispatch current web command: ${command}`);
assert.doesNotMatch(bridge, /case "telefon_sms_senden"/,
  "obsolete Magnolie SMS transport remains in the Windows dispatcher");
for (const callback of ["StatusChanged", "SmsReceived", "PairingChanged"])
  assert.match(bridge, new RegExp(`kdeConnectSms\\.${callback} \\+=`),
    `long-lived KDE callback is not connected: ${callback}`);
assert.match(read("BridgeDispatcher.Sync.cs"),
  /personalSyncWebCommits[\s\S]*WaitAsync\(TimeSpan\.FromSeconds\(30\)\)/,
  "personal sync ACK is not gated by the web durable-save commit");
assert.match(application, /nachDauerhaftemSpeichern\(\(\) => Bruecke\.sende\(\{ cmd: "sync_commit"/,
  "provider sync result is not acknowledged after durable UI commit");
assert.match(application, /ausstehendeTransaktion[\s\S]*cmd: "sync", transactionId: transactionId/,
  "provider sync retry is not bound to a persisted unique transaction");
assert.match(application, /delete DATEN\.syncMetadaten\.nextcloud\.ausstehendeTransaktion/,
  "successful provider sync does not retire its transaction before the follow-up sync");
assert.match(bridge, /case "sync_commit": CommitSynchronization/,
  "provider sync commit is not dispatched");
assert.match(mainForm, /JSON\.parse\([^)]+\)/,
  "WebView callback arguments are not JSON-decoded from serialized data");
assert.match(mainForm, /BalloonTipClicked[\s\S]*App\.telefonAntwort/,
  "Windows notification click does not open the SMS reply composer");

for (const event of [
  "graphKonfiguration", "graphAnmeldung", "graphAbmeldung",
  "telefonStand", "telefonPairingOffen", "telefonPairingCode", "telefonGekoppelt",
  "geraetOeffnen", "geraetStatus", "kdePairingCode", "kdePairingStatus",
  "telefonSmsStatus", "telefonSmsEmpfangen", "telefonMeldung", "telefonFehler",
  "telefonEingehenderAnruf", "telefonWaehlStatus", "telefonAnnehmStatus", "telefonAuflegeStatus",
  "personalSync", "personalSyncFehler"
]) assert.match(application, new RegExp(`\\b${event}\\(nutzlast\\)`),
  `expected native event contract missing from App: ${event}`);

assert.doesNotMatch(html, /id="(?:telefon|sms)-schleier"/,
  "obsolete static communication dialogs remain in HTML");
assert.doesNotMatch(application, /cmd: "telefon_sms_senden"/,
  "obsolete Magnolie SMS command remains in UI");
assert.match(application, /if \(laufenderSpeicher\) return;/,
  "save serialization guard is missing");
assert.match(application, /vorBeenden\(\)[\s\S]*?speichereJetzt\(true\)/,
  "close does not flush pending data");

console.log("NATIVE INTEGRATION SMOKE TEST PASSED");
