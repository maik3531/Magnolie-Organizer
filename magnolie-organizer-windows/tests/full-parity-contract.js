"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { canonicalContract, commands, personalSyncPayloads, sendObjects, sha256 } = require("./linux-parity-fixture");

const root = path.resolve(__dirname, "..");
const read = file => fs.readFileSync(path.join(root, file), "utf8");
const windowsUi = read("app/web/anwendung.js");
const windowsMediaUi = read("app/web/phone-media.js");
const windowsMediaDispatcher = read("DeviceFileBridge.cs");
const windowsMediaRequest = read("DeviceFileUiRequest.cs");
const windowsDispatcher = fs.readdirSync(root).filter(file => /^BridgeDispatcher(?:\.[A-Za-z]+)?\.cs$/.test(file))
  .map(read).join("\n") + read("MainForm.cs");
const windowsCallbacks = windowsDispatcher + fs.readdirSync(root)
  .filter(file => /^(?:Telefon|Magnolienbaum)Coordinator(?:\.[A-Za-z]+)?\.cs$/.test(file)).map(read).join("\n");
const windowsSchemas = read("BridgeDispatcherContract.cs");
const fixture = JSON.parse(process.env.MAGNOLIE_PARITY_FIXTURE
  ? fs.readFileSync(process.env.MAGNOLIE_PARITY_FIXTURE, "utf8") : read("tests/resources/linux-parity-contract.json"));
assert.deepStrictEqual([...sendObjects('Bruecke.sende({cmd: "sync_bestaetigen", transactionId})')[0]],
  [["cmd", '"sync_bestaetigen"'], ["transactionId", "transactionId"]]);
for (const property of ["...payload", "[transactionId]: value", "transactionId = value", "get transactionId() {}", "transactionId, transactionId"])
  assert.throws(() => sendObjects('Bruecke.sende({cmd: "sync_bestaetigen", ' + property + '})'),
    /Eigenschaft/, "Unsupported or duplicate payload properties must fail closed: " + property);

assert.strictEqual(fixture.schema, "magnolie-linux-parity-v1", "unbekanntes Linux-Vertragsfixture");
assert.match(fixture.sources["web/anwendung.js"], /^[0-9a-f]{64}$/);
assert.match(fixture.sources["bin/magnolie-organizer"], /^[0-9a-f]{64}$/);
assert.strictEqual(sha256(canonicalContract(fixture)), fixture.contractSha256,
  "Linux-Vertragsfixture wurde nicht kanonisch erzeugt");
assert.strictEqual(canonicalContract({ ...fixture, sources: {
  "web/anwendung.js": "0".repeat(64), "bin/magnolie-organizer": "f".repeat(64)
} }), canonicalContract(fixture), "Provenienz-Hashes dürfen den semantischen Vertrag nicht verändern");
assert.ok(fixture.commands.length > 40, "Befehlsfixture ist unplausibel klein");
assert.ok(fixture.callbacks.length > 25, "Callbackfixture ist unplausibel klein");
assert.ok(fixture.commands.includes("mutations_snapshot"),
"Linux fixture must retain mandatory mutation snapshots alongside the explicit journal policies from #142");

const windowsCommands = new Set(commands(windowsUi + "\n" + windowsMediaUi));
const commandAliases = { sync_bestaetigen: "sync_commit", handbuch_herunterladen: "update_herunterladen" };
// Refs #829: media adapters deliberately have different wire names. Check
// each real Windows sender/action/handler instead of inventing dummy aliases.
// This is a source-contract check, not native media/device acceptance.
const mediaActions = {
  medien_backup: ["backup_list", "backup_restore"],
  medien_papierkorb: ["trash_list", "trash_restore", "trash_purge", "trash_empty", "trash_thumbnail", "trash_preview"],
  telefon_foto_aktion: ["shared_setting", "receive_consent", "discover", "page", "sync_shared", "cancel", "request_read"],
  telefon_fotoziel_waehlen: ["pick_destination", "default_destination"],
  telefon_videoziel_waehlen: ["pick_destination", "default_destination"],
  telefon_medien_senden: ["send_consent"],
  telefon_sammlungsordner: ["pick_collection_source"]
};
function validateMediaRoutes(ui, dispatcher, request) {
  for (const action of new Set(Object.values(mediaActions).flat())) {
    assert.match(ui, new RegExp(`\\brequest\\("${action}"`), `Windows media UI misses action ${action}`);
    assert.match(dispatcher, new RegExp(`case "${action}"`), `Windows media dispatcher misses action ${action}`);
    assert.ok(request.includes(`"${action}"`), `Windows exact media request parser misses ${action}`);
  }
}
validateMediaRoutes(windowsMediaUi, windowsMediaDispatcher, windowsMediaRequest);
assert.throws(() => validateMediaRoutes(windowsMediaUi.replaceAll('request("backup_restore"', 'request("unknown"'),
  windowsMediaDispatcher, windowsMediaRequest), /UI misses action backup_restore/);
assert.throws(() => validateMediaRoutes(windowsMediaUi, windowsMediaDispatcher.replace('case "send_consent"', 'case "unknown"'),
  windowsMediaRequest), /dispatcher misses action send_consent/);
assert.match(windowsUi, /window\.MagnolieMedia\.createRecoveryPanel\(/);
assert.match(windowsUi, /window\.MagnolieMedia\.createPanel\(/);
assert.match(read("app/web/index.html"), /src="phone-media\.js"/);
assert.match(windowsMediaDispatcher, /partial void HandleNativeMediaUi\([\s\S]*?HandleNativeMediaUiAsync\(message\)/);
assert.match(windowsDispatcher, /HandleNativeMediaUi\(message, ref mediaHandling\)/);
assert.match(windowsMediaDispatcher, /NativeMediaUiRequest\.Parse\(/);
assert.match(windowsMediaRequest, /TelefonProtocolContract\.ExactObject\(value, fields\.ToArray\(\)\)/);
assert.match(windowsMediaUi, /\["images", "Photos", "pictures"\], \["video", "Videos", "video_destination"\]/);
// The deprecated Linux backup-folder helper is unmounted (#429/#759).
// If it becomes reachable again, generate() includes it and this gate fails
// until that deliberate product/UI change receives a new mapping.
assert.ok(!fixture.commands.includes("telefon_backupziel"), "Separate backup-location chooser became part of the Linux contract again");

const webcamCommands = ["telefon_webcam_stand", "telefon_webcam_start", "telefon_webcam_stop"];
for (const command of webcamCommands) {
  assert.match(windowsUi, new RegExp(`\\brequest\\("${command}"`), `Windows webcam UI misses ${command}`);
  assert.match(windowsDispatcher, new RegExp(`case "${command}"`), `Windows webcam dispatcher misses ${command}`);
  assert.match(windowsSchemas, new RegExp(`\\["${command}"\\]`), `Windows webcam schema misses ${command}`);
}
assert.match(windowsDispatcher, /DesktopWebcamActionAsync\(message\)/);
assert.match(windowsDispatcher, /form\.ConfirmDesktopWebcam\(selected, RequireProfile\)/);
// Windows ships the manual in the Organizer installer; Linux has a separate DEB.
assert.ok(!windowsCommands.has("handbuch_herunterladen"));
assert.ok(windowsCommands.has("update_herunterladen") && windowsCommands.has("update_installieren"));
assert.ok(!windowsUi.includes('handbuchHolen.id = "handbuch-herunterladen"'));
// Native HFP routing belongs only to the Linux host. The Win32 deployment must
// explicitly remain unsupported, not add dummy routing commands for parity.
const linuxAudioCommand = "telefon_anruf_audio_einstellung";
const linuxAudioCallback = "telefonAnrufAudio";
assert.ok(fixture.commands.includes(linuxAudioCommand) && fixture.callbacks.includes(linuxAudioCallback));
assert.ok(!windowsCommands.has(linuxAudioCommand));
assert.match(read("WindowsBluetoothRadio.cs"), /\["state"\] = "unsupported"/);
assert.match(read("WindowsBluetoothRadio.cs"), /\["approved_capability"\] = false/);
assert.doesNotMatch(read("WindowsBluetoothRadio.cs"), /RequestAccessAsync|RegisterApp|RegisterForTransport/);
for (const command of fixture.commands) {
  if ([linuxAudioCommand, "telefon_bluetooth_einstellungen", "telefon_anruf_audio_pruefen"].includes(command)) continue;
  if (command === "telefon_webcam_aktion") continue; // explicit native Windows webcam routes checked above
  if (Object.hasOwn(mediaActions, command)) {
    assert.ok(windowsCommands.has("telefon_medien"), `Windows media envelope missing for ${command}`);
    assert.match(windowsDispatcher, /case "telefon_medien"/);
    assert.match(windowsSchemas, /\["telefon_medien"\]/);
    continue;
  }
  const nativeCommand = commandAliases[command] || command;
  assert.ok(windowsCommands.has(nativeCommand), `Windows UI misses Linux contract command ${command}`);
  assert.match(windowsDispatcher, new RegExp(`case "${nativeCommand}"`), `Windows dispatcher misses ${command}`);
  assert.match(windowsSchemas, new RegExp(`\\["${nativeCommand}"\\]`), `Windows schema misses ${command}`);
}
const commits = sendObjects(windowsUi).filter(object => object.get("cmd") === '"sync_commit"');
assert.ok(commits.length, "Windows journal ACK is absent");
for (const object of commits) assert.deepStrictEqual([...object.keys()].sort(), ["cmd", "transactionId"],
  "The journal ACK alias must preserve the exact Linux payload fields");
assert.match(windowsDispatcher, /new TelefonCoordinator\(paths, HandleTelefonEventAsync/);
assert.match(windowsDispatcher, /await form\.SendAsync\(function, message \?\? payload\)/);
for (const name of fixture.callbacks) {
  if (name === linuxAudioCallback || name === "telefonAnrufAudioGespeichert") continue;
  if (name === "telefonFotoErgebnis") {
    assert.match(windowsMediaDispatcher, /form\.SendAsync\("MagnolieMedia\.receive"/);
    assert.match(windowsMediaUi, /window\.MagnolieMedia\s*=\s*\{[\s\S]*\breceive\(reply\)/);
    assert.match(windowsMediaUi, /reply\.device_id !== item\.peerId/);
    continue;
  }
  if (name === "telefonWebcam") {
    assert.match(read("BridgeDispatcher.DesktopWebcam.cs"), /form\.SendAsync\("App\.kdeMedien"/);
    assert.match(windowsUi, /\n\s+kdeMedien\(value\)\s*\{/);
    continue;
  }
  assert.match(windowsCallbacks, new RegExp(`(?:SendAsync|emit)\\("App\\.${name}"`),
    `Windows dispatcher misses App.${name}`);
  assert.ok(new RegExp(`\\n\\s+(?:async\\s+)?${name}\\([^)]*\\)\\s*\\{`).test(windowsUi), `Windows UI misses App.${name}`);
}

function validatePersonalSyncPayloads(source) {
  for (const object of sendObjects(source)) {
    const commandValue = object.get("cmd") || "";
    const commandMatch = /^(?:"([^"]*)"|'([^']*)')$/.exec(commandValue);
    const command = commandMatch && (commandMatch[1] ?? commandMatch[2]);
    if (!fixture.payloadSchemas[command]) continue;
    const allowed = new Set(fixture.payloadSchemas[command]);
    const unexpected = [...object.keys()].filter(key => !allowed.has(key));
    assert.deepStrictEqual(unexpected, [], `${command} has forbidden top-level fields: ${unexpected.join(", ")}`);
  }
}

validatePersonalSyncPayloads(windowsUi);
assert.throws(() => validatePersonalSyncPayloads(`Bruecke.sende({
  art: "personal_sync.deletion_decision", trigger: "manual",
  cmd: "personal_sync_senden", kennung: peer.device_id, inhalt: { trigger: "manual" }
})`), /forbidden top-level fields: trigger/, "top-level trigger fixture must fail regardless of property order");
assert.deepStrictEqual(personalSyncPayloads(windowsUi), fixture.personalSyncPayloads,
  "Windows personal sync payloads differ from the Linux contract fixture");

for (const marker of [
  /baumNachrichtEmpfangen\(\)/,
  /telefonAnnehmStatus\(nutzlast\)/,
  /letzteSyncs:\s*\{ kalender:\s*\{\}, adressbuecher:\s*\{\} \}/,
  /nextcloud:\s*\{ kalender:\s*\{\}, adressbuecher:\s*\{\}/,
  /const request = \{ format: format, run_id: run, trigger: trigger, modules: modules \}/,
  /daten:\s*\{ termine: \(DATEN\.syncAbgleichBasis \|\| DATEN\)\.termine,[\s\S]*letzteSyncs: DATEN\.letzteSyncs,[\s\S]*syncMetadaten: DATEN\.syncMetadaten/
]) assert.match(windowsUi, marker);

for (const [alias, canonical] of [["telefonWaehlstatus", "telefonWaehlStatus"],
  ["telefonAnnehmstatus", "telefonAnnehmStatus"], ["telefonAuflegestatus", "telefonAuflegeStatus"]]) {
  assert.match(windowsDispatcher, new RegExp(`App\\.${alias}"\\) function = "App\\.${canonical}`));
  assert.match(windowsUi, new RegExp(`${canonical}\\(nutzlast\\)`));
}

console.log(`FULL PARITY CONTRACT PASSED (${fixture.commands.length} command contracts, ${fixture.callbacks.length} callback contracts; ${Object.keys(mediaActions).length} media adapters and native webcam routes checked; inactive backup chooser and Linux-only HFP routing classified)`);
