#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "..");
const props = fs.readFileSync(path.join(root, "Directory.Build.props"), "utf8");
const version = /<Version>([^<]+)<\/Version>/.exec(props)?.[1];
if (!/^\d+\.\d+\.\d+$/.test(version || "")) throw new Error("Kanonische Version fehlt.");
const installerName = `Magnolie-Organizer-Windows-${version}-Setup-x64.exe`;
const python = process.env.MAGNOLIE_PYTHON || ["python3", "python"].find((candidate) =>
  spawnSync(candidate, ["--version"], { encoding: "utf8" }).status === 0);
if (!python) throw new Error("Python 3 for localization tests is missing");
process.env.MAGNOLIE_PYTHON = python;

let failed = false;
for (const test of ["handbook-protection.js", "localization-completeness.js", "web-smoke.js",
  "structured-appointment-parity.js", "handbook-smoke.js",
  "native-integration-smoke.js", "full-parity-contract.js", "linux-live-parity.js",
  "nsis-installer-fixture.js", "installer-publication.js", "manifest-policy.js", "release-audit.js"]) {
  const result = spawnSync(process.execPath, [path.join(__dirname, test), version, installerName], {
    stdio: "inherit",
    env: { ...process.env, MAGNOLIE_PYTHON: python }
  });
  if (result.error) { console.error(result.error); failed = true; }
  else if (result.status !== 0) failed = true;
}
if (failed) process.exit(1);
