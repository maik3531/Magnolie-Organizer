#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "..");
const generator = path.join(root, "installer", "GenerateInstallManifests.js");
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-nsis-transaction-"));

function write(base, relative, contents) {
  const target = path.join(base, relative);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, contents);
}

function generate(publish, output) {
  const result = spawnSync(process.execPath, [generator, publish, output], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr || result.stdout);
}

function entries(manifest) {
  const buffer = fs.readFileSync(manifest);
  assert.deepEqual([...buffer.subarray(0, 2)], [0xff, 0xfe], "Manifest benötigt UTF-16LE-BOM");
  return buffer.subarray(2).toString("utf16le").trim().split(/\r?\n/).filter(Boolean)
    .map(line => ({ kind: line.slice(0, 1), relative: line.slice(2).replaceAll("\\", path.sep) }));
}

function copyOwned(source, destination, manifest) {
  for (const entry of entries(manifest).filter(entry => entry.kind === "F")) {
    const from = path.join(source, entry.relative);
    if (fs.existsSync(from)) write(destination, entry.relative, fs.readFileSync(from));
  }
}

function deleteOwned(install, manifest) {
  for (const entry of entries(manifest)) {
    const target = path.join(install, entry.relative);
    if (entry.kind === "F") fs.rmSync(target, { force: true });
    else if (fs.existsSync(target)) {
      try { fs.rmdirSync(target); } catch (error) { if (error.code !== "ENOTEMPTY") throw error; }
    }
  }
}

function classifyExistingInstall({ marker, coreManifest }) {
  const validMarker = marker === "MagnolieOrganizer.Windows.v1" || marker === "2.0.0";
  if (!validMarker) throw new Error("foreign install directory");
  return coreManifest ? "installed" : "managed-remnant";
}

function installFixture({ failAt }) {
  const fixture = fs.mkdtempSync(path.join(temp, "case-"));
  const oldPublish = path.join(fixture, "old-publish");
  const newPublish = path.join(fixture, "new-publish");
  const oldManifests = path.join(fixture, "old-manifests");
  const newManifests = path.join(fixture, "new-manifests");
  const install = path.join(fixture, "install");
  const backup = path.join(fixture, "backup");
  write(oldPublish, "Magnolie Organizer.exe", "old application");
  write(oldPublish, "obsolete.dll", "obsolete");
  write(oldPublish, "handbuch/index.html", "old handbook");
  write(newPublish, "Magnolie Organizer.exe", "new application");
  write(newPublish, "current.dll", "current");
  write(newPublish, "handbuch/index.html", "new handbook");
  generate(oldPublish, oldManifests);
  generate(newPublish, newManifests);

  copyOwned(oldPublish, install, path.join(oldManifests, "core.manifest"));
  copyOwned(oldPublish, install, path.join(oldManifests, "handbook.manifest"));
  for (const name of ["core", "handbook"]) fs.copyFileSync(path.join(oldManifests, `${name}.manifest`), path.join(install, `.magnolie-${name}.manifest`));
  write(install, ".magnolie-installer", "MagnolieOrganizer.Windows.v1");
  write(install, "Magnolie Organizer deinstallieren.exe", "old uninstaller");
  write(install, "notes-from-user.txt", "must remain");

  fs.mkdirSync(backup, { recursive: true });
  for (const name of ["core", "handbook"]) {
    const manifest = path.join(install, `.magnolie-${name}.manifest`);
    fs.copyFileSync(manifest, path.join(backup, `previous-${name}.manifest`));
    copyOwned(install, backup, manifest);
    deleteOwned(install, manifest);
  }
  for (const name of [".magnolie-installer", "Magnolie Organizer deinstallieren.exe"]) {
    if (fs.existsSync(path.join(install, name))) fs.copyFileSync(path.join(install, name), path.join(backup, name));
    fs.rmSync(path.join(install, name), { force: true });
  }

  const rollback = () => {
    for (const name of ["handbook", "core"]) deleteOwned(install, path.join(newManifests, `${name}.manifest`));
    for (const name of ["core", "handbook"]) {
      copyOwned(backup, install, path.join(backup, `previous-${name}.manifest`));
      fs.copyFileSync(path.join(backup, `previous-${name}.manifest`), path.join(install, `.magnolie-${name}.manifest`));
    }
    for (const name of [".magnolie-installer", "Magnolie Organizer deinstallieren.exe"]) fs.copyFileSync(path.join(backup, name), path.join(install, name));
  };

  copyOwned(newPublish, install, path.join(newManifests, "core.manifest"));
  if (failAt === "extract") { rollback(); return install; }
  copyOwned(newPublish, install, path.join(newManifests, "handbook.manifest"));
  for (const name of ["core", "handbook"]) fs.copyFileSync(path.join(newManifests, `${name}.manifest`), path.join(install, `.magnolie-${name}.manifest`));
  write(install, "Magnolie Organizer deinstallieren.exe", "new uninstaller");
  if (failAt === "marker") { rollback(); return install; }
  write(install, ".magnolie-installer", "MagnolieOrganizer.Windows.v1");
  return install;
}

function uninstallFixture({ marker, locked = "", unknown = false }) {
  const fixture = fs.mkdtempSync(path.join(temp, "uninstall-"));
  const publish = path.join(fixture, "publish");
  const manifests = path.join(fixture, "manifests");
  const install = path.join(fixture, "install");
  write(publish, "Magnolie Organizer.exe", "application");
  write(publish, "current.dll", "library");
  write(publish, "handbuch/index.html", "handbook");
  generate(publish, manifests);
  copyOwned(publish, install, path.join(manifests, "core.manifest"));
  copyOwned(publish, install, path.join(manifests, "handbook.manifest"));
  for (const name of ["core", "handbook"]) {
    fs.copyFileSync(path.join(manifests, `${name}.manifest`),
      path.join(install, `.magnolie-${name}.manifest`));
  }
  write(install, ".magnolie-installer", marker);
  write(install, "Magnolie Organizer deinstallieren.exe", "uninstaller");
  if (unknown) write(install, "notes-from-user.txt", "preserve");

  const valid = marker === "MagnolieOrganizer.Windows.v1" || marker === "2.0.0";
  if (!valid) return { install, failed: true };
  const protectedFiles = new Set([".magnolie-core.manifest", ".magnolie-handbook.manifest",
    ".magnolie-installer", "Magnolie Organizer deinstallieren.exe"]);
  let failed = false;
  for (const name of ["handbook", "core"]) {
    for (const entry of entries(path.join(install, `.magnolie-${name}.manifest`))) {
      if (entry.kind !== "F" || protectedFiles.has(entry.relative)) continue;
      if (entry.relative === locked) { failed = true; continue; }
      fs.rmSync(path.join(install, entry.relative), { force: true });
    }
  }
  if (failed) return { install, failed };
  for (const name of protectedFiles) fs.rmSync(path.join(install, name), { force: true });
  if (unknown) write(install, ".magnolie-installer", "MagnolieOrganizer.Windows.v1");
  return { install, failed };
}

try {
  assert.equal(classifyExistingInstall({ marker: "MagnolieOrganizer.Windows.v1", coreManifest: true }),
    "installed", "gültige Besitzliste wurde nicht als updatefähige Installation erkannt");
  assert.equal(classifyExistingInstall({ marker: "MagnolieOrganizer.Windows.v1", coreManifest: false }),
    "managed-remnant", "Restordner nach Deinstallation wurde fälschlich als vollständige Altversion erkannt");
  assert.throws(() => classifyExistingInstall({ marker: "foreign-product", coreManifest: false }),
    /foreign install directory/, "fremder Restordner wurde zur Wiederinstallation freigegeben");
  const success = installFixture({});
  assert.equal(fs.readFileSync(path.join(success, "Magnolie Organizer.exe"), "utf8"), "new application");
  assert.ok(!fs.existsSync(path.join(success, "obsolete.dll")), "obsolete verwaltete Datei blieb zurück");
  assert.equal(fs.readFileSync(path.join(success, "notes-from-user.txt"), "utf8"), "must remain");
  assert.ok(fs.existsSync(path.join(success, ".magnolie-core.manifest")), "Core-Besitzliste fehlt");

  for (const failAt of ["extract", "marker"]) {
    const rolledBack = installFixture({ failAt });
    assert.equal(fs.readFileSync(path.join(rolledBack, "Magnolie Organizer.exe"), "utf8"), "old application");
    assert.equal(fs.readFileSync(path.join(rolledBack, "obsolete.dll"), "utf8"), "obsolete");
    assert.equal(fs.readFileSync(path.join(rolledBack, ".magnolie-installer"), "utf8"), "MagnolieOrganizer.Windows.v1");
    assert.equal(fs.readFileSync(path.join(rolledBack, "Magnolie Organizer deinstallieren.exe"), "utf8"), "old uninstaller");
    assert.equal(fs.readFileSync(path.join(rolledBack, "notes-from-user.txt"), "utf8"), "must remain");
  }
  for (const marker of ["MagnolieOrganizer.Windows.v1", "2.0.0"]) {
    const removed = uninstallFixture({ marker });
    assert.equal(removed.failed, false, `gültiger Produktmarker wurde abgelehnt: ${marker}`);
    assert.ok(!fs.existsSync(path.join(removed.install, "Magnolie Organizer.exe")),
      `verwaltete Anwendung blieb nach Deinstallation zurück: ${marker}`);
  }
  const rejected = uninstallFixture({ marker: "foreign-product" });
  assert.equal(fs.readFileSync(path.join(rejected.install, "Magnolie Organizer.exe"), "utf8"),
    "application", "ungültiger Marker durfte Programmdateien löschen");
  const locked = uninstallFixture({ marker: "MagnolieOrganizer.Windows.v1",
    locked: "Magnolie Organizer.exe" });
  assert.equal(locked.failed, true, "gesperrte Programmdatei meldet keinen unvollständigen Abbau");
  for (const evidence of [".magnolie-core.manifest", ".magnolie-installer",
    "Magnolie Organizer deinstallieren.exe"]) {
    assert.ok(fs.existsSync(path.join(locked.install, evidence)),
      `Besitznachweis ging nach fehlgeschlagener Löschung verloren: ${evidence}`);
  }
  const remnants = uninstallFixture({ marker: "2.0.0", unknown: true });
  assert.equal(fs.readFileSync(path.join(remnants.install, "notes-from-user.txt"), "utf8"), "preserve");
  assert.equal(fs.readFileSync(path.join(remnants.install, ".magnolie-installer"), "utf8"),
    "MagnolieOrganizer.Windows.v1", "Restordner bleibt für eine sichere Neuinstallation unmarkiert");
  console.log("NSIS-Transaktionsfixtures bestanden.");
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
