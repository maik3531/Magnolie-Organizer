#!/usr/bin/env node
"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const [installer, record, expectedName] = process.argv.slice(2);
const fail = message => { throw new Error(`Installer-Buildrecord: ${message}`); };

if (!installer || !record || !expectedName || path.basename(installer) === path.basename(record))
  fail("Installer, separater Record und Artefaktname sind erforderlich");
if (!/^Magnolie-Organizer-Windows-\d+\.\d+\.\d+-Setup-x64\.exe$/.test(expectedName))
  fail("Artefaktname ist nicht kanonisch");
const before = fs.statSync(installer, { bigint: true, throwIfNoEntry: false });
if (!before?.isFile() || before.size === 0n) fail("Installer fehlt oder ist leer");
const sha256 = crypto.createHash("sha256").update(fs.readFileSync(installer)).digest("hex");
const after = fs.statSync(installer, { bigint: true });
if (before.dev !== after.dev || before.ino !== after.ino || before.size !== after.size || before.mtimeNs !== after.mtimeNs)
  fail("Installer wurde während der Hashbildung verändert");

const contents = `${JSON.stringify({ schema: "magnolie-installer-build-v1", artifact: expectedName, bytes: Number(after.size), sha256 })}\n`;
const temporary = `${record}.tmp-${process.pid}-${Date.now()}`;
try {
  fs.writeFileSync(temporary, contents, { encoding: "ascii", flag: "wx", mode: 0o600 });
  fs.renameSync(temporary, record);
} finally {
  fs.rmSync(temporary, { force: true });
}
