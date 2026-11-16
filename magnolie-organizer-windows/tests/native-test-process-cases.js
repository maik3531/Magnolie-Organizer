"use strict";
const assert = require("node:assert/strict");
const { findExecutable, assertSpawned, runBoundedProgram } = require("./native-test-process");
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
const progress = [];
const environment = { SYNTHETIC_FIXTURE: "1" };
const bounded = runBoundedProgram("owned-tool", ["owned-case"], {
  label: "synthetic bounded launch", env: environment, write: line => progress.push(line),
  spawn(command, args, options) {
    assert.equal(command, "owned-tool"); assert.deepEqual(args, ["owned-case"]);
    assert.equal(options.timeout, 300000); assert.equal(options.killSignal, "SIGKILL");
    assert.equal(options.env, environment); assert.equal(options.stdio, "inherit");
    return { status: 0, signal: null };
  }
});
assert.equal(bounded.status, 0);
assert.match(progress[0], /TEST START synthetic bounded launch/);
assert.match(progress[1], /TEST END synthetic bounded launch: status=0/);
const startupFailure = runBoundedProgram("owned-tool", [], {
  label: "synthetic failed launch", write: () => {}, spawn: () => { throw missing; }
});
assert.equal(startupFailure.error, missing); assert.equal(startupFailure.status, null);
const timeoutProgress = [];
const expired = runBoundedProgram(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
  label: "synthetic hanging child", timeoutMs: 500, write: line => timeoutProgress.push(line)
});
assert.notEqual(expired.status, 0);
assert.equal(expired.error?.code, "ETIMEDOUT");
assert.match(timeoutProgress[1], /TEST END synthetic hanging child/);
const { WorkerFileFixture } = require("./worker-file-fixture");
(async () => {
  let calls = 0, finish;
  const pendingTermination = new Promise(resolve => { finish = resolve; });
  const owned = { terminate() { calls++; return pendingTermination; } };
  const fixture = new WorkerFileFixture();
  fixture.threads.push(owned); // Explicit controlled double, not a product worker.
  const stopped = fixture.stop(owned);
  assert.equal(fixture.stop(owned), stopped);
  let closed = false;
  const closing = fixture.close().then(() => { closed = true; });
  await Promise.resolve();
  assert.equal(closed, false, "Cleanup must await the actual owned termination");
  assert.equal(calls, 1);
  finish(0); await closing;
  assert.equal(fixture.stop(owned), stopped);
  await fixture.close();
  assert.equal(calls, 1, "A stopped worker must never be terminated twice");
  assert.throws(() => fixture.stop({ terminate() { throw new Error("foreign worker invoked"); } }));

  const actual = new WorkerFileFixture();
  try {
    const thread = actual.start("self.onmessage = event => self.postMessage(event.data);");
    const reply = new Promise((resolve, reject) => {
      const deadline = setTimeout(() => reject(new Error("Owned worker echo timeout")), 8000);
      thread.once("message", value => { clearTimeout(deadline); resolve(value); });
      thread.once("error", error => { clearTimeout(deadline); reject(error); });
    });
    thread.postMessage("owned-echo");
    assert.equal(await reply, "owned-echo");
    const first = actual.stop(thread);
    assert.equal(actual.stop(thread), first);
    const folder = actual.folder;
    await actual.close(); await first;
    assert.equal(require("node:fs").existsSync(folder), false);
    assert.equal(actual.threads.length, 0);
  } finally { await actual.close(); }
  console.log("Native test-process cases passed: startup/status/deadlines and owned worker termination once with actual drain.");
})().catch(error => { console.error(error); process.exitCode = 1; });
