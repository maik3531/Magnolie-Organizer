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
    (/^magnolie-organizer-\d/.test(entry.name) || entry.name === "magnolie-organizer-stamm") &&
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
console.log(`LINUX LIVE PARITY PASSED (${linuxRoot})`);
