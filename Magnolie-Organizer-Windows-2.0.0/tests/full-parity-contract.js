"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { canonicalContract, personalSyncPayloads, sendObjects, sha256 } = require("./linux-parity-fixture");

const root = path.resolve(__dirname, "..");
const read = file => fs.readFileSync(path.join(root, file), "utf8");
const windowsUi = read("app/web/anwendung.js");
const windowsDispatcher = fs.readdirSync(root).filter(file => /^BridgeDispatcher(?:\.[A-Za-z]+)?\.cs$/.test(file))
  .map(read).join("\n") + read("MainForm.cs");
const windowsCallbacks = windowsDispatcher + read("TelefonCoordinator.cs");
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
assert.ok(fixture.commands.includes("mutations_snapshot") &&
  !fixture.commands.some(command => ["journal_aufbewahrung", "journal_erzeugen",
    "journal_intervall"].includes(command)),
"Linux fixture must expose automatic mutation snapshots without manual journal controls");

const windowsCommands = new Set(Array.from(windowsUi.matchAll(/cmd:\s*"([a-z0-9_]+)"/g), match => match[1]));
const commandAliases = { sync_bestaetigen: "sync_commit" };
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
  if (command === linuxAudioCommand) continue;
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
  if (name === linuxAudioCallback) continue;
  assert.match(windowsCallbacks, new RegExp(`(?:SendAsync|emit)\\("App\\.${name}"`),
    `Windows dispatcher misses App.${name}`);
  assert.match(windowsUi, new RegExp(`\\n    ${name}\\([^)]*\\) \\{`), `Windows UI misses App.${name}`);
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

console.log(`FULL PARITY CONTRACT PASSED (${fixture.commands.length - 1} shared commands, ${fixture.callbacks.length - 1} shared callbacks; Linux-only HFP routing and Windows unsupported capability checked)`);
