/* Actual Advanced webcam functions in a controlled DOM; no driver or phone IO. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto").webcrypto;
const { JSDOM } = require("jsdom");
const source = fs.readFileSync(path.join(__dirname, "../web/anwendung.js"), "utf8");
const begin = source.indexOf("  function kdeMedienAnfordern(");
const end = source.indexOf("  const kdeDateisystemAnsichten", begin);
assert(begin > 0 && end > begin);

async function scenario(reason) {
  const dom = new JSDOM("<!doctype html><body></body>");
  const document = dom.window.document, calls = [], timers = [], pending = new Map();
  const el = (tag, css, text) => {
    const node = document.createElement(tag);
    if (css) node.className = css;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const knopf = (text, css, action) => {
    const button = el("button", css, text); button.run = action; return button;
  };
  const timer = (fn, ms) => { timers.push(ms); return timers.length; };
  const bridge = { sende(message) {
    calls.push(message);
    const waiter = pending.get(message.requestId);
    if (waiter) {
      const value = message.request?.action === "prepare"
        ? { included: true, enabled: false, phase: "off", reason, lease: "", action: reason ? "" : "a".repeat(64),
          choices: reason ? [] : [{ token: "b".repeat(64), phone: "Notes", device: "Controlled virtual camera" }] }
        : message.request?.action === "start"
          ? { included: true, enabled: true, phase: "starting", lease: "c".repeat(64) }
          : { included: true, enabled: false, phase: "off", reason: "", lease: "" };
      pending.delete(message.requestId); waiter.resolve({ ok: true, webcam: value });
    }
    return true;
  }};
  const build = new Function("document", "el", "knopf", "_", "crypto", "setTimeout", "clearTimeout",
    "kdeMedienAnfragen", "Bruecke", "gesperrt", source.slice(begin, end) + "\nreturn baueTelefonWebcam;")(
      document, el, knopf, text => text, crypto, timer, () => {}, pending, bridge, false);
  const root = el("details");
  Object.defineProperty(root, "open", { value: true });
  document.body.append(root); build(root);
  try {
    const buttons = [...root.querySelectorAll("button")];
    const enable = buttons.find(button => button.textContent === "Enable");
    const start = buttons.find(button => button.textContent === "Start");
    assert(enable && start && start.disabled && calls.length === 0);
    await enable.run();
    assert.deepEqual(calls[0].request, { action: "prepare", provider: "auto" });
    assert(timers.includes(160000), "Administrator setup was given only the normal short request timeout");
    if (reason) {
      assert(start.disabled && root.querySelectorAll("select")[1].hidden);
      if (reason === "driver_not_installed") assert(root.textContent.includes("v4l2loopback kernel driver"));
      if (reason === "driver_authentication_cancelled") assert(root.textContent.includes("System authorization was cancelled."));
      assert.equal(calls.length, 1);
    } else {
      assert(!start.disabled);
      await start.run();
      assert.deepEqual(calls[1].request, { action: "start", action_token: "a".repeat(64), choice_token: "b".repeat(64), muted: false, front: false });
      assert(!JSON.stringify(calls).includes("/dev/"), "Renderer supplied a native path");
    }
  } finally { dom.window.close(); }
}

(async () => {
  for (const reason of ["driver_not_installed", "driver_authentication_cancelled", "driver_setup_failed", ""]) await scenario(reason);
  console.log("PASS: 4 actual Advanced webcam UI setup scenarios; no device/root/capture IO");
})().catch(error => { console.error(error); process.exitCode = 1; });
