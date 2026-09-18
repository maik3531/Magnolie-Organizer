#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const [publishArg, outputArg] = process.argv.slice(2);
if (!publishArg || !outputArg) {
  throw new Error("Aufruf: GenerateInstallManifests.js <Publish-Verzeichnis> <Ausgabeverzeichnis>");
}

const publish = path.resolve(publishArg);
const output = path.resolve(outputArg);
const coreFiles = [];
const handbookFiles = [];

function visit(directory, relative = "") {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name, "en"))) {
    if (entry.isSymbolicLink()) throw new Error(`Symbolische Verknüpfung ist im Installer-Payload nicht erlaubt: ${entry.name}`);
    const childRelative = relative ? `${relative}/${entry.name}` : entry.name;
    const child = path.join(directory, entry.name);
    if (entry.isDirectory()) visit(child, childRelative);
    else if (entry.isFile() && !entry.name.toLowerCase().endsWith(".pdb")) {
      (childRelative.startsWith("handbuch/") ? handbookFiles : coreFiles).push(childRelative);
    }
  }
}

function createManifest(files, ownedFiles) {
  const allFiles = [...files, ...ownedFiles];
  const directories = new Set();
  for (const file of allFiles) {
    if (/[|\r\n]/.test(file) || path.isAbsolute(file) || file.split("/").includes("..")) {
      throw new Error(`Unsicherer Installerpfad: ${file}`);
    }
    let parent = path.posix.dirname(file);
    while (parent !== ".") {
      directories.add(parent);
      parent = path.posix.dirname(parent);
    }
  }
  const lines = [
    ...allFiles.sort((a, b) => a.localeCompare(b, "en")).map(file => `F|${file.replaceAll("/", "\\")}`),
    ...[...directories].sort((a, b) => b.split("/").length - a.split("/").length || b.localeCompare(a, "en"))
      .map(directory => `D|${directory.replaceAll("/", "\\")}`)
  ];
  return Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from(`${lines.join("\r\n")}\r\n`, "utf16le")]);
}

if (!fs.statSync(publish).isDirectory()) throw new Error(`Publish-Verzeichnis fehlt: ${publish}`);
fs.mkdirSync(output, { recursive: true });
visit(publish);
fs.writeFileSync(path.join(output, "core.manifest"), createManifest(coreFiles, [
  ".magnolie-core.manifest",
  ".magnolie-installer",
  "Magnolie Organizer deinstallieren.exe"
]));
fs.writeFileSync(path.join(output, "handbook.manifest"), createManifest(handbookFiles, [".magnolie-handbook.manifest"]));
