"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict"), crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
const root = path.resolve(process.argv[2]), output = path.resolve(process.argv[3]);
const file = path.join(root, "magnolie-organizer-windows/tests/desktop-state-regressions.js");
const originalHarness = fs.readFileSync(file, "utf8").split("async function run(web)")[0];
const results = [];

async function check(relativeWeb, pageUrl) {
  // Only the fixture's document URL changes; both product scripts are evaluated unchanged.
  const source = originalHarness.replace('url: "https://desktop-regression.invalid/index.html"', "url: " + JSON.stringify(pageUrl));
  assert.notEqual(source, originalHarness);
  const mod = new Module(file, module); mod.filename = file; mod.paths = Module._nodeModulePaths(path.dirname(file));
  mod._compile(source + "\nmodule.exports = { boot };", file);
  const b = await mod.exports.boot(path.join(root, relativeWeb), {});
  const urls = new Set(), unload = new Map(), workers = [];
  let failConstructor = false, created = 0, revoked = 0, terminations = 0, seq = 0;
  const add = b.w.addEventListener.bind(b.w), remove = b.w.removeEventListener.bind(b.w);
  b.w.addEventListener = (type, fn, options) => {
    if (type !== "unload") return add(type, fn, options);
    const wrapped = function (event) { if (options?.once) unload.delete(fn); return fn.call(this, event); };
    unload.set(fn, wrapped); return add(type, wrapped, options);
  };
  b.w.removeEventListener = (type, fn, options) => {
    const wrapped = type === "unload" ? unload.get(fn) : null;
    if (type === "unload") unload.delete(fn);
    return remove(type, wrapped || fn, options);
  };
  const custom = pageUrl.startsWith("magnolie-organizer:");
  b.w.Blob = Blob;
  b.w.URL.createObjectURL = blob => { created++; const url = URL.createObjectURL(blob); urls.add(url); return url; };
  b.w.URL.revokeObjectURL = url => { URL.revokeObjectURL(url); if (urls.delete(url)) revoked++; };
  b.w.Worker = class {
    constructor(url) {
      assert.equal(url.startsWith("data:text/javascript,"), custom);
      assert.equal(url.startsWith("blob:"), !custom);
      if (failConstructor) throw new Error("controlled constructor failure");
      this.terminated = 0; workers.push(this);
    }
    postMessage(payload) { this.payload = payload; }
    terminate() { this.terminated++; terminations++; }
  };
  const query = () => {
    const item = { uid: "independent-843-" + seq++, datum: "2026-06-12", zeit: "09:00",
      icsRoundtrip: ["DTSTART:20260612T090000Z", "DURATION:PT1H", "RRULE:FREQ=DAILY;COUNT=2"] };
    assert.equal(b.t.icsRuntime("expand", item, [0, 1]), null);
    return b.t.icsRuntime.state.worker;
  };
  const resources = expected => {
    assert.equal(urls.size, custom ? 0 : expected, "wrong active object URL count");
    assert.equal(unload.size, expected, "wrong active unload listener count");
  };
  try {
    failConstructor = true;
    for (let i = 0; i < 3; i++) { query(); resources(0); }
    failConstructor = false;
    const old = query(); resources(1);
    let replacement = null;
    const restart = () => {
      if (replacement || b.t.icsRuntime.state.worker !== null) return;
      replacement = query();
    };
    b.w.document.addEventListener("magnolie-recurrence-progress", restart);
    old.onmessage({ data: { key: old.payload.key, timeZoneIdentity: "wrong-provider" } });
    b.w.document.removeEventListener("magnolie-recurrence-progress", restart);
    assert.ok(replacement && replacement !== old, "synchronous publication did not construct a replacement");
    assert.equal(old.terminated, 1); assert.equal(replacement.terminated, 0);
    assert.equal(b.t.icsRuntime.state.worker, replacement); resources(1);
    old.onerror(new Error("late old error"));
    old.onmessage({ data: { key: replacement.payload.key, timeZoneIdentity: "wrong-old-provider" } });
    assert.equal(b.t.icsRuntime.state.worker, replacement);
    assert.equal(b.t.icsRuntime.state.jobs.get(replacement.payload.key).status, "pending");
    assert.equal(old.terminated, 1); resources(1);
    replacement.onmessage({ data: { key: replacement.payload.key,
      timeZoneIdentity: replacement.payload.timeZoneIdentity, result: [] } });
    assert.equal(b.t.icsRuntime.state.jobs.get(replacement.payload.key).status, "ready");
    assert.equal(b.t.icsRuntime.state.worker, replacement); resources(1);
    assert.equal(query(), replacement, "success discarded the healthy worker");
    replacement.onmessage({ data: { key: replacement.payload.key,
      timeZoneIdentity: replacement.payload.timeZoneIdentity, error: "recurrence-output-limit" } });
    assert.equal(b.t.icsRuntime.state.jobs.get(replacement.payload.key).status, "error");
    assert.equal(b.t.icsRuntime.state.worker, replacement); resources(1);
    replacement.onerror(new Error("controlled worker failure")); resources(0);
    replacement.onerror(new Error("repeated disposed-worker callback")); resources(0);
    assert.equal(replacement.terminated, 1);
    const final = query(); resources(1);
    b.w.dispatchEvent(new b.w.Event("unload")); resources(0);
    b.w.dispatchEvent(new b.w.Event("unload")); resources(0);
    assert.equal(final.terminated, 1); assert.equal(terminations, 3);
    assert.equal(created, custom ? 0 : 6); assert.equal(revoked, created);
    results.push({ web: relativeWeb, page_protocol: custom ? "magnolie-organizer:" : "https:",
      passed: true, constructor_failures: 3, synchronous_replacement_preserved: true,
      stale_callbacks_ignored: true, successful_result_preserved: true,
      job_error_keeps_worker: true, idempotent_disposal: true,
      object_urls_created: created, object_urls_revoked: revoked, workers_terminated: terminations });
  } finally {
    for (const url of urls) URL.revokeObjectURL(url);
    b.close();
  }
}

(async () => {
  await check("magnolie-organizer-windows/app/web", "https://independent-843.invalid/index.html");
  await check("magnolie-organizer/web", "https://independent-843.invalid/index.html");
  await check("magnolie-organizer/web", "magnolie-organizer://app/index.html");
  const sources = Object.fromEntries(["magnolie-organizer/web/anwendung.js", "magnolie-organizer-windows/app/web/anwendung.js"]
    .map(file => [file, crypto.createHash("sha256").update(fs.readFileSync(path.join(root, file))).digest("hex")]));
  const report = { root, head: execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim(),
    node: process.version, sources, passed: true, cases: results.length, results,
    boundary_de: "Unveränderte Produktfunktionen in JSDOM mit echten Node-Blob-URLs; Worker-Ereignisse kontrolliert injiziert. Der data:-Pfad prüft Protokollwahl und Lebensdauer, keine echte WebKit-Ausführung. Keine native Heap-/Monats-Tray-Abnahme." };
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify(report));
})().catch(error => { console.error(error); process.exitCode = 1; });
