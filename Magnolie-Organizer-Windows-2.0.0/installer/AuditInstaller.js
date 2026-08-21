#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const crypto = require("node:crypto");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { artifactPayload } = require("../build/AuditWebPayload");

const [installer, publish, expectedName, buildRecord] = process.argv.slice(2);
const markerName = "WINDOWS-RUNTIME-UNVERIFIED.txt";
const marker = "windowsRuntimeVerified=false\nwindowsVmValidationRequired=true\nartifactTrust=UNSIGNED\n";
const fail = message => { throw new Error(`Installer-Audit: ${message}`); };

if (!installer || !publish || !expectedName || !buildRecord || path.resolve(installer) === path.resolve(buildRecord) ||
    !/^Magnolie-Organizer-Windows-\d+\.\d+\.\d+-Setup-x64\.exe$/.test(expectedName) ||
    /-UNSIGNED/i.test(expectedName)) fail("sichtbarer Installername ist nicht kanonisch");
if (!fs.statSync(installer, { throwIfNoEntry: false })?.isFile()) fail("Installer fehlt");
if (!fs.statSync(buildRecord, { throwIfNoEntry: false })?.isFile()) fail("separater Installer-Buildrecord fehlt");
if (!fs.statSync(publish, { throwIfNoEntry: false })?.isDirectory()) fail("Publishbaum fehlt");

let record;
try { record = JSON.parse(fs.readFileSync(buildRecord, "ascii")); }
catch { fail("Installer-Buildrecord ist kein gültiges JSON"); }
if (!record || Array.isArray(record) || Object.keys(record).sort().join(",") !== "artifact,bytes,schema,sha256" ||
    record.schema !== "magnolie-installer-build-v1" || record.artifact !== expectedName ||
    !Number.isSafeInteger(record.bytes) || record.bytes <= 0 || !/^[0-9a-f]{64}$/.test(record.sha256))
  fail("Installer-Buildrecord ist nicht kanonisch");
const before = fs.statSync(installer, { bigint: true });
const actualHash = crypto.createHash("sha256").update(fs.readFileSync(installer)).digest();
const after = fs.statSync(installer, { bigint: true });
if (before.dev !== after.dev || before.ino !== after.ino || before.size !== after.size || before.mtimeNs !== after.mtimeNs)
  fail("Installer wurde während des Audits verändert");
if (BigInt(record.bytes) !== after.size || !crypto.timingSafeEqual(actualHash, Buffer.from(record.sha256, "hex")))
  fail("Installer stimmt nicht mit dem atomaren Buildrecord überein");

const markerPath = path.join(publish, markerName);
const crossCompile = fs.statSync(markerPath, { throwIfNoEntry: false })?.isFile();
if (crossCompile && fs.readFileSync(markerPath).toString("ascii") !== marker)
  fail(`${markerName} ist nicht exakt der freigegebene Cross-Marker`);

const image = fs.readFileSync(installer);
if (image.length < 0x40 || image[0] !== 0x4d || image[1] !== 0x5a) fail("DOS/PE-Kopf fehlt");
const peOffset = image.readUInt32LE(0x3c);
if (peOffset < 0x40 || peOffset + 24 > image.length || image.subarray(peOffset, peOffset + 4).compare(Buffer.from("PE\0\0", "binary")) !== 0)
  fail("PE-Signatur fehlt oder ist beschädigt");
const machine = image.readUInt16LE(peOffset + 4);
const sectionCount = image.readUInt16LE(peOffset + 6);
const optionalSize = image.readUInt16LE(peOffset + 20);
const optional = peOffset + 24;
if (![0x14c, 0x8664].includes(machine) || sectionCount < 1 || sectionCount > 96 || optionalSize < 68 || optional + optionalSize > image.length)
  fail("PE-COFF-Kopf ist ungültig oder außerhalb der Datei");
const magic = image.readUInt16LE(optional);
if (magic !== 0x10b && magic !== 0x20b) fail("PE Optional Header hat ein unbekanntes Format");
const checksumOffset = optional + 64;
const sizeOfHeaders = image.readUInt32LE(optional + 60);
const sectionTable = optional + optionalSize;
if (sizeOfHeaders < sectionTable + sectionCount * 40 || sizeOfHeaders > image.length)
  fail("PE-Headergröße umfasst die Section-Tabelle nicht");
const ranges = [];
for (let index = 0; index < sectionCount; index++) {
  const section = sectionTable + index * 40;
  if (section + 40 > image.length) fail("PE-Section-Tabelle ist abgeschnitten");
  const rawSize = image.readUInt32LE(section + 16);
  const rawOffset = image.readUInt32LE(section + 20);
  if (!rawSize) continue;
  if (rawOffset < sizeOfHeaders || rawOffset + rawSize > image.length || rawOffset + rawSize < rawOffset)
    fail(`PE-Section ${index + 1} zeigt außerhalb der Datei`);
  ranges.push([rawOffset, rawOffset + rawSize]);
}
ranges.sort((left, right) => left[0] - right[0]);
for (let index = 1; index < ranges.length; index++) if (ranges[index][0] < ranges[index - 1][1])
  fail("PE-Sections überlappen sich in der Datei");
const expectedChecksum = image.readUInt32LE(checksumOffset);
if (expectedChecksum) {
  let sum = 0;
  for (let offset = 0; offset < image.length; offset += 2) {
    const word = offset === checksumOffset || offset === checksumOffset + 2 ? 0 :
      image[offset] | ((offset + 1 < image.length ? image[offset + 1] : 0) << 8);
    sum = (sum + word) >>> 0;
    sum = (sum & 0xffff) + (sum >>> 16);
  }
  sum = ((sum & 0xffff) + (sum >>> 16) + image.length) >>> 0;
  if (sum !== expectedChecksum) fail("PE-Prüfsumme ist ungültig");
}
const originalKey = Buffer.from("OriginalFilename\0", "utf16le");
const originalValue = Buffer.from(`${expectedName}\0`, "utf16le");
const keyOffset = image.indexOf(originalKey);
if (keyOffset < 0 || image.indexOf(originalValue, keyOffset + originalKey.length) < 0 ||
    image.indexOf(originalValue, keyOffset + originalKey.length) > keyOffset + 4096)
  fail("OriginalFilename ist nicht kanonisch");

const sevenZip = [process.env.SEVENZIP, "7z", "7zz", "7za"].filter(Boolean).find(command => {
  const probe = spawnSync(command, ["i"], { stdio: "ignore" });
  return !probe.error && probe.status === 0;
});
if (!sevenZip) fail("7z für die NSIS-Prüfung fehlt");
const tested = spawnSync(sevenZip, ["t", "-bso1", "-bse1", installer], { encoding: "utf8" });
if (tested.status !== 0 || !/Type\s*=\s*Nsis/i.test(`${tested.stdout}${tested.stderr}`))
  fail("Installer ist kein extrahierbares NSIS-Archiv");

const extracted = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-installer-audit-"));
try {
  const extraction = spawnSync(sevenZip, ["x", "-y", `-o${extracted}`, installer], { encoding: "utf8" });
  if (extraction.status !== 0) fail(`NSIS-Extraktion fehlgeschlagen: ${extraction.stderr || extraction.stdout}`);
  const walk = base => fs.readdirSync(base, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(base, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });
  const published = walk(publish).filter(file => path.extname(file).toLowerCase() !== ".pdb");
  for (const source of published) {
    const relative = path.relative(publish, source);
    const target = path.join(extracted, relative);
    if (!fs.statSync(target, { throwIfNoEntry: false })?.isFile()) fail(`Publishdatei fehlt im Installer: ${relative}`);
    if (!fs.readFileSync(source).equals(fs.readFileSync(target))) fail(`Installerdatei ist nicht bytegleich: ${relative}`);
  }
  artifactPayload(publish, extracted);
  const extractedMarker = path.join(extracted, markerName);
  if (crossCompile && fs.readFileSync(extractedMarker).toString("ascii") !== marker)
    fail("eingebetteter Cross-Marker ist nicht exakt");
  if (!crossCompile && fs.existsSync(extractedMarker)) fail("Installer enthält unerwarteten Cross-Marker");
} finally {
  fs.rmSync(extracted, { recursive: true, force: true });
}

console.log(`Installer-Audit bestanden: ${expectedName}`);
