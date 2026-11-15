"use strict";
const assert = require("node:assert/strict");
const { findExecutable, assertSpawned } = require("./native-test-process");
const missing = Object.assign(new Error("Synthetic executable missing"), { code: "ENOENT" });
const fixtures = [
  [{ status: 0, signal: null, stdout: "8.0.428\r\n" }, true],
  [{ status: 0, signal: null, stdout: "10.0.100\n" }, true],
  [{ status: 0, signal: null, stdout: "6.0.100\n" }, false],
  [{ status: 0, signal: null, stdout: "8.0.428", error: missing }, false],
  [{ status: null, signal: "SIGTERM", stdout: "8.0.428" }, false],
  [{ status: 1, signal: null, stdout: "8.0.428" }, false],
  [{ status: 0, signal: null, stdout: "" }, false],
  [{ status: 0, signal: null, stdout: "not a version" }, false]
];
for (const [result, expected] of fixtures) {
  const selected = findExecutable(["synthetic-tool"], ["--version"], 8, () => result);
  assert.equal(Boolean(selected.command), expected);
  if (!expected) assert.equal(selected.diagnostics.length, 1);
}
const calls = [];
const selected = findExecutable(["missing", "working"], ["--version"], 8, command => {
  calls.push(command); return command === "missing" ? { status: 0, error: missing } : { status: 0, stdout: "10.0.100" };
});
assert.equal(selected.command, "working"); assert.deepEqual(calls, ["missing", "working"]);
assert.equal(findExecutable(["configured-only"], [], 7, () => ({ status: 0, error: missing })).command, null);
assert.equal(findExecutable(["powershell"], [], 7, () => ({ status: 0, stdout: "5\n" })).command, null);
assert.equal(findExecutable(["powershell"], [], 7, () => ({ status: 0, stdout: "7\r\n" })).command, "powershell");
assert.throws(() => assertSpawned({ status: null, stdout: null, stderr: null, error: missing }, "policy"));
assert.throws(() => assertSpawned({ status: null, stdout: null, stderr: null }, "policy"));
assert.throws(() => assertSpawned({ status: 1, signal: "SIGTERM" }, "policy"));
assert.equal(assertSpawned({ status: 1, signal: null }, "actual expected rejection").status, 1);
console.log("Native test-process cases passed: real startup/status, supported newer SDKs and no false policy rejection from null results.");
