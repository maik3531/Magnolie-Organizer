"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
let managed = true, enumerations = 0;
const handles = ["0", "0x0", "0X0000", "", null, undefined, "0x1234", "3456", "malformed", 0];
const context = {
  ChromeUtils: { importESModule: () => ({ ExtensionCommon: { ExtensionAPI: class {} },
    XPCOMUtils: { defineLazyGlobalGetters() {} }, MailServices: {}, CardDAVDirectory: {}, cal: {}, CalDavGenericRequest: {} }) },
  Services: { prefs: { getBoolPref: () => managed }, appinfo: { processID: 42 }, env: { get: () => "" },
    wm: { getEnumerator() { enumerations++; return handles.map(nativeHandle => ({
      docShell: { treeOwner: { QueryInterface: () => ({ nativeHandle }) } }
    })); } } },
  PathUtils: { profileDir: "owned-empty-profile" }, Ci: { nsIBaseWindow: {} }
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../app/thunderbird/api.js"), "utf8"), context);
const request = new context.magnolie().getAPI().magnolie.request;
(async () => {
  const value = await request({ version: 1, id: "a".repeat(32), op: "environment" });
  assert.deepEqual(JSON.parse(JSON.stringify(value.mailWindows)), ["0x1234", "3456", "malformed", 0],
    "Absent native widgets must be omitted, while nonzero/malformed values must still reach the native ownership validator");
  assert.equal(value.pid, 42); assert.equal(value.managed, true);
  managed = false;
  const personal = await request({ version: 1, id: "b".repeat(32), op: "environment" });
  assert.deepEqual(JSON.parse(JSON.stringify(personal.mailWindows)), []);
  assert.equal(enumerations, 1, "An ordinary personal profile must not enumerate managed mail windows");
  console.log("THUNDERBIRD ENVIRONMENT PASS: absent headless widgets, retained native validation inputs, managed-profile scope");
})().catch(error => { console.error(error); process.exitCode = 1; });
