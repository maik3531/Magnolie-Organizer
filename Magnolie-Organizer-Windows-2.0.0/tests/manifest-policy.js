#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "..");
const version = process.argv[2];
const installerName = process.argv[3];
const pwsh = [process.env.MAGNOLIE_TEST_PWSH, "/tmp/opencode/powershell-7.4.13/pwsh", "pwsh"].filter(Boolean).find(command =>
  spawnSync(command, ["-NoProfile", "-Command", "$PSVersionTable.PSVersion.Major"], { encoding: "utf8" }).status === 0);
if (!pwsh) {
  console.log("Manifest-Policy-Test übersprungen: PowerShell 7 fehlt.");
  process.exit(0);
}
const quote = value => value.replaceAll("'", "''");
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-manifest-policy-"));
try {
  const installer = path.join(temp, installerName);
  const one = path.join(temp, "one.xml");
  const two = path.join(temp, "two.xml");
  const report = path.join(temp, "follow-up.json");
  fs.writeFileSync(installer, "signed installer fixture\n");
  const xml = `<?xml version="1.0"?><update><windows><version>${version}</version><url>https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/${installerName}</url><sha256>${"a".repeat(64)}</sha256></windows><signature>embedded-fixture</signature></update>`;
  fs.writeFileSync(one, xml); fs.writeFileSync(two, xml);
  const updater = path.join(root, "build", "UpdateManifest.ps1");
  const updateCommand = `function Get-AuthenticodeSignature { [pscustomobject]@{ Status='Valid'; SignerCertificate=[pscustomobject]@{Subject='CN=Release'}; TimeStamperCertificate=[pscustomobject]@{} } }; & '${quote(updater)}' -Installer '${quote(installer)}' -ExpectedPublisher 'CN=Release' -RootManifest '${quote(one)}' -LinuxSourceManifest '${quote(two)}'`;
  const rejected = spawnSync(pwsh, ["-NoProfile", "-Command", updateCommand], { encoding: "utf8", env: { ...process.env, OS: "Windows_NT" } });
  assert.notEqual(rejected.status, 0, "eingebettete signature wurde akzeptiert");
  assert.match(`${rejected.stdout}${rejected.stderr}`, /Signiertes Manifest wird nicht verändert/);
  assert.equal(fs.readFileSync(one, "utf8"), xml, "signiertes Manifest wurde verändert");
  assert.equal(fs.readFileSync(two, "utf8"), xml, "signiertes Manifest wurde verändert");

  const auditor = path.join(root, "build", "AuditUpdateManifest.ps1");
  const auditCommand = `& '${quote(auditor)}' -Manifest @('${quote(one)}','${quote(two)}') -Report '${quote(report)}'`;
  const audited = spawnSync(pwsh, ["-NoProfile", "-Command", auditCommand], { encoding: "utf8" });
  assert.notEqual(audited.status, 0, `${audited.stderr || audited.stdout}`);
  const result = JSON.parse(fs.readFileSync(report, "utf8"));
  assert.ok(result.every(entry => entry.windowsReleaseStatus === "UNVEROEFFENTLICHT" && entry.embeddedSignature));
  console.log("Manifest-Signatur- und Veröffentlichungs-Policy bestanden.");
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
