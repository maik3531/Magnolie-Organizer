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
const results = [];
for (const test of ["ui-bugfixes.js", "aur-sms-regressions.js", "planner-sms-regressions.js", "phone-settings-regressions.js", "device-identifiers.js", "call-audio-regressions.js", "background-sms.js", "background-receipt-vectors.js", "personal-asset-protection.js", "handbook-protection.js", "localization-completeness.js", "web-smoke.js",
  "oversized-note-safety.js", "desktop-state-regressions.js", "save-custom-regressions.js", "custom-time-regressions.js", "planned-sms-save-regressions.js", "asr-sms-regressions.js", "desktop-data-regressions.js", "frontend-integrity.js", "recurrence-worker.js", "recurrence-golden.js",
  "month-recurrence-stability.js", "birthday-display.js", "baum-contact-batch.js", "baum-contact-review.js", "journal-selection.js", "bundled-handbook-update.js", "structured-appointment-parity.js", "handbook-smoke.js", "handbook-windows-variants.js",
  "native-integration-smoke.js", "full-parity-contract.js", "linux-live-parity.js",
  "nsis-installer-fixture.js", "installer-publication.js", "manifest-policy.js", "release-audit.js"]) {
  const result = spawnSync(process.execPath, [path.join(__dirname, test),
    ...(test === "aur-sms-regressions.js" ? [] : [version, installerName])], {
    stdio: "inherit",
    env: { ...process.env, MAGNOLIE_PYTHON: python }
  });
  if (result.error) { console.error(result.error); failed = true; }
  else if (result.status !== 0) failed = true;
  results.push([test, !result.error && result.status === 0]);
}
console.log("\nComplete Windows web test results:");
for (const [test, passed] of results) console.log(`${passed ? "PASS" : "FAIL"} ${test}`);
console.log(`${results.filter(([, passed]) => passed).length}/${results.length} test programs passed`);
if (failed) process.exit(1);
