#!/usr/bin/env node
"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { generate } = require("./linux-parity-fixture");

const root = path.resolve(__dirname, "..");
const parent = path.dirname(root);
const configured = process.env.MAGNOLIE_LINUX_SOURCE;
const candidates = configured ? [path.resolve(configured)] : fs.readdirSync(parent, { withFileTypes: true })
  .filter(entry => entry.isDirectory() &&
    (entry.name === "magnolie-organizer" || /^magnolie-organizer-\d/.test(entry.name)) &&
    entry.name !== path.basename(root))
  .map(entry => path.join(parent, entry.name));
const linuxRoot = candidates.find(candidate =>
  fs.statSync(path.join(candidate, "web", "anwendung.js"), { throwIfNoEntry: false })?.isFile() &&
  fs.statSync(path.join(candidate, "bin", "magnolie-organizer"), { throwIfNoEntry: false })?.isFile());
if (!linuxRoot) {
  console.log("LINUX LIVE PARITY SKIPPED (kein Linux-Quellbaum vorhanden)");
  process.exit(0);
}
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "resources", "linux-parity-contract.json"), "utf8"));
const semanticFields = ["schema", "commands", "callbacks", "payloadSchemas", "personalSyncPayloads"];
const semanticContract = contract => Object.fromEntries(semanticFields.map(field => [field, contract[field]]));
assert.deepStrictEqual(semanticContract(generate(linuxRoot)), semanticContract(fixture),
  `Linux-Vertragsfixture ist veraltet; aktualisieren mit tests/generate-linux-parity-fixture.js ${linuxRoot}`);
const linuxUi = fs.readFileSync(path.join(linuxRoot, "web", "anwendung.js"), "utf8");
const windowsUi = fs.readFileSync(path.join(root, "app", "web", "anwendung.js"), "utf8");
for (const [name, source] of [["Linux", linuxUi], ["Windows", windowsUi]]) {
  assert.match(source, /\["generic-dav", "Standard CalDAV\/CardDAV"\]/,
    `${name}: generische DAV-Kontotypauswahl fehlt`);
  assert.match(source, /kontoArt:\s*nextcloudEntwurf\.kontoArt/,
    `${name}: kontoArt fehlt im DAV-Speichervertrag`);
  assert.match(source, /briefkastenAktiv = !generisch/,
    `${name}: generisches DAV sperrt den Briefkasten nicht`);
  assert.match(source, /startsWith\("generic-"\) \? davName/,
    `${name}: generische Quellen werden nicht neutral beschriftet`);
  assert.match(source, /supportsVtodo === false[\s\S]{0,180}Appointments remain available/,
    `${name}: VTODO-Fähigkeitshinweis fehlt`);
  assert.ok(/setupImportWarteschlange = Array\.isArray\(roh\.stagedImports\)/.test(source) &&
    /roh\.stagedImports\.filter\([\s\S]*?roh\.oneTimeImports/.test(source),
    `${name}: gepruefte Assistentenimporte oder der explizite Altformat-Pfad fehlen`);
  assert.ok(/typeof quelle === "object" && quelle\.payload[\s\S]*?App\.importErgebnis\(quelle\.payload\)/.test(source),
    `${name}: vorbereitete Importe werden nicht an die normale Importentscheidung uebergeben`);
  assert.doesNotMatch(source, /setupTelefonAktionen/,
    `${name}: veraltete automatische Telefonkopplung ist noch aktiv`);
  assert.match(source, /setTimeout\(starteNaechstenSetupImport, 0\)/,
    `${name}: Assistentenaktionen werden nicht direkt gestartet`);
}
console.log(`LINUX LIVE PARITY PASSED (${linuxRoot})`);
