"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
let managed = true, enumerations = 0, retained = 0, released = 0;
const handles = ["0", "0x0", "0X0000", "", null, undefined, "0x1234", "3456", "malformed", 0];
const context = {
  ChromeUtils: { importESModule: () => ({ ExtensionCommon: { ExtensionAPI: class {} },
    XPCOMUtils: { defineLazyGlobalGetters() {} }, MailServices: {}, CardDAVDirectory: {}, cal: {}, CalDavGenericRequest: {} }) },
  Services: { prefs: { getBoolPref: () => managed }, appinfo: { processID: 42 }, env: { get: () => "" },
    startup: { enterLastWindowClosingSurvivalArea() { retained++; }, exitLastWindowClosingSurvivalArea() { released++; } },
    wm: { getEnumerator() { enumerations++; return handles.map(nativeHandle => ({
      docShell: { treeOwner: { QueryInterface: () => ({ nativeHandle }) } }
    })); } } },
  PathUtils: { profileDir: "owned-empty-profile" }, Ci: { nsIBaseWindow: {} }
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../app/thunderbird/api.js"), "utf8"), context);
const extension = new context.magnolie();
const request = extension.getAPI().magnolie.request;
(async () => {
  assert.equal(retained, 1, "A silent managed helper must retain its native service lifetime without a mail window");
  extension.getAPI();
  assert.equal(retained, 1, "Repeated API setup must not retain another lifetime lease");
  const value = await request({ version: 1, id: "a".repeat(32), op: "environment" });
  assert.deepEqual(JSON.parse(JSON.stringify(value.mailWindows)), ["0x1234", "3456", "malformed", 0],
    "Absent native widgets must be omitted, while nonzero/malformed values must still reach the native ownership validator");
  assert.equal(value.pid, 42); assert.equal(value.managed, true);
  managed = false;
  const personal = await request({ version: 1, id: "b".repeat(32), op: "environment" });
  assert.deepEqual(JSON.parse(JSON.stringify(personal.mailWindows)), []);
  assert.equal(enumerations, 1, "An ordinary personal profile must not enumerate managed mail windows");
  const personalExtension = new context.magnolie(); personalExtension.getAPI(); personalExtension.onShutdown();
  assert.equal(retained, 1); assert.equal(released, 0, "A personal profile must not alter the managed lifetime");
  extension.onShutdown(); extension.onShutdown();
  assert.equal(released, 1, "The managed lifetime must be released exactly once on shutdown");
  const replies = [], nativeOperations = [];
  let listener, providerReady = false;
  const port = { onMessage: { addListener(value) { listener = value; } }, onDisconnect: { addListener() {} },
    postMessage(value) { replies.push(value); }, disconnect() { throw new Error("Unexpected disconnect"); } };
  const background = {
    browser: {
      magnolie: { async request(message) {
        nativeOperations.push(message.op);
        if (message.op === "environment") return { managed: true, pid: 42, profile: "owned-profile", mailWindows: ["0x1234"] };
        if (message.op === "status") return { google: { accounts: ["cached@example.test"], pending: false } };
        throw new Error("A read attempted an interactive operation: " + message.op);
      } },
      runtime: { connectNative() { return port; }, async sendMessage(id, message) {
        assert.equal(id, "tbsync@jobisoft.de");
        if (message.op === "ping" && !providerReady) throw new Error("Provider has not started");
        assert.ok(["ping", "status"].includes(message.op), "Reading settings invoked provider sign-in");
        return { protocol: 1, ready: providerReady, accounts: [], login: { pending: false } };
      } }
    },
    setTimeout: () => 0, clearTimeout() {}
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../app/thunderbird/background.js"), "utf8"), background);
  const tick = () => new Promise(resolve => setImmediate(resolve));
  await tick(); assert.equal(typeof listener, "function");
  listener({ version: 1, id: "c".repeat(32), op: "environment" }); await tick();
  assert.equal(replies[0].ok, true, "Provider failure must not hide the helper identity/window handles from the native owner");
  assert.equal(replies[0].ready, false); assert.equal(replies[0].providerReady, false);
  assert.deepEqual(JSON.parse(JSON.stringify(replies[0].mailWindows)), ["0x1234"]);
  providerReady = true;
  listener({ version: 1, id: "d".repeat(32), op: "environment" }); await tick();
  assert.equal(replies[1].ok, true); assert.equal(replies[1].ready, true);
  listener({ version: 1, id: "e".repeat(32), op: "status" }); await tick();
  assert.equal(replies[2].ok, true);
  assert.deepEqual(JSON.parse(JSON.stringify(replies[2].google.accounts)), ["cached@example.test"]);
  assert.ok(nativeOperations.every(op => ["environment", "status"].includes(op)), "A stored account read opened sign-in");
  console.log("THUNDERBIRD ENVIRONMENT PASS: absent headless widgets, retained native validation inputs, managed-profile scope");
})().catch(error => { console.error(error); process.exitCode = 1; });
