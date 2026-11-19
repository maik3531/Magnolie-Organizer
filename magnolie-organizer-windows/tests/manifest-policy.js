#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { findExecutable, assertSpawned } = require("./native-test-process");

const root = path.resolve(__dirname, "..");
const version = process.argv[2];
const installerName = process.argv[3];
const defaultPowerShell = process.platform === "win32" ? path.join(process.env.ProgramFiles || "C:\\Program Files", "PowerShell/7/pwsh.exe") : "pwsh";
const detectedPowerShell = findExecutable([process.env.MAGNOLIE_TEST_PWSH || defaultPowerShell],
  ["-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.Major"], 7);
const pwsh = detectedPowerShell.command;
if (!pwsh) {
  assert.ok(!process.env.MAGNOLIE_TEST_PWSH, "Configured PowerShell could not start: " + detectedPowerShell.diagnostics.join("; "));
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
  // Exercise the canonical policy with controlled verification dependencies,
  // not an installed SignTool attempting to verify this text placeholder.
  const fixtureRoot = path.join(temp, "source-fixture"), fixtureBuild = path.join(fixtureRoot, "build");
  fs.mkdirSync(fixtureBuild, { recursive: true });
  fs.copyFileSync(path.join(root, "Directory.Build.props"), path.join(fixtureRoot, "Directory.Build.props"));
  const updaterSource = path.join(root, "build", "UpdateManifest.ps1");
  const updater = path.join(fixtureBuild, "UpdateManifest.ps1");
  fs.copyFileSync(updaterSource, updater);
  assert.ok(fs.readFileSync(updater).equals(fs.readFileSync(updaterSource)), "manifest policy source copy changed");
  const verifier = path.join(temp, "controlled-verifier.exe"), verified = path.join(temp, "controlled-verification.txt");
  fs.writeFileSync(verifier, "INERT-VERIFIER-NOT-AN-EXECUTABLE\n");
  fs.writeFileSync(path.join(fixtureBuild, "Release.Common.ps1"), `. '${quote(path.join(root, "build", "Release.Common.ps1"))}'
function Invoke-NativeCommand {
  param($FilePath, $ArgumentList)
  if ($FilePath -cne '${quote(verifier)}' -or $ArgumentList.Count -ne 5 -or
      ($ArgumentList[0..3] -join ' ') -cne 'verify /pa /all /tw' -or $ArgumentList[4] -cne '${quote(installer)}') {
    throw 'Unexpected native command in controlled manifest-policy fixture.'
  }
  [IO.File]::WriteAllText('${quote(verified)}', 'controlled signature verification only')
}
`);
  const updateCommand = `function Get-AuthenticodeSignature { param($LiteralPath) if ($LiteralPath -cne '${quote(installer)}') { throw 'Unexpected signature read' }; [pscustomobject]@{ Status='Valid'; SignerCertificate=[pscustomobject]@{Subject='CN=Release'}; TimeStamperCertificate=[pscustomobject]@{} } }; & '${quote(updater)}' -Installer '${quote(installer)}' -ExpectedPublisher 'CN=Release' -SignTool '${quote(verifier)}' -RootManifest '${quote(one)}' -LinuxSourceManifest '${quote(two)}'`;
  const rejected = spawnSync(pwsh, ["-NoProfile", "-Command", updateCommand], { encoding: "utf8", env: { ...process.env, OS: "Windows_NT" } });
  assertSpawned(rejected, "Manifest update policy");
  assert.notEqual(rejected.status, 0, "eingebettete signature wurde akzeptiert");
  assert.ok(fs.existsSync(verified), "controlled native verification was not reached before manifest-policy rejection");
  assert.match(`${rejected.stdout}${rejected.stderr}`, /Signiertes Manifest wird nicht verändert/);
  assert.equal(fs.readFileSync(one, "utf8"), xml, "signiertes Manifest wurde verändert");
  assert.equal(fs.readFileSync(two, "utf8"), xml, "signiertes Manifest wurde verändert");

  const auditor = path.join(root, "build", "AuditUpdateManifest.ps1");
  const auditCommand = `& '${quote(auditor)}' -Manifest @('${quote(one)}','${quote(two)}') -Report '${quote(report)}'`;
  const audited = spawnSync(pwsh, ["-NoProfile", "-Command", auditCommand], { encoding: "utf8" });
  assertSpawned(audited, "Manifest audit policy");
  assert.notEqual(audited.status, 0, `${audited.stderr || audited.stdout}`);
  const result = JSON.parse(fs.readFileSync(report, "utf8"));
  assert.ok(result.every(entry => entry.windowsReleaseStatus === "UNVEROEFFENTLICHT" && entry.embeddedSignature));
  console.log("Manifest-Signatur- und Veröffentlichungs-Policy bestanden.");
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
