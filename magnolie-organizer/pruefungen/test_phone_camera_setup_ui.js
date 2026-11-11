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

async function scenario(reason, installMode = "", initiallyConnected = true) {
  const dom = new JSDOM("<!doctype html><body></body>");
  const document = dom.window.document, calls = [], timers = [], pending = new Map(), prompts = [], callbacks = [];
  let connected = initiallyConnected;
  const el = (tag, css, text) => {
    const node = document.createElement(tag);
    if (css) node.className = css;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const knopf = (text, css, action) => {
    const button = el("button", css, text); button.run = action; return button;
  };
  const timer = (fn, ms) => { timers.push(ms); if (ms === 2000) callbacks.push(fn); return timers.length; };
  const bridge = { sende(message) {
    calls.push(message);
    const waiter = pending.get(message.requestId);
    if (waiter) {
      if (message.request?.action === "install_driver") assert(document.body.textContent.includes("Please wait …"));
      const ready = { included: true, enabled: false, phase: "off", reason: "", lease: "", action: "a".repeat(64),
        choices: [{ token: "b".repeat(64), phone: "Notes", device: "Controlled virtual camera" }] };
      const value = message.request?.action === "install_driver"
        ? installMode === "failed" || installMode === "pending"
          ? { ...ready, action: "", choices: [], reason: installMode === "failed" ? "driver_installation_failed" : "driver_installation_pending" }
          : ready
        : message.request?.action === "prepare"
        ? { included: true, enabled: false, phase: "off", reason, lease: "", action: reason ? "" : "a".repeat(64),
          ...(installMode ? { install_token: "d".repeat(64) } : {}),
          choices: reason ? [] : [{ token: "b".repeat(64), phone: "Notes", device: "Controlled virtual camera" }] }
        : message.request?.action === "start"
          ? { included: true, enabled: true, phase: "starting", lease: "c".repeat(64) }
          : { included: true, enabled: false, phase: "off", reason: "", lease: "" };
      pending.delete(message.requestId); waiter.resolve({ ok: true, webcam: { ...value, visible: connected } });
    }
    return true;
  }};
  const build = new Function("document", "el", "knopf", "_", "crypto", "setTimeout", "clearTimeout",
    "kdeMedienAnfragen", "Bruecke", "gesperrt", "frage", source.slice(begin, end) + "\nreturn baueTelefonWebcam;")(
      document, el, knopf, text => text, crypto, timer, () => {}, pending, bridge, false, async (...args) => {
        prompts.push(args);
        assert.equal(calls.filter(call => call.request?.action === "install_driver").length, 0, "Install ran before consent");
        assert(args[0].includes("v4l2loopback") && args[1] === "Install and set up" && args[2] === "Cancel");
        if (installMode === "provider") root.querySelector("select").dispatchEvent(new dom.window.Event("change"));
        if (installMode === "closed") root.remove();
        return installMode !== "no";
      });
  const root = el("details");
  Object.defineProperty(root, "open", { value: true });
  document.body.append(root); build(root);
  try {
    const buttons = [...root.querySelectorAll("button")];
    const enable = buttons.find(button => button.textContent === "Enable");
    const start = buttons.find(button => button.textContent === "Start");
    assert(enable && start && start.disabled);
    assert(root.querySelector("#telefon-webcam").hidden, "Visible before native live status");
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    assert.equal(calls[0].cmd, "telefon_webcam_stand");
    if (!initiallyConnected) {
      assert(root.querySelector("#telefon-webcam").hidden, "Offline paired/absent Notes must stay hidden");
      await enable.run(); await start.run();
      assert.equal(calls.length, 1, "Offline card dispatched setup/capture");
      connected = true;
      await callbacks.at(-1)();
      assert(!root.querySelector("#telefon-webcam").hidden, "Live connection did not reveal card");
      return;
    }
    assert(!root.querySelector("#telefon-webcam").hidden);
    calls.length = 0;
    await enable.run();
    assert.deepEqual(calls[0].request, { action: "prepare", provider: "auto" });
    assert(timers.includes(160000), "Administrator setup was given only the normal short request timeout");
    if (installMode) {
      assert.equal(prompts.length, 1);
      const installing = calls.filter(call => call.request?.action === "install_driver");
      assert(!calls.some(call => call.request?.action === "start"), "Installation started camera capture");
      if (["no", "provider", "closed"].includes(installMode)) {
        assert.equal(installing.length, 0);
        assert(calls.some(call => call.request?.action === "cancel" && call.request.action_token === "d".repeat(64)));
      } else {
        assert.deepEqual(installing.map(call => call.request), [{ action: "install_driver", install_token: "d".repeat(64) }]);
        assert(timers.includes(800000));
        if (installMode === "failed") assert(root.textContent.includes("Please install the v4l2loopback driver"));
        if (installMode === "pending") assert(enable.disabled && root.textContent.includes("may still be running"));
        if (installMode === "yes") assert(!start.disabled);
      }
      return;
    }
    if (reason) {
      assert(start.disabled && root.querySelectorAll("select")[1].hidden);
      if (reason === "driver_not_installed") assert(root.textContent.includes("Please install the v4l2loopback driver"));
      if (reason === "driver_authentication_cancelled") assert(root.textContent.includes("System authorization was cancelled."));
      assert.equal(calls.length, 1);
    } else {
      assert(!start.disabled);
      await start.run();
      assert.deepEqual(calls[1].request, { action: "start", action_token: "a".repeat(64), choice_token: "b".repeat(64), muted: false, front: false });
      assert(!JSON.stringify(calls).includes("/dev/"), "Renderer supplied a native path");
      connected = false;
      await callbacks.at(-1)();
      assert(root.querySelector("#telefon-webcam").hidden, "Disconnected Notes card remains visible");
      const count = calls.length;
      await enable.run(); await start.run();
      assert.equal(calls.length, count, "Hidden stale controls dispatched capture/setup");
    }
  } finally { dom.window.close(); }
}

(async () => {
  for (const reason of ["driver_not_installed", "driver_authentication_cancelled", "driver_setup_failed", ""]) await scenario(reason);
  for (const mode of ["yes", "no", "provider", "closed", "failed", "pending"]) await scenario("driver_not_installed", mode);
  await scenario("", "", false);
  console.log("PASS: 11 actual Advanced webcam UI scenarios including live Notes visibility/disconnect; no package/device/root/capture IO");
})().catch(error => { console.error(error); process.exitCode = 1; });
