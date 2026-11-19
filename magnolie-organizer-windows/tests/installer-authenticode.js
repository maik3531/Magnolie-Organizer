#!/usr/bin/env node
"use strict";
// Exercise the actual audit dispatcher with synthetic bytes and controlled
// archive/verifier dependencies. No executable, extractor or signer is started.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const vm = require("node:vm");
const audit = fs.readFileSync(path.join(__dirname, "../installer/AuditInstaller.js"), "utf8");
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-installer-signature-"));
try {
  const expectedName = "Magnolie-Organizer-Windows-9.8.7-Setup-x64.exe";
  const installer = path.join(temp, expectedName);
  const publish = path.join(temp, "payload");
  fs.mkdirSync(publish);
  const app = Buffer.from("MZ synthetic application, never executed\n");
  fs.writeFileSync(path.join(publish, "Magnolie Organizer.exe"), app);
  const image = Buffer.alloc(1024);
  image.write("MZ"); image.writeUInt32LE(128, 60); image.write("PE\0\0", 128, "binary");
  image.writeUInt16LE(0x8664, 132); image.writeUInt16LE(1, 134); image.writeUInt16LE(224, 148);
  image.writeUInt16LE(0x20b, 152); image.writeUInt32LE(512, 212);
  image.writeUInt32LE(512, 392); image.writeUInt32LE(512, 396);
  Buffer.from(`OriginalFilename\0${expectedName}\0`, "utf16le").copy(image, 512);
  fs.writeFileSync(installer, image);
  const record = path.join(temp, "record.json");
  fs.writeFileSync(record, JSON.stringify({ schema: "magnolie-installer-build-v1", artifact: expectedName,
    bytes: image.length, sha256: crypto.createHash("sha256").update(image).digest("hex") }));
  const host = path.join(temp, "host with spaces");
  const verifier = path.join(temp, "verifier with spaces.ps1");
  const report = path.join(temp, "report.json");
  const receipt = path.join(temp, "receipt.json");
  const signedArgs = ["--authenticode", host, verifier, "CN=Product", "mock tool", report, receipt];
  let count = 0;
  for (const scenario of ["unsigned", "signed", "host-rejected", "host-error", "wrong-flag", "short-args", "changed-payload", "payload-rejected"]) {
    const calls = [], extracts = [], output = [];
    let payloadChecked = false;
    const args = scenario === "unsigned" ? [] : scenario === "short-args" ? ["--authenticode"] : [...signedArgs];
    if (scenario === "wrong-flag") args[0] = "--unknown";
    const spawnSync = (command, argv) => {
      calls.push([command, argv]);
      if (["7z", "7zz", "7za"].includes(command)) {
        if (argv[0] === "i") return { status: 0 };
        if (argv[0] === "t") return { status: 0, stdout: "Type = Nsis\n", stderr: "" };
        assert.equal(argv[0], "x");
        const extracted = argv.find(arg => arg.startsWith("-o")).slice(2);
        extracts.push(extracted);
        fs.writeFileSync(path.join(extracted, "Magnolie Organizer.exe"), scenario === "changed-payload" ? "changed" : app);
        return { status: 0, stdout: "", stderr: "" };
      }
      assert.equal(command, host);
      assert.equal(payloadChecked, true, "Signature verifier ran before byte/payload checks");
      assert.deepEqual(Array.from(argv), ["-NoProfile", "-NonInteractive", "-File", verifier,
        "-Root", extracts[0], "-Publisher", "CN=Product", "-SignTool", "mock tool", "-Report", report,
        "-Installer", installer, "-UninstallerReceipt", receipt]);
      return scenario === "host-error" ? { error: new Error("controlled host error"), status: null } : { status: scenario === "host-rejected" ? 1 : 0 };
    };
    let failure;
    try {
      vm.runInNewContext(audit, {
        require(name) {
          if (name === "node:child_process") return { spawnSync };
          if (name === "../build/AuditWebPayload") return { artifactPayload(from, to) {
            assert.equal(from, publish); assert.equal(to, extracts[0]);
            if (scenario === "payload-rejected") throw new Error("controlled payload rejection");
            payloadChecked = true;
          } };
          return require(name);
        },
        process: { argv: [process.execPath, "AuditInstaller.js", installer, publish, expectedName, record, ...args], env: {} },
        Buffer, console: { log: text => output.push(text) }
      }, { timeout: 2000, filename: "AuditInstaller.js" });
    } catch (error) { failure = error; }
    if (["unsigned", "signed"].includes(scenario)) {
      assert.equal(failure, undefined); assert.equal(output.length, 1);
    } else {
      assert.ok(failure, `Audit accepted ${scenario}`); assert.equal(output.length, 0);
    }
    assert.equal(calls.filter(([command]) => command === host).length,
      ["signed", "host-rejected", "host-error"].includes(scenario) ? 1 : 0);
    for (const extracted of extracts) assert.equal(fs.existsSync(extracted), false, "Audit did not clean its owned extraction");
    count++;
  }
  console.log(`${count} installer Authenticode dispatch cases passed (controlled dependencies; no native signing/extraction).`);
} finally { fs.rmSync(temp, { recursive: true, force: true }); }
