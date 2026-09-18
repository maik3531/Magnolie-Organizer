#!/usr/bin/env node
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { spawnSync } = require("node:child_process");
const root = path.resolve(__dirname, "..");
const read = p => fs.readFileSync(path.join(root, p), "utf8");
const fail = message => { throw new Error(`Release-Audit: ${message}`); };
const handbook = [process.env.MAGNOLIE_HANDBUCH_WEB,
  path.resolve(root, "..", "magnolie-handbuch", "web"),
  path.join(root, "shared", "magnolie-handbuch", "web")]
  .filter(Boolean).find((candidate) => fs.existsSync(path.join(candidate, "inhalt.js")) &&
    fs.existsSync(path.join(candidate, "i18n", "de.js")));
if (!handbook) fail("Gemeinsame Handbuchquelle fehlt");
function checkPowerShell(file) {
  const text = read(file);
  const pairs = { ")": "(", "]": "[", "}": "{" };
  const stack = [];
  let quote = "", escaped = false, comment = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (comment) { if (c === "\n") comment = false; continue; }
    if (quote) {
      if (quote === '"' && c === "`" && !escaped) { escaped = true; continue; }
      if (c === quote && !escaped) quote = "";
      escaped = false;
      continue;
    }
    if (c === "#") { comment = true; continue; }
    if (c === '"' || c === "'") { quote = c; continue; }
    if ("([{ ".includes(c) && c !== " ") stack.push(c);
    if (pairs[c] && stack.pop() !== pairs[c]) fail(`${file} hat unausgeglichene Klammern`);
  }
  if (quote || stack.length) fail(`${file} hat unausgeglichene Zeichenketten oder Klammern`);
}
for (const file of ["build/Build.ps1", "build/BuildSource.ps1", "build/Release.Common.ps1", "build/UpdateManifest.ps1", "vm/StartTest.ps1", "vm/TestInstallerUpdate.ps1"]) checkPowerShell(file);
const version = /<Version>([^<]+)<\/Version>/.exec(read("Directory.Build.props"))?.[1];
if (!/^\d+\.\d+\.\d+$/.test(version || "")) fail("kanonische Version fehlt");
if (process.argv[2] !== version || process.argv[3] !== `Magnolie-Organizer-Windows-${version}-Setup-x64.exe`) fail("Release-Tests erhielten nicht die kanonischen Namen");
if (/<(?:Version|AssemblyVersion|FileVersion)>/.test(read("MagnolieOrganizer.Windows.csproj"))) fail("csproj dupliziert Version");
if (!read("app.manifest").includes(`assemblyIdentity version="${version}.0"`)) fail("Manifestversion weicht ab");
const nsi = read("installer/MagnolieOrganizer.nsi");
for (const token of ['!define ROOT "${__FILEDIR__}/.."', "PRODUCT_MARKER_ID", "INSTALLER_FILENAME", 'OutFile "${OUTPUT_FILE}"', "/x \"handbuch\"", 'File /r /x "*.pdb" /x "handbuch" "${PUBLISH_DIR}/*.*"', 'File /r "${PUBLISH_DIR}/handbuch/*.*"']) if (!nsi.includes(token)) fail(`NSIS-Invariante fehlt: ${token}`);
if (nsi.includes('!define PRODUCT_VERSION "')) fail("NSIS enthält feste Produktversion");
if (/^\s*!cd\b/m.test(nsi)) fail("NSIS darf nicht vom Aufrufverzeichnis abhängen");
for (const sourcePath of nsi.matchAll(/^(?:Icon|UninstallIcon|!define MUI_(?:ICON|UNICON|WELCOMEFINISHPAGE_BITMAP|UNWELCOMEFINISHPAGE_BITMAP|HEADERIMAGE_BITMAP|HEADERIMAGE_UNBITMAP))\s+"([^"]+)"/gm)) {
  if (!sourcePath[1].startsWith("${ROOT}/")) fail(`NSIS-Repositorypfad ist nicht an ROOT gebunden: ${sourcePath[1]}`);
}
for (const sourcePath of nsi.matchAll(/^\s*File\s+[^\r\n]*"(\$\{PUBLISH_DIR\}[^"]*)"/gm)) {
  if (sourcePath[1].includes("\\")) fail(`NSIS-Publishpfad verwendet einen plattformabhängigen Trenner: ${sourcePath[1]}`);
}

const bundledMakensis = "/tmp/opencode/nsis-root/usr/bin/makensis";
const bundledNsisDir = "/tmp/opencode/nsis-root/usr/share/nsis";
if (fs.existsSync(bundledMakensis)) {
  const auditBase = os.tmpdir();
  fs.mkdirSync(auditBase, { recursive: true });
  const fixture = fs.mkdtempSync(path.join(auditBase, "magnolie-nsis-audit-"));
  try {
    fs.mkdirSync(path.join(fixture, "installer"), { recursive: true });
    fs.mkdirSync(path.join(fixture, "app"), { recursive: true });
    fs.mkdirSync(path.join(fixture, "Ausgabe", "handbuch"), { recursive: true });
    fs.copyFileSync(path.join(root, "installer", "MagnolieOrganizer.nsi"), path.join(fixture, "installer", "MagnolieOrganizer.nsi"));
    fs.copyFileSync(path.join(root, "installer", "welcome.bmp"), path.join(fixture, "installer", "welcome.bmp"));
    fs.copyFileSync(path.join(root, "installer", "header.bmp"), path.join(fixture, "installer", "header.bmp"));
    fs.copyFileSync(path.join(root, "app", "magnolie-organizer.ico"), path.join(fixture, "app", "magnolie-organizer.ico"));
    fs.writeFileSync(path.join(fixture, "Ausgabe", "Magnolie Organizer.exe"), "NSIS release-audit fixture\n");
    fs.writeFileSync(path.join(fixture, "Ausgabe", "WINDOWS-RUNTIME-UNVERIFIED.txt"), "windowsRuntimeVerified=false\nwindowsVmValidationRequired=true\nartifactTrust=UNSIGNED\n");
    fs.writeFileSync(path.join(fixture, "Ausgabe", "handbuch", "index.html"), "<!doctype html><title>fixture</title>\n");
    const manifests = path.join(fixture, "manifests");
    const manifestResult = spawnSync(process.execPath, [path.join(root, "installer", "GenerateInstallManifests.js"), path.join(fixture, "Ausgabe"), manifests], { encoding: "utf8" });
    if (manifestResult.status !== 0) fail(`Installer-Manifest-Fixture fehlgeschlagen: ${manifestResult.stderr || manifestResult.stdout}`);
    const coreManifest = fs.readFileSync(path.join(manifests, "core.manifest")).subarray(2).toString("utf16le");
    if (!coreManifest.includes("WINDOWS-RUNTIME-UNVERIFIED.txt")) fail("Cross-Laufzeitmarker fehlt im Installer-Manifest-Fixture");
    const fixtureInstallerName = `Magnolie-Organizer-Windows-${version}-Setup-x64.exe`;
    const output = path.join(fixture, fixtureInstallerName);
    const syntax = spawnSync(bundledMakensis, [
      "-V2",
      `-DPRODUCT_VERSION=${version}`,
       `-DPUBLISH_DIR=${path.join(fixture, "Ausgabe")}`,
       `-DCORE_MANIFEST=${path.join(manifests, "core.manifest")}`,
       `-DHANDBOOK_MANIFEST=${path.join(manifests, "handbook.manifest")}`,
      `-DOUTPUT_FILE=${output}`,
      `-DINSTALLER_FILENAME=${fixtureInstallerName}`,
      path.join(fixture, "installer", "MagnolieOrganizer.nsi")
    ], { encoding: "utf8", env: { ...process.env, NSISDIR: bundledNsisDir }, cwd: auditBase });
    if (syntax.status !== 0 || !fs.existsSync(output)) fail(`echter NSIS-Fixture-Bau fehlgeschlagen: ${syntax.stderr || syntax.stdout}`);
    const installerAudit = path.join(root, "installer", "AuditInstaller.js");
    const buildRecord = path.join(fixture, `${fixtureInstallerName}.build.json`);
    const recordResult = spawnSync(process.execPath, [path.join(root, "installer", "CreateInstallerBuildRecord.js"), output, buildRecord, fixtureInstallerName], { encoding: "utf8" });
    if (recordResult.status !== 0) fail(`Installer-Buildrecord konnte nicht erzeugt werden: ${recordResult.stderr || recordResult.stdout}`);
    const audited = spawnSync(process.execPath, [installerAudit, output, path.join(fixture, "Ausgabe"), fixtureInstallerName, buildRecord], { encoding: "utf8" });
    if (audited.status !== 0) fail(`echter Installer wurde nicht vollständig geprüft: ${audited.stderr || audited.stdout}`);
    const original = fs.readFileSync(output);
    const pe = original.readUInt32LE(0x3c);
    const sectionCount = original.readUInt16LE(pe + 6);
    const sectionTable = pe + 24 + original.readUInt16LE(pe + 20);
    const firstSection = original.readUInt32LE(sectionTable + 20) + Math.min(8, original.readUInt32LE(sectionTable + 16) - 1);
    let overlay = 0;
    for (let index = 0; index < sectionCount; index++) {
      const section = sectionTable + index * 40;
      overlay = Math.max(overlay, original.readUInt32LE(section + 20) + original.readUInt32LE(section + 16));
    }
    const payload = overlay + Math.floor((original.length - overlay) / 2);
    for (const [label, offset] of [["DOS/PE-Stub", 0x50], ["PE-Section", firstSection], ["NSIS-Payload", payload]]) {
      if (offset < 0 || offset >= original.length) fail(`${label}-Testoffset liegt außerhalb des Fixtures`);
      const corrupted = path.join(fixture, `${label.replace(/\W/g, "-")}-${fixtureInstallerName}`);
      const changed = Buffer.from(original); changed[offset] ^= 0x01; fs.writeFileSync(corrupted, changed);
      const corruptAudit = spawnSync(process.execPath, [installerAudit, corrupted, path.join(fixture, "Ausgabe"), fixtureInstallerName, buildRecord], { encoding: "utf8" });
      if (corruptAudit.status === 0) fail(`Bitflip in ${label} wurde akzeptiert`);
    }
    const malformed = path.join(fixture, `malformed-${fixtureInstallerName}`);
    const malformedImage = Buffer.from(original);
    malformedImage.writeUInt32LE(malformedImage.length - 1, sectionTable + 20);
    fs.writeFileSync(malformed, malformedImage);
    const malformedRecord = `${malformed}.build.json`;
    const malformedRecordResult = spawnSync(process.execPath, [path.join(root, "installer", "CreateInstallerBuildRecord.js"), malformed, malformedRecord, fixtureInstallerName], { encoding: "utf8" });
    if (malformedRecordResult.status !== 0) fail("Record für PE-Negativfixture konnte nicht erzeugt werden");
    const malformedAudit = spawnSync(process.execPath, [installerAudit, malformed, path.join(fixture, "Ausgabe"), fixtureInstallerName, malformedRecord], { encoding: "utf8" });
    if (malformedAudit.status === 0) fail("PE-Section außerhalb der Dateigrenze wurde trotz passendem Hash akzeptiert");
  } finally {
    fs.rmSync(fixture, { recursive: true, force: true });
  }
}
const source = read("build/BuildSource.ps1");
if (source.includes('".png"')) fail("Quellbau schließt PNG aus");
for (const file of ["app/magnolie-organizer.ico", "app/web/kaffee-qr.mga", "app/symbole/48x48/magnolie-organizer.png", "app/symbole/64x64/magnolie-organizer.png", "app/symbole/128x128/magnolie-organizer.png", "app/symbole/256x256/magnolie-organizer.png", "shared/magnolie-handbuch/web/kaffee-qr.mga", "shared/magnolie-handbuch/web/maik-walter.mga", "tests/resources/personal-sync-contract.json", "tests/resources/telefon-control-contract.json", "tests/resources/linux-parity-contract.json", "tests/linux-parity-fixture.js", "tests/generate-linux-parity-fixture.js", "LICENSE"]) if (!fs.existsSync(path.join(root, file))) fail(`Pflichtdatei fehlt: ${file}`);
for (const file of ["app/web/kaffee-qr.png", "shared/magnolie-handbuch/web/kaffee-qr.png", "shared/magnolie-handbuch/web/maik-walter.jpg"]) if (fs.existsSync(path.join(root, file))) fail(`Klartext-Personenasset vorhanden: ${file}`);
for (const file of ["tests/PersonalSyncTests.cs", "tests/TelefonProtocolTests.cs"]) if (/magnolie-organizer-1\.31\.7|\.\.\\.*pruefungen/.test(read(file))) fail(`${file} benötigt Geschwisterquelle`);
const vmResultTest = read("vm/TestInstallerUpdate.ps1");
for (const token of ["$transcriptStarted", "$resultWritten", "$resultPersisted", "$logPersisted", "Remove-Item -LiteralPath $path -Force", "if (-not $results)", "VM bleibt zur Diagnose aktiv", "function Sync-ResultFile", "foreach ($attempt in 1..10)", "FileShare]::ReadWrite", "FileShare]::Delete", "function Write-InfrastructureFailure", "INFRASTRUCTURE FAILURE", "Ergebnisdateien konnten nicht dauerhaft geschrieben werden", "$stream.Flush($true)", "$mountExitCode", "$shutdownExitCode", "mountvol.exe", "shutdown.exe", "if (-not $report.Passed) { exit 1 }", "exit 0"]) if (!vmResultTest.includes(token)) fail(`VM-Ergebniskanal fehlt: ${token}`);
const flush = vmResultTest.indexOf("$stream.Flush($true)");
const persistenceCheck = vmResultTest.indexOf("if (-not $resultWritten)");
const dismount = vmResultTest.indexOf("$mountOutput = @(&");
const dismountCheck = vmResultTest.indexOf("if ($mountExitCode -ne 0)", dismount);
const shutdown = vmResultTest.indexOf("$shutdownOutput = @(&");
const shutdownCheck = vmResultTest.indexOf("if ($shutdownExitCode -ne 0)", shutdown);
if (flush < 0 || persistenceCheck < flush || dismount < persistenceCheck || dismountCheck < dismount || shutdown < dismountCheck || shutdownCheck < shutdown) fail("VM prüft Flush, Persistenz, Aushängen und Herunterfahren nicht in dieser Reihenfolge");
const build = read("build/Build.ps1");
for (const token of [".release-staging-", "New-DeterministicZip", "Enter-ReleaseLock", "Sign-Official", "MAGNOLIE_SIGNTOOL", "--packaging-self-test", "Write-ReleaseChecksums", "Assert-SourceArchive", "Assert-BinaryArchiveBuildConfig", "AuditWebPayload.js", '"--publish", $buildRoot, $publish', '"--artifact", $publish, $zipAudit', "BuildSource.ps1", "sourceForRelease", "installerName", "TimeStamperCertificate", 'Move-Item -LiteralPath $unsignedSetupStage', "CreateInstallerBuildRecord.js", "installerRecordName", "CrossCompile", "WINDOWS-RUNTIME-UNVERIFIED.txt", "windowsRuntimeVerified=false", "windowsVmValidationRequired=true", "artifactTrust=UNSIGNED", "AuditInstaller.js", "NSISDIR", "/tmp/opencode/nsis-root/usr/bin/makensis", "Binärausgabe benötigt MAGNOLIE_CONTRIBUTOR_HASH"]) if (!build.includes(token)) fail(`Build-Invariante fehlt: ${token}`);
for (const token of ['ExtractToDirectory($sourceForRelease, $sourceProjection)', 'Push-Location $buildRoot', 'MAGNOLIE_LINUX_SOURCE']) if (!build.includes(token)) fail(`Verified source projection missing: ${token}`);
if (build.includes(".SignerCertificate.Subject.Contains(")) fail("Build akzeptiert Herausgeber-Teiltreffer");
if (!/if \(\$CrossCompile\)[\s\S]*?else \{[\s\S]*?--packaging-self-test[\s\S]*?--self-test[\s\S]*?--ui-self-test[\s\S]*?\}/.test(build)) fail("Cross-Bau grenzt Windows-Laufzeittests nicht eindeutig ab");
if (!/\$installerName = \$canonicalInstallerName/.test(build)) fail("Der Bau verwendet nicht durchgehend den normalen Installernamen");
if (!/\$setupStage = Join-Path \$publicationStage \$canonicalInstallerName/.test(build) ||
    !build.includes('"-DINSTALLER_FILENAME=$canonicalInstallerName"')) fail("Offizieller und Cross-Bau verwenden nicht denselben kanonischen Installernamen");
if (/canonicalInstallerName\.Replace\([^\r\n]*UNSIGNED/.test(build)) fail("PowerShell-Bau erzeugt weiterhin einen -UNSIGNED-Ausgabenamen");
if (!/\$unsignedSetupStage = if \(\$official\)[^\r\n]*\.unsigned-[^\r\n]*else \{ \$setupStage \}/.test(build)) fail("Offizielles unsigniertes Staging ist nicht vom kanonischen Ausgabenamen getrennt");
const runtimeCrossBranch = build.indexOf("if ($CrossCompile) {", build.indexOf("$app ="));
const runtimeNormalBranch = build.indexOf("    } else {", runtimeCrossBranch);
const markerWrite = build.indexOf("WINDOWS-RUNTIME-UNVERIFIED.txt");
if (runtimeCrossBranch < 0 || markerWrite < runtimeCrossBranch || markerWrite > runtimeNormalBranch) fail("Laufzeitmarker ist nicht ausschließlich auf den Cross-Bau begrenzt");
const common = read("build/Release.Common.ps1");
for (const token of ["Sort-Object", "LastWriteTime", "ExternalAttributes", ".rollback", "Invoke-NativeCommand", '$LASTEXITCODE', '$backedUp', '$installed', "Assert-SourceArchive", "Remove-StaleUnsignedInstallers", "Setup-x64-UNSIGNED"] ) if (!common.includes(token)) fail(`Archiv/Ersetzungs-Invariante fehlt: ${token}`);
for (const token of ["Get-ReleaseSourceFiles", "-Force", "excludedDirectories", ".release-staging-*", "Compare-Object", "SHA256"] ) if (!common.includes(token)) fail(`Quellenenumerations-/Hash-Invariante fehlt: ${token}`);
for (const token of ["Assert-BinaryArchiveBuildConfig", 'GetFileName($_) -ceq "build-config.json"', "Quellarchiv enthält den Contributor-Hash"]) if (!common.includes(token)) fail(`Branding-Archiv-Invariante fehlt: ${token}`);
const webAudit = read("build/AuditWebPayload.js");
for (const token of ["app", "web", "anwendung.js", "oeffneSuche", "nextcloud", "LINGUAS", "native-i18n.json", "handbuch", "artifactPayload"]) if (!webAudit.includes(token)) fail(`Web-Publish-Invariante fehlt: ${token}`);
const publishCall = build.indexOf('"--publish", $buildRoot, $publish');
const dotnetPublish = build.indexOf('"dotnet" @("publish"');
const handbookPort = build.indexOf("build/PortHandbook.js");
const zipBuild = build.indexOf("New-DeterministicZip $publish");
if (dotnetPublish < 0 || handbookPort < dotnetPublish || publishCall < handbookPort || zipBuild < publishCall)
  fail("Post-Publish-Webaudit läuft nicht nach Publish und Handbuchportierung sowie vor dem ZIP");
const parityTest = read("tests/full-parity-contract.js");
if (!parityTest.includes("linux-parity-contract.json") || /magnolie-organizer-1\.31\.7|path\.resolve\(root, "\.\."/.test(parityTest))
  fail("Vollparitätstest ist nicht vom Linux-Geschwisterbaum entkoppelt");

const webAuditTemp = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-web-audit-"));
try {
  const publishFixture = path.join(webAuditTemp, "publish");
  fs.mkdirSync(publishFixture);
  fs.cpSync(path.join(root, "app", "web"), path.join(publishFixture, "web"), { recursive: true });
  fs.copyFileSync(path.join(root, "app", "native-i18n.json"), path.join(publishFixture, "native-i18n.json"));
  const handbookPortResult = spawnSync(process.execPath,
    [path.join(root, "build", "PortHandbook.js"), handbook, version,
      `Magnolie-Organizer-Windows-${version}-Setup-x64.exe`, path.join(publishFixture, "handbuch")],
    { encoding: "utf8" });
  if (handbookPortResult.status !== 0) fail(`Gemeinsames Handbuch konnte nicht portiert werden: ${handbookPortResult.stderr || handbookPortResult.stdout}`);
  const auditScript = path.join(root, "build", "AuditWebPayload.js");
  const runAudit = () => spawnSync(process.execPath, [auditScript, "--publish", root, publishFixture], { encoding: "utf8" });
  const currentAudit = runAudit();
  if (currentAudit.status !== 0) fail(`Post-Publish-Fixture wurde abgelehnt: ${currentAudit.stderr || currentAudit.stdout}`);
  const publishedApplication = path.join(publishFixture, "web", "anwendung.js");
  fs.rmSync(publishedApplication);
  const missingAudit = runAudit();
  if (missingAudit.status === 0 || !`${missingAudit.stderr}${missingAudit.stdout}`.includes("anwendung.js"))
    fail("Post-Publish-Audit akzeptierte fehlende Webdatei");
  fs.copyFileSync(path.join(root, "app", "web", "anwendung.js"), publishedApplication);
  fs.appendFileSync(publishedApplication, "\n// stale publish fixture\n");
  const staleAudit = runAudit();
  if (staleAudit.status === 0 || !`${staleAudit.stderr}${staleAudit.stdout}`.includes("nicht bytegleich"))
    fail("Post-Publish-Audit akzeptierte veraltete Webdatei");
} finally {
  fs.rmSync(webAuditTemp, { recursive: true, force: true });
}
for (const token of ["DisplayPath", "IsPathRooted", "GetFullPath((Join-Path (Split-Path -Parent $Destination) $name))", "Prüfsummenpfad zeigt nicht auf das Quellartefakt"]) if (!common.includes(token)) fail(`Prüfsummenpfad-Invariante fehlt: ${token}`);
if (!build.includes('DisplayPath = $sourceName') || !build.includes('$sourceStage = Join-Path $publicationStage $sourceName')) fail("Source ZIP and checksums must share the final flat layout");
const vmMedia = read("vm/Create-TestMedia.sh");
const vmTest = read("vm/StartTest.ps1");
const vmCreate = read("vm/Create-VM.sh");
const vmInstallerTest = read("vm/TestInstallerUpdate.ps1");
if (!vmMedia.includes('printf \'%s\\n\' "$MAGNOLIE_VM_BRANDING" > "$staging/Magnolie.Branding"')) fail("VM-Medium schreibt Magnolie.Branding nicht explizit");
for (const token of ["Magnolie.Branding", 'cnotin @(\"official\", \"unbranded\")', '$branding -ceq "official"', '"NotRun"', "PackagingSelfTestPassed", "CrossCompileRuntimeMarkerPresent", "WINDOWS-RUNTIME-UNVERIFIED.txt", "Offizieller Packaging-Selbsttest fehlgeschlagen"]) if (!vmTest.includes(token)) fail(`VM-Branding-/Laufzeittest-Invariante fehlt: ${token}`);
for (const token of ["Magnolie-Windows-Results.img", "MAGNOLIE_RESULTS", "MAGNOLIE_VM_DISK", "MAGNOLIE_VM_RESULTS_IMAGE", '[[ "$disk" != "$results" ]]', '[[ "$path" != *,* ]]', "parted --script", "mklabel msdos", "mkpart primary fat32 1MiB 100%", "mkfs.vfat -F 32 -h", "--offset=", "@@$results_partition_offset", "format=raw,bus=sata"]) if (!vmCreate.includes(token)) fail(`VM-Ergebnisdatenträger-Invariante fehlt: ${token}`);
if (!read("vm/Autounattend.xml").includes("<PreventDeviceEncryption>true</PreventDeviceEncryption>")) fail("Windows-VM verhindert automatische Verschlüsselung des Ergebniskanals nicht");
for (const token of ["MAGNOLIE_RESULTS", "RESULT.txt", "windows-vm-test.log", "Start-Transcript", '"SUCCESS"', '"FAIL"']) if (!vmInstallerTest.includes(token)) fail(`VM-Installer-Ergebnis-Invariante fehlt: ${token}`);
if (!/if \(\$branding -ceq "official"\) \{[\s\S]*?--packaging-self-test[\s\S]*?\}/.test(vmTest)) fail("Packaging-Selbsttest ist nicht ausschließlich an offizielles Branding gebunden");
if (/Start-Process[^\r\n]*--packaging-self-test/.test(vmTest.replace(/if \(\$branding -ceq "official"\) \{[\s\S]*?\n\}/, ""))) fail("Packaging-Selbsttest kann außerhalb des offiziellen Zweigs starten");
if (!common.includes("$backedUp.Count - 1") || !common.includes("$installed.Count - 1")) fail("Statischer Rückwärts-Rollbacknachweis fehlt");
for (const script of [build, source]) {
  if (/^\s*(?:dotnet|bun)\s/m.test(script) || /&\s+\$makensis/.test(script)) fail("Nativer Buildbefehl umgeht Invoke-NativeCommand");
}
const workflow = read(".github/workflows/windows.yml");
if (/latest|8\.0\.x/.test(workflow)) fail("CI verwendet unverankerte Werkzeugversion");
for (const line of workflow.split("\n").filter(line => line.includes("uses:"))) {
  if (!/@[0-9a-f]{40}\s+#\s+v\d/.test(line)) fail(`CI-Action ist nicht mit SHA und Versionskommentar verankert: ${line.trim()}`);
}
for (const token of ["BuildSource.ps1", "Build.ps1", "BuildInstaller", "MAGNOLIE_CONTRIBUTOR_HASH"]) if (!workflow.includes(token)) fail(`CI-Invariante fehlt: ${token}`);
const nsisStep = workflow.indexOf("- name: NSIS einrichten");
const certificateStep = workflow.indexOf("- name: Signierzertifikat einrichten");
if (nsisStep < 0 || certificateStep < 0 || nsisStep > certificateStep ||
    workflow.slice(nsisStep, certificateStep).includes("SIGNING_PFX_BASE64"))
  fail("CI trennt NSIS-Abhängigkeit nicht vom Signierzertifikat");
for (const token of ['$projectArtifacts = $env:ARTIFACT_DIR',
  "Copy-Item -LiteralPath $source -Destination $env:ARTIFACT_DIR",
  "Copy-Item -LiteralPath $file -Destination $projectArtifacts"])
  if (!workflow.includes(token)) fail(`CI bewahrt das Prüfsummenlayout nicht: ${token}`);
const updater = read("build/UpdateManifest.ps1");
for (const token of ["translate(local-name(), 'SIGNATURE', 'signature')='signature'", "RootManifest", "LinuxSourceManifest", "UpdateManualWindows", ".staging-", ".Count -ne 1", "GetFullPath", "ExpectedPublisher", "Get-AuthenticodeSignature", "TimeStamperCertificate", '"verify", "/pa", "/all", "/tw"', "Invoke-NativeCommand"]) if (!updater.includes(token)) fail(`Manifest-Invariante fehlt: ${token}`);
if (updater.includes(".SignerCertificate.Subject.Contains(")) fail("Manifesthelfer akzeptiert Herausgeber-Teiltreffer");
const port = read("build/PortHandbook.js");
for (const token of ["process.argv[3]", "process.argv[4]", "installerName",
  "JSON.stringify({ version })", "inhalt.js", "sourceWeb === output"]) {
  if (!port.includes(token)) fail(`Handbuch-Metadaten-Invariante fehlt: ${token}`);
}
const canonicalInstaller = `Magnolie-Organizer-Windows-${version}-Setup-x64.exe`;
const portScript = path.join(root, "build", "PortHandbook.js");
for (const installerName of [canonicalInstaller]) {
  const handbookTempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-handbook-audit-"));
  const handbookTemp = path.join(handbookTempRoot, "handbuch");
  const portResult = spawnSync(process.execPath, [portScript, handbook, version, installerName, handbookTemp], { encoding: "utf8" });
  if (portResult.status !== 0) fail(`Handbuch-Port mit erlaubtem Installernamen fehlgeschlagen: ${portResult.stderr || portResult.stdout}`);
  const portedContent = fs.readFileSync(path.join(handbookTemp, "inhalt.js"), "utf8");
  if (JSON.parse(fs.readFileSync(path.join(handbookTemp, "version.json"), "utf8")).version !== version ||
      !portedContent.includes(installerName)) fail(`Handbuch-Port bewahrte Installernamen nicht exakt: ${installerName}`);
  fs.rmSync(handbookTempRoot, { recursive: true, force: true });
}
for (const installerName of [
  `${canonicalInstaller}.bak`,
  `Magnolie-Organizer-Windows-${version}-Setup-x64-UNSIGNED.exe`,
  `Magnolie-Organizer-Windows-${version}-Setup-x64-DEBUG.exe`,
  `../${canonicalInstaller}`,
  `subdir/${canonicalInstaller}`,
  `subdir\\${canonicalInstaller}`
]) {
  const rejected = spawnSync(process.execPath, [portScript, handbook, version, installerName,
    path.join(os.tmpdir(), `magnolie-rejected-${process.pid}`)], { encoding: "utf8" });
  if (rejected.status === 0) fail(`Handbuch-Port akzeptierte Suffix oder Pfadinjektion: ${installerName}`);
}
const linuxInstaller = read("installer/BuildInstaller.sh");
const buildScriptText = read("build/Build.ps1");
const nsisInstaller = read("installer/MagnolieOrganizer.nsi");
for (const token of ["MAGNOLIE_CONTRIBUTOR_HASH", "VerifyBuildConfig.js", "command -v makensis", "-DPRODUCT_VERSION", ".staging-", 'installer_name="Magnolie-Organizer-Windows-$version-Setup-x64.exe"', "CreateInstallerBuildRecord.js", "PublishInstaller.sh", ".build.json", "sha256sum", "MAGNOLIE_OFFICIAL_RELEASE", "AuditInstaller.js", "windowsRuntimeVerified=false", "artifactTrust=UNSIGNED"]) if (!linuxInstaller.includes(token)) fail(`Linux-NSIS-Invariante fehlt: ${token}`);
if (/installer_name=.*Setup-x64-UNSIGNED\.exe/.test(linuxInstaller)) fail("Linux-NSIS erzeugt weiterhin einen -UNSIGNED-Ausgabenamen");
if (!buildScriptText.includes('$setupStage = Join-Path $publicationStage $canonicalInstallerName') ||
    buildScriptText.includes('$releaseInstallerName')) fail("PowerShell-Bau verwendet nicht in beiden Modi den kanonischen Installernamen");
for (const token of ["Function CleanManagedInstall", "Function PrepareManagedUpgrade", "Function RollbackManagedUpgrade",
  "Function BackupManagedManifest", "Function DeleteManagedManifest", "Function RestoreManagedManifest",
  "InitPluginsDir",
  'File /oname=magnolie-core.manifest "${CORE_MANIFEST}"', 'File /oname=magnolie-handbook.manifest "${HANDBOOK_MANIFEST}"',
  'Delete "$INSTDIR\\.magnolie-installer"', 'Delete "$INSTDIR\\Magnolie Organizer deinstallieren.exe"',
  "Call PrepareManagedUpgrade", "Call RollbackManagedUpgrade", "Section -Commit"])
  if (!nsisInstaller.includes(token)) fail(`NSIS bereinigt Upgrades nicht sicher: ${token}`);
const managedCleanup = /Function CleanManagedInstall([\s\S]*?)FunctionEnd/.exec(nsisInstaller)?.[1] || "";
if (!managedCleanup.includes('IfFileExists "$INSTDIR\\.magnolie-core.manifest" 0 fresh'))
  fail("NSIS behandelt einen Marker nach vollständiger Deinstallation weiterhin als installierte Altversion");
const upgradePreparation = /Function PrepareManagedUpgrade([\s\S]*?)FunctionEnd/.exec(nsisInstaller)?.[1] || "";
const transactionStart = upgradePreparation.indexOf("StrCpy $TransactionActive 1");
const firstManagedDelete = upgradePreparation.indexOf("Call DeleteManagedManifest");
if (transactionStart < 0 || firstManagedDelete < 0 || transactionStart > firstManagedDelete)
  fail("NSIS aktiviert den Rollback nicht vor der ersten verwalteten Dateilöschung");
if (!upgradePreparation.includes("IfErrors cleanup_failed") ||
    !upgradePreparation.includes("Call RollbackManagedUpgrade"))
  fail("NSIS ignoriert gesperrte Dateien während eines Upgrades");
if (!upgradePreparation.includes('CopyFiles /SILENT "$INSTDIR\\.magnolie-installer" "$BackupDir"'))
  fail("NSIS sichert den Marker eines deinstallierten Restordners nicht für einen Rollback");
const backupManifest = /Function BackupManagedManifest([\s\S]*?)FunctionEnd/.exec(nsisInstaller)?.[1] || "";
const deleteManifest = /Function DeleteManagedManifest([\s\S]*?)FunctionEnd/.exec(nsisInstaller)?.[1] || "";
const restoreManifest = /Function RestoreManagedManifest([\s\S]*?)FunctionEnd/.exec(nsisInstaller)?.[1] || "";
const uninstallDeleteManifest = /Function un\.DeleteManagedManifest([\s\S]*?)FunctionEnd/.exec(nsisInstaller)?.[1] || "";
for (const [name, source] of [["Backup", backupManifest], ["Löschen", deleteManifest],
  ["Wiederherstellen", restoreManifest], ["Deinstallation", uninstallDeleteManifest]])
  if (!source.includes("FileReadUTF16LE") || /\bFileRead\s+\$0\s+\$2/.test(source))
    fail(`NSIS liest die UTF-16LE-Besitzliste beim ${name} nicht als UTF-16LE`);
for (const separatelyBackedUp of [".magnolie-core.manifest", ".magnolie-handbook.manifest",
  ".magnolie-installer", "Magnolie Organizer deinstallieren.exe"])
  if (!backupManifest.includes(`StrCmp $3 "${separatelyBackedUp}" loop`))
    fail(`NSIS sichert Metadatei doppelt und kann dadurch ein normales Upgrade abbrechen: ${separatelyBackedUp}`);
if (nsisInstaller.includes('RMDir /r "$INSTDIR"')) fail("NSIS löscht unbekannte Benutzerdateien im Programmordner rekursiv");
if (!nsisInstaller.includes('Call un.DeleteManagedManifest')) fail("Uninstaller verwendet die Besitzliste nicht");
const uninstallSection = /Section "Uninstall"([\s\S]*?)SectionEnd/.exec(nsisInstaller)?.[1] || "";
if (!/ExecWait\s+'"\$INSTDIR\\\$\{PRODUCT_EXE\}" --unregister-call-notifications'\s+\$0/.test(uninstallSection))
  fail("Uninstaller quotes the notification-cleanup executable incorrectly");
if (!/Invoke-NativeCommand \$makensis @\("-WX"/.test(buildScriptText))
  fail("NSIS warnings must fail the installer build");
if (!uninstallSection.includes('${LEGACY_PRODUCT_MARKER}')) fail("Uninstaller erkennt den alten 2.0.0-Produktmarker nicht");
if (!uninstallSection.includes("$UninstallCleanupFailed == 1")) fail("Uninstaller ignoriert fehlgeschlagene Dateilöschungen");
const uninstallManifestCleanup = /Function un\.DeleteManagedManifest([\s\S]*?)FunctionEnd/.exec(nsisInstaller)?.[1] || "";
for (const protectedFile of [".magnolie-core.manifest", ".magnolie-handbook.manifest",
  ".magnolie-installer", "Magnolie Organizer deinstallieren.exe"])
  if (!uninstallManifestCleanup.includes(`StrCmp $4 "${protectedFile}" loop`))
    fail(`Uninstaller löscht Besitznachweis vor erfolgreicher Bereinigung: ${protectedFile}`);
const manifestGenerator = read("installer/GenerateInstallManifests.js");
for (const token of ["core.manifest", "handbook.manifest", ".magnolie-core.manifest", ".magnolie-handbook.manifest", "utf16le", "isSymbolicLink"])
  if (!manifestGenerator.includes(token)) fail(`Installer-Manifest-Invariante fehlt: ${token}`);
const clearSigningEnvironment = buildScriptText.indexOf("[Environment]::SetEnvironmentVariable($name, $null");
const firstDependencyProcess = buildScriptText.indexOf('Invoke-NativeCommand "dotnet"');
if (clearSigningEnvironment < 0 || firstDependencyProcess < 0 || clearSigningEnvironment > firstDependencyProcess)
  fail("PowerShell-Bau entfernt Signiergeheimnisse nicht vor Abhängigkeitsprozessen aus der Umgebung");
const configFixture = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-config-audit-"));
  try {
  const configPath = path.join(configFixture, "build-config.json");
  const upperHash = "AB".repeat(32);
  fs.writeFileSync(configPath, JSON.stringify({ contributorHash: upperHash }));
  const upperConfig = spawnSync(process.execPath, [path.join(root, "installer", "VerifyBuildConfig.js"), configPath], { encoding: "utf8", env: { ...process.env, MAGNOLIE_CONTRIBUTOR_HASH: upperHash } });
  if (upperConfig.status === 0) fail("build-config.json akzeptierte nicht normalisierten Hash");
  fs.writeFileSync(configPath, JSON.stringify({ contributorHash: upperHash.toLowerCase() }));
  const lowerConfig = spawnSync(process.execPath, [path.join(root, "installer", "VerifyBuildConfig.js"), configPath], { encoding: "utf8", env: { ...process.env, MAGNOLIE_CONTRIBUTOR_HASH: upperHash } });
  if (lowerConfig.status !== 0) fail(`normalisierte build-config.json wurde abgelehnt: ${lowerConfig.stderr || lowerConfig.stdout}`);
} finally { fs.rmSync(configFixture, { recursive: true, force: true }); }

const pwshCandidates = [process.env.MAGNOLIE_TEST_PWSH,
  process.env.ProgramFiles && path.join(process.env.ProgramFiles, "PowerShell", "7", "pwsh.exe"),
  process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "Microsoft", "WindowsApps", "pwsh.exe"),
  "/tmp/opencode/powershell-7.4.13/pwsh", "pwsh"].filter(Boolean);
let pwshCommand = pwshCandidates.find(command => {
  const probe = spawnSync(command, ["-NoProfile", "-Command", "$PSVersionTable.PSVersion.Major"], { encoding: "utf8" });
  return probe.status === 0 && Number.parseInt(probe.stdout, 10) >= 7;
});
let pwshPrefix = [];
if (!pwshCommand && process.platform === "win32") {
  const probe = spawnSync("cmd.exe", ["/d", "/c", "pwsh", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.Major"], { encoding: "utf8" });
  if (probe.status === 0 && Number.parseInt(probe.stdout, 10) >= 7) {
    pwshCommand = "cmd.exe";
    pwshPrefix = ["/d", "/c", "pwsh"];
  }
}
if (!pwshCommand && process.platform === "win32") fail("Release-Audit benötigt PowerShell 7; Windows PowerShell 5.1 wird nicht unterstützt");
const runPwsh = (args, options) => spawnSync(pwshCommand, [...pwshPrefix, ...args], options);
if (pwshCommand) {
  const psFile = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"];
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-release-audit-"));
  const commonPath = path.join(root, "build", "Release.Common.ps1").replace(/'/g, "''");
  const behaviorPath = path.join(temp, "behavior.ps1");
  fs.writeFileSync(behaviorPath, `$ErrorActionPreference = "Stop"
. '${commonPath}'
try {
  Invoke-NativeCommand (Get-Process -Id $PID).Path @("-NoProfile", "-Command", "exit 23")
  throw "Befehl wurde nach Fehler fortgesetzt"
} catch {
  if ($_.Exception.Data["ExitCode"] -ne 23 -or -not $_.Exception.Data["Command"]) { throw "Nativer Fehler ist nicht strukturiert" }
}
$temp = Join-Path ([IO.Path]::GetTempPath()) ("magnolie-rollback-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory $temp | Out-Null
try {
  $live1 = Join-Path $temp "live1"; $live2 = Join-Path $temp "live2"
  $stage1 = Join-Path $temp "stage1"; $stage2 = Join-Path $temp "stage2"
  Set-Content $live1 old1; Set-Content $live2 old2; Set-Content $stage1 new1; Set-Content $stage2 new2
  $script:failBackup = $true
  function Move-Item { param($LiteralPath, $Destination)
    if ($script:failBackup -and $LiteralPath -eq $live2 -and $Destination -like "*.rollback") { throw "simulierter Backupfehler" }
    Microsoft.PowerShell.Management\\Move-Item -LiteralPath $LiteralPath -Destination $Destination
  }
  try { Install-StagedPaths @(,@($stage1,$live1),@($stage2,$live2)); throw "Backupfehler nicht ausgelöst" } catch {
    if ((Get-Content $live1 -Raw).Trim() -ne "old1" -or (Get-Content $live2 -Raw).Trim() -ne "old2") { throw "Unberührtes Liveziel wurde verändert" }
  }
  $script:failBackup = $false; $script:failInstall = $true
  function Move-Item { param($LiteralPath, $Destination)
    if ($script:failInstall -and $LiteralPath -eq $stage2) { throw "simulierter Installationsfehler" }
    Microsoft.PowerShell.Management\\Move-Item -LiteralPath $LiteralPath -Destination $Destination
  }
  try { Install-StagedPaths @(,@($stage1,$live1),@($stage2,$live2)); throw "Installationsfehler nicht ausgelöst" } catch {
    if ((Get-Content $live1 -Raw).Trim() -ne "old1" -or (Get-Content $live2 -Raw).Trim() -ne "old2") { throw "Rollback stellte Liveziele nicht wieder her" }
  }
  } finally { Remove-Item $temp -Recurse -Force }
  $cleanupRoot = Join-Path ([IO.Path]::GetTempPath()) ("magnolie-unsigned-cleanup-" + [Guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory $cleanupRoot | Out-Null
  try {
    $stale = Join-Path $cleanupRoot "Magnolie-Organizer-Windows-99.88.77-Setup-x64-UNSIGNED.ExE"
    $canonical = Join-Path $cleanupRoot "Magnolie-Organizer-Windows-99.88.77-Setup-x64.exe"
    $unrelated = Join-Path $cleanupRoot "Other-Setup-x64-UNSIGNED.exe"
    Set-Content $stale stale; Set-Content $canonical canonical; Set-Content $unrelated unrelated
    Remove-StaleUnsignedInstallers $cleanupRoot
    if ((Test-Path $stale) -or -not (Test-Path $canonical) -or -not (Test-Path $unrelated)) { throw "Bereinigung alter UNSIGNED-Artefakte ist nicht eng begrenzt" }
  } finally { Remove-Item $cleanupRoot -Recurse -Force }
`, "utf8");
  fs.appendFileSync(behaviorPath, `
$sourceRoot = Join-Path ([IO.Path]::GetTempPath()) ("magnolie-source-policy-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory (Join-Path $sourceRoot "tests/fixtures") -Force | Out-Null
New-Item -ItemType Directory (Join-Path $sourceRoot "vm") -Force | Out-Null
New-Item -ItemType Directory (Join-Path $sourceRoot "Ausgabe") -Force | Out-Null
New-Item -ItemType Directory (Join-Path $sourceRoot ".claude") -Force | Out-Null
try {
  Set-Content (Join-Path $sourceRoot "source-resource.png") "source png"
  Set-Content (Join-Path $sourceRoot "tests/fixtures/contact.vcf") "fixture"
  Set-Content (Join-Path $sourceRoot "tests/fixtures/calendar.ics") "fixture"
  Set-Content (Join-Path $sourceRoot "tests/fixtures/contact.ldif") "fixture"
  Set-Content (Join-Path $sourceRoot "Magnolie-Organizer-Windows-99.88.77-Setup-x64-UNSIGNED.ExE") "fake installer"
  Set-Content (Join-Path $sourceRoot "Other-9.0-X64.ZIP") "generated zip"
  Set-Content (Join-Path $sourceRoot "Other-9.0-sOuRcE.ZiP") "generated source"
  Set-Content (Join-Path $sourceRoot "Other-9.0-pruefsummen.SHA256") "checksum"
  Set-Content (Join-Path $sourceRoot "vm/windows-test.PNG") "screenshot"
  Set-Content (Join-Path $sourceRoot "Ausgabe/generated.txt") "build output"
  Set-Content (Join-Path $sourceRoot ".claude/settings.local.json") "local settings"
  Set-Content (Join-Path $sourceRoot ".env") "SECRET=value"
  Set-Content (Join-Path $sourceRoot "release.pfx") "secret certificate"
  $sourceNames = @(Get-ReleaseSourceFiles $sourceRoot | ForEach-Object { [IO.Path]::GetRelativePath($sourceRoot, $_.FullName).Replace('\\', '/') })
  foreach ($requiredSource in @("source-resource.png", "tests/fixtures/contact.vcf", "tests/fixtures/calendar.ics", "tests/fixtures/contact.ldif")) {
    if ($sourceNames -cnotcontains $requiredSource) { throw "Legitime Quelldatei wurde ausgeschlossen: $requiredSource" }
  }
  foreach ($generated in @("Magnolie-Organizer-Windows-99.88.77-Setup-x64-UNSIGNED.ExE", "Other-9.0-X64.ZIP", "Other-9.0-sOuRcE.ZiP", "Other-9.0-pruefsummen.SHA256", "vm/windows-test.PNG", "Ausgabe/generated.txt", ".claude/settings.local.json", ".env", "release.pfx")) {
    if ($sourceNames -icontains $generated) { throw "Erzeugte Datei wurde als Quelle akzeptiert: $generated" }
  }
} finally { Remove-Item $sourceRoot -Recurse -Force }
`, "utf8");
  const behavior = runPwsh(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", behaviorPath], { encoding: "utf8" });
  if (behavior.status !== 0) fail(`PowerShell-Verhaltenstest fehlgeschlagen: ${behavior.stderr || behavior.stdout}`);
  const publicationBehavior = runPwsh(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path.join(root, "tests", "powershell-installer-publication.ps1"), "-Common", path.join(root, "build", "Release.Common.ps1")], { encoding: "utf8" });
  if (publicationBehavior.status !== 0) fail(`PowerShell-Installertransaktion fehlgeschlagen: ${publicationBehavior.stderr || publicationBehavior.stdout}`);

  const checksumLayout = path.join(temp, "checksum-layout");
  const checksumProject = path.join(checksumLayout, "project");
  fs.mkdirSync(checksumProject, { recursive: true });
  const sourceArchive = path.join(checksumProject, `Magnolie-Organizer-Windows-${version}-Source.zip`);
  const binaryZip = path.join(checksumProject, `Magnolie-Organizer-Windows-${version}-x64.zip`);
  const setup = path.join(checksumProject, `Magnolie-Organizer-Windows-${version}-Setup-x64.exe`);
  const checksum = path.join(checksumProject, `Magnolie-Organizer-Windows-${version}-PRUEFSUMMEN.sha256`);
  fs.writeFileSync(sourceArchive, "source fixture\n");
  fs.writeFileSync(binaryZip, "zip fixture\n");
  fs.writeFileSync(setup, "setup fixture\n");
  const psQuote = value => value.replace(/'/g, "''");
  const checksumCommand = `. '${commonPath}'; Write-ReleaseChecksums '${psQuote(root)}' '${version}' '${psQuote(checksum)}' @([pscustomobject]@{ Source='${psQuote(sourceArchive)}'; DisplayPath='${path.basename(sourceArchive)}' }, [pscustomobject]@{ Source='${psQuote(binaryZip)}'; DisplayPath='${path.basename(binaryZip)}' }, [pscustomobject]@{ Source='${psQuote(setup)}'; DisplayPath='${path.basename(setup)}' })`;
  const checksumResult = runPwsh(["-NoProfile", "-Command", checksumCommand], { encoding: "utf8" });
  if (checksumResult.status !== 0) fail(`Prüfsummen-Verhaltenstest fehlgeschlagen: ${checksumResult.stderr || checksumResult.stdout}`);
  const checksumText = fs.readFileSync(checksum, "utf8");
  if (!checksumText.includes(`  ${path.basename(sourceArchive)}`) || !checksumText.includes(`  ${path.basename(binaryZip)}`) || !checksumText.includes(`  ${path.basename(setup)}`)) fail("Prüfsummendatei enthält nicht die veröffentlichten relativen Pfade");
  if (checksumText.includes("Setup-x64-UNSIGNED.exe")) fail("Prüfsummendatei enthält einen nichtkanonischen Installernamen");
  const sha256sum = spawnSync("sha256sum", ["--version"], { encoding: "utf8" });
  if (!sha256sum.error && sha256sum.status === 0) {
    const check = spawnSync("sha256sum", ["-c", path.basename(checksum)], { cwd: checksumProject, encoding: "utf8" });
    if (check.status !== 0) fail(`sha256sum -c lehnte Prüfsummendatei ab: ${check.stderr || check.stdout}`);
  }

  const buildScript = path.join(root, "build", "Build.ps1");
  const crossEnv = { ...process.env, NSISDIR: temp };
  delete crossEnv.MAGNOLIE_OFFICIAL_RELEASE;
  delete crossEnv.MAGNOLIE_CONTRIBUTOR_HASH;
  for (const name of ["MAGNOLIE_SIGNTOOL", "MAGNOLIE_SIGN_CERTIFICATE", "MAGNOLIE_SIGN_PASSWORD", "MAGNOLIE_SIGN_PUBLISHER", "MAGNOLIE_TIMESTAMP_URL"]) delete crossEnv[name];
  if (process.platform === "linux") {
    const officialCross = runPwsh([...psFile, buildScript, "-CrossCompile"], { encoding: "utf8", env: { ...crossEnv, MAGNOLIE_OFFICIAL_RELEASE: "1" } });
    if (officialCross.status === 0 || !`${officialCross.stdout}${officialCross.stderr}`.includes("keine offizielle Ausgabe")) fail("Cross-Bau akzeptierte den offiziellen Modus");
    const signedCross = runPwsh([...psFile, buildScript, "-CrossCompile"], { encoding: "utf8", env: { ...crossEnv, MAGNOLIE_SIGNTOOL: "configured" } });
    if (signedCross.status === 0 || !`${signedCross.stdout}${signedCross.stderr}`.includes("verweigert konfigurierte Signierung")) fail("Cross-Bau akzeptierte Signierkonfiguration");
    const missingNsisDir = { ...crossEnv }; delete missingNsisDir.NSISDIR;
    const noNsisDirCross = runPwsh([...psFile, buildScript, "-CrossCompile"], { encoding: "utf8", env: missingNsisDir });
    if (noNsisDirCross.status === 0 || !`${noNsisDirCross.stdout}${noNsisDirCross.stderr}`.includes("extern gesetztes NSISDIR")) fail("Cross-Bau akzeptierte fehlendes NSISDIR");
    const missingHashCross = runPwsh([...psFile, buildScript, "-CrossCompile"], { encoding: "utf8", env: crossEnv });
    if (missingHashCross.status === 0 || !`${missingHashCross.stdout}${missingHashCross.stderr}`.includes("Binärausgabe benötigt MAGNOLIE_CONTRIBUTOR_HASH")) fail("Cross-Bau akzeptierte fehlendes Contributor-Branding");
  } else {
    const nonLinuxCross = runPwsh([...psFile, buildScript, "-CrossCompile"], { encoding: "utf8", env: crossEnv });
    if (nonLinuxCross.status === 0 || !`${nonLinuxCross.stdout}${nonLinuxCross.stderr}`.includes("ausschließlich für einen Linux-Bau")) fail("Cross-Bau lief außerhalb von Linux");
  }

  const installer = path.join(temp, `Magnolie-Organizer-Windows-${version}-Setup-x64.exe`);
  const unsignedInstaller = path.join(temp, `Magnolie-Organizer-Windows-${version}-Setup-x64-UNSIGNED.exe`);
  const manifest1 = path.join(temp, "one.xml");
  const manifest2 = path.join(temp, "two.xml");
  fs.writeFileSync(installer, "test");
  fs.writeFileSync(unsignedInstaller, "test");
  const duplicate = `<update><windows><version>${version}</version><url>https://example.invalid/${path.basename(installer)}</url><sha256>x</sha256></windows><windows><version>${version}</version><url>https://example.invalid/${path.basename(installer)}</url><sha256>x</sha256></windows></update>`;
  fs.writeFileSync(manifest1, duplicate); fs.writeFileSync(manifest2, duplicate);
  const manifestScript = path.join(root, "build", "UpdateManifest.ps1");
  const policyEnv = { ...process.env, OS: "Windows_NT" };
  delete policyEnv.MAGNOLIE_SIGN_PUBLISHER;
  delete policyEnv.MAGNOLIE_SIGNTOOL;
  const noPolicy = runPwsh([...psFile, manifestScript, "-Installer", installer, "-RootManifest", manifest1, "-LinuxSourceManifest", manifest2], { encoding: "utf8", env: policyEnv });
  if (noPolicy.status === 0 || !`${noPolicy.stdout}${noPolicy.stderr}`.includes("Signaturprüfung benötigt")) fail("Manifesthelfer lief ohne Herausgeber-Policy");
  const unsignedTest = runPwsh([...psFile, manifestScript, "-Installer", unsignedInstaller, "-ExpectedPublisher", "CN=Release", "-RootManifest", manifest1, "-LinuxSourceManifest", manifest2], { encoding: "utf8", env: policyEnv });
  if (unsignedTest.status === 0 || !`${unsignedTest.stdout}${unsignedTest.stderr}`.includes("Installername entspricht nicht")) fail("Manifesthelfer akzeptierte UNSIGNED-Artefakt");
  const escapedManifestScript = manifestScript.replace(/'/g, "''");
  const escapedInstaller = installer.replace(/'/g, "''");
  const escapedManifest1 = manifest1.replace(/'/g, "''");
  const escapedManifest2 = manifest2.replace(/'/g, "''");
  const mockSignature = `function Get-AuthenticodeSignature { [pscustomobject]@{ Status = 'Valid'; SignerCertificate = [pscustomobject]@{ Subject = 'CN=Release' }; TimeStamperCertificate = [pscustomobject]@{} } }; & '${escapedManifestScript}' -Installer '${escapedInstaller}' -ExpectedPublisher 'CN=Release' -RootManifest '${escapedManifest1}' -LinuxSourceManifest '${escapedManifest2}'`;
  const manifestTest = runPwsh(["-NoProfile", "-Command", mockSignature], { encoding: "utf8", env: policyEnv });
  if (manifestTest.status === 0 || !`${manifestTest.stdout}${manifestTest.stderr}`.includes("genau ein /update/windows")) fail("Doppelte XML-Ziele wurden nicht geschlossen abgewiesen");
  const signedXml = `<update><windows><version>${version}</version><url>https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/${path.basename(installer)}</url><sha256>${"a".repeat(64)}</sha256></windows><signature>fixture</signature></update>`;
  fs.writeFileSync(manifest1, signedXml); fs.writeFileSync(manifest2, signedXml);
  const signedTest = runPwsh(["-NoProfile", "-Command", mockSignature], { encoding: "utf8", env: policyEnv });
  if (signedTest.status === 0 || !`${signedTest.stdout}${signedTest.stderr}`.includes("Signiertes Manifest wird nicht verändert")) fail("Eingebettetes kleingeschriebenes signature wurde mutiert");
  const report = path.join(temp, "manifest-follow-up.json");
  const auditManifest = path.join(root, "build", "AuditUpdateManifest.ps1");
  const staleAuditCommand = `& '${psQuote(auditManifest)}' -Manifest @('${psQuote(manifest1)}','${psQuote(manifest2)}') -Report '${psQuote(report)}'`;
  const staleAudit = runPwsh(["-NoProfile", "-Command", staleAuditCommand], { encoding: "utf8" });
  if (staleAudit.status === 0 || JSON.parse(fs.readFileSync(report, "utf8"))[0].windowsReleaseStatus !== "UNVEROEFFENTLICHT") fail("Unbelegter Windows-Hash wurde nicht fail-closed ausgewiesen");
  fs.rmSync(temp, { recursive: true, force: true });
} else {
  if (!updater.includes('$windowsNodes.Count -ne 1')) fail("Statischer Nachweis gegen doppelte XML-Ziele fehlt");
}
console.log(`Release-Audit für ${version} bestanden.`);
