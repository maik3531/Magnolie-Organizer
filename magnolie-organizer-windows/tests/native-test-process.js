"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { spawnSync } = require("node:child_process");

function findExecutable(candidates, args, minimumMajor, probe = spawnSync) {
  const diagnostics = [];
  for (const command of [...new Set(candidates.filter(Boolean))]) {
    if (path.isAbsolute(command) && !fs.existsSync(command) && probe === spawnSync) {
      diagnostics.push(`${command}: executable file missing`); continue;
    }
    if (process.platform === "win32" && process.env.LOCALAPPDATA &&
        path.resolve(command).toLowerCase().startsWith(path.join(process.env.LOCALAPPDATA, "Microsoft/WindowsApps").toLowerCase() + path.sep)) {
      diagnostics.push(`${command}: execution alias is not an installed tool`); continue;
    }
    const result = probe(command, args, { encoding: "utf8", timeout: 10000, windowsHide: true });
    const version = typeof result.stdout === "string" ? /^(\d+)(?:[.\s]|$)/.exec(result.stdout.trim()) : null;
    if (!result.error && result.status === 0 && !result.signal && version && Number(version[1]) >= minimumMajor)
      return { command, diagnostics };
    diagnostics.push(`${command}: ${result.error?.code || result.error?.message || `status=${result.status}, signal=${result.signal || "none"}, version=${version?.[1] || "missing"}`}`);
  }
  return { command: null, diagnostics };
}

function assertSpawned(result, label) {
  assert.ifError(result.error);
  assert.ok(Number.isInteger(result.status), `${label} did not return an exit status (signal=${result.signal || "none"})`);
  assert.ok(!result.signal, `${label} was terminated by ${result.signal}`);
  return result;
}

// A PASS line inside a child does not prove that the child actually exited.
// Keep web-gate hangs attributable and bounded rather than waiting for the
// six-hour CI job limit (Refs #674). This does not change product deadlines.
function runBoundedProgram(command, args, {
  label, env = process.env, timeoutMs = 300000, spawn = spawnSync, write = console.log
} = {}) {
  assert.ok(typeof label === "string" && label.length > 0);
  assert.ok(Number.isInteger(timeoutMs) && timeoutMs > 0);
  const started = Date.now();
  write(`TEST START ${label}`);
  let result;
  try {
    result = spawn(command, args, { stdio: "inherit", env, timeout: timeoutMs, killSignal: "SIGKILL" });
  } catch (error) {
    result = { error, status: null, signal: null };
  }
  write(`TEST END ${label}: status=${result.status}, signal=${result.signal || "none"}, error=${result.error?.code || result.error?.message || "none"}, elapsedMs=${Date.now() - started}`);
  return result;
}

module.exports = { findExecutable, assertSpawned, runBoundedProgram };
