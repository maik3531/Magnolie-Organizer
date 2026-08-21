"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { canonicalContract, personalSyncPayloads, sendObjects, sha256 } = require("./linux-parity-fixture");

const root = path.resolve(__dirname, "..");
const read = file => fs.readFileSync(path.join(root, file), "utf8");
const windowsUi = read("app/web/anwendung.js");
const windowsDispatcher = read("BridgeDispatcher.cs") + read("BridgeDispatcher.Sync.cs");
const windowsSchemas = read("BridgeDispatcherContract.cs");
const fixture = JSON.parse(read("tests/resources/linux-parity-contract.json"));

assert.strictEqual(fixture.schema, "magnolie-linux-parity-v1", "unbekanntes Linux-Vertragsfixture");
assert.match(fixture.sources["web/anwendung.js"], /^[0-9a-f]{64}$/);
assert.match(fixture.sources["bin/magnolie-organizer"], /^[0-9a-f]{64}$/);
assert.strictEqual(sha256(canonicalContract(fixture)), fixture.contractSha256,
  "Linux-Vertragsfixture wurde nicht kanonisch erzeugt");
assert.ok(fixture.commands.length > 40, "Befehlsfixture ist unplausibel klein");
assert.ok(fixture.callbacks.length > 25, "Callbackfixture ist unplausibel klein");

const windowsCommands = new Set(Array.from(windowsUi.matchAll(/cmd:\s*"([a-z0-9_]+)"/g), match => match[1]));
for (const command of fixture.commands) {
  assert.ok(windowsCommands.has(command), `Windows UI misses Linux contract command ${command}`);
  assert.match(windowsDispatcher, new RegExp(`case "${command}"`), `Windows dispatcher misses ${command}`);
  assert.match(windowsSchemas, new RegExp(`\\["${command}"\\]`), `Windows schema misses ${command}`);
}
for (const name of fixture.callbacks) {
  assert.match(windowsDispatcher, new RegExp(`SendAsync\\("App\\.${name}"`),
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
  /daten:\s*\{ termine: DATEN\.termine,[\s\S]*letzteSyncs: DATEN\.letzteSyncs,[\s\S]*syncMetadaten: DATEN\.syncMetadaten/
]) assert.match(windowsUi, marker);

for (const [alias, canonical] of [["telefonWaehlstatus", "telefonWaehlStatus"],
  ["telefonAnnehmstatus", "telefonAnnehmStatus"], ["telefonAuflegestatus", "telefonAuflegeStatus"]]) {
  assert.match(windowsDispatcher, new RegExp(`App\\.${alias}"\\) function = "App\\.${canonical}`));
  assert.match(windowsUi, new RegExp(`${canonical}\\(nutzlast\\)`));
}

console.log(`FULL PARITY CONTRACT PASSED (${fixture.commands.length} commands, ${fixture.callbacks.length} callbacks)`);
