#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { assertSpawned } = require("./native-test-process");

const root = path.resolve(__dirname, "..");
const publisher = path.join(root, "installer", "PublishInstaller.sh");
const name = "Magnolie-Organizer-Windows-9.8.7-Setup-x64.exe";
const windows = process.platform === "win32";
const bash = process.env.MAGNOLIE_TEST_BASH || (windows
  ? [process.env.ProgramFiles, process.env["ProgramFiles(x86)"]].filter(Boolean)
    .map(base => path.join(base, "Git/bin/bash.exe")).find(file => fs.existsSync(file))
  : "bash");
assert.ok(bash, "The shell-publication fixture requires an existing Git Bash; no tools are installed by this test.");
const capabilities = spawnSync(bash, ["-c", "test -x /usr/bin/bash && test -x /usr/bin/mv && test -x /usr/bin/cp && test -x /usr/bin/rm"],
  { encoding: "utf8", timeout: 10000 });
assertSpawned(capabilities, "Existing shell-publication tools");
assert.equal(capabilities.status, 0, "The configured Bash lacks the required existing POSIX tools.");
function shellPath(file) {
  if (!windows) return file;
  const result = spawnSync(bash, ["-c", 'exec /usr/bin/cygpath -u "$1"', "magnolie-path", file],
    { encoding: "utf8", timeout: 10000 });
  assertSpawned(result, "Windows-to-POSIX fixture path");
  assert.equal(result.status, 0, result.stderr || result.stdout);
  const converted = result.stdout.trim();
  assert.ok(converted.startsWith("/") && !/[\r\n]/.test(converted), "Invalid POSIX fixture path");
  return converted;
}
const shellPublisher = shellPath(publisher), shellRuntime = shellPath(process.execPath);

function writeExecutable(target, contents) {
  fs.writeFileSync(target, contents, { mode: 0o755 });
}

function runCase(failure = {}) {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-publish Prüfung-"));
  try {
  const bin = path.join(fixture, "bin");
  const publish = path.join(fixture, "Ausgabe");
  fs.mkdirSync(bin); fs.mkdirSync(publish);
  const stage = path.join(fixture, ".new.exe");
  const recordStage = path.join(fixture, ".new.build.json");
  const live = path.join(fixture, name);
  const record = `${live}.build.json`;
  const stale = path.join(fixture, "Magnolie-Organizer-Windows-1.2.3-Setup-x64-UNSIGNED.exe");
  fs.writeFileSync(stage, "new installer"); fs.writeFileSync(recordStage, "new record");
  fs.writeFileSync(live, "old installer"); fs.writeFileSync(record, "old record"); fs.writeFileSync(stale, "old stale");
  for (const command of ["mv", "rm", "cp"]) writeExecutable(path.join(bin, command), `#!/usr/bin/env bash
counter="$MAGNOLIE_PUBLISH_TEST_FIXTURE/.${command}-count"; count=0; [[ ! -f "$counter" ]] || read -r count < "$counter"; count=$((count+1)); printf '%s' "$count" > "$counter"
if [[ "\${MAG_FAIL_${command.toUpperCase()}_AT:-0}" == "$count" ]]; then exit 71; fi
exec /usr/bin/${command} "$@"
`);
  const audit = path.join(fixture, "audit.js");
  fs.writeFileSync(audit, `if (process.env.MAG_FAIL_AUDIT === "1") process.exit(72); const fs=require("node:fs"); if(fs.readFileSync(process.argv[2],"utf8")!=="new installer"||fs.readFileSync(process.argv[5],"utf8")!=="new record") process.exit(73);`);
  // Resolve Bash with the native PATH intact. Add the injected command wrappers
  // only AFTER entering its POSIX environment; Windows PATH uses semicolons and
  // drive colons cannot be concatenated as if they were POSIX separators.
  const result = spawnSync(bash, ["-c", 'export PATH="$1:$PATH"; shift; exec /usr/bin/bash "$@"', "magnolie-publication",
    shellPath(bin), shellPublisher, shellPath(fixture), shellPath(stage), shellPath(recordStage),
    shellPath(publish), name, shellRuntime, shellPath(audit)], {
    encoding: "utf8", timeout: 30000,
    env: { ...process.env, MAGNOLIE_PUBLISH_TEST_FIXTURE: shellPath(fixture), ...failure }
  });
  assertSpawned(result, "Synthetic shell publication");
  if (Object.keys(failure).length) {
    assert.notEqual(result.status, 0, `Fehler wurde nicht ausgelöst: ${JSON.stringify(failure)}`);
    assert.equal(fs.readFileSync(live, "utf8"), "old installer");
    assert.equal(fs.readFileSync(record, "utf8"), "old record");
    assert.equal(fs.readFileSync(stale, "utf8"), "old stale");
  } else {
    assert.equal(result.status, 0, result.stderr || result.stdout);
    assert.equal(fs.readFileSync(live, "utf8"), "new installer");
    assert.equal(fs.readFileSync(record, "utf8"), "new record");
    assert.ok(!fs.existsSync(stale));
  }
  } finally { fs.rmSync(fixture, { recursive: true, force: true }); }
}

runCase();
for (let phase = 1; phase <= 5; phase++) runCase({ MAG_FAIL_MV_AT: String(phase) });
runCase({ MAG_FAIL_AUDIT: "1" });
runCase({ MAG_FAIL_CP_AT: "1" });
runCase({ MAG_FAIL_RM_AT: "1" });
runCase({ MAG_FAIL_RM_AT: "2" });
console.log("Shell-Installerpublikation ist in allen Phasen transaktional.");
