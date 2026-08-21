#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const configPath = process.argv[2] || path.resolve(__dirname, "..", "Ausgabe", "build-config.json");
const expectedHash = process.env.MAGNOLIE_CONTRIBUTOR_HASH;

try {
  if (!/^[0-9a-fA-F]{64}$/.test(expectedHash || "")) {
    throw new Error("MAGNOLIE_CONTRIBUTOR_HASH fehlt oder ist ungültig");
  }
  const stat = fs.statSync(configPath);
  if (!stat.isFile() || stat.size > 4096) throw new Error("Datei fehlt oder ist zu groß");
  const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
  if (!config || typeof config !== "object" || Array.isArray(config) ||
      typeof config.contributorHash !== "string" ||
      !/^[0-9a-fA-F]{64}$/.test(config.contributorHash)) {
    throw new Error("contributorHash ist keine 64-stellige Hexfolge");
  }
  if (config.contributorHash !== expectedHash.toLowerCase())
    throw new Error("contributorHash entspricht nicht MAGNOLIE_CONTRIBUTOR_HASH");
} catch (error) {
  console.error(`Offizieller Installer abgebrochen: ungültige build-config.json (${error.message}).`);
  process.exit(1);
}

console.log("Offizielle build-config.json geprüft.");
