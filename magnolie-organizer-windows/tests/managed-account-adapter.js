"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

async function main() {
  let listener;
  const calls = [];
  const code = fs.readFileSync(path.join(__dirname, "../app/account-bridge/tbsync-managed.mjs"), "utf8");
  vm.runInNewContext(code.replace(/^import .*;\r?\n/gm, ""), {
    browser: { runtime: { onMessageExternal: { addListener(fn) { listener = fn; } } } },
    accounts: { list: async () => [{ provider: "eas", accountId: "a1", accountName: "Microsoft test",
      enabled: true, error: null, custom: { refreshToken: "NEVER-EXPORT-THIS", password: "NEVER-EXPORT-THIS" } }] },
    folders: { listForAccount: async () => [{ folderId: "f1", targetID: "book1", targetType: "contacts", displayName: "Contacts", selected: true,
      custom: { secret: "NEVER-EXPORT-THIS" } }] },
    isProviderConnected: id => id === "eas",
    ui: { invokeRpc: async (name, args) => { calls.push({ name, args }); return name === "addAccount" ? { accountId: "a1" } : null; } }
  });
  assert.equal(listener({ protocol: 1, op: "status" }, { id: "unrelated@example.invalid" }), undefined);
  assert.equal(listener({ protocol: 1, op: "deleteAccount" }, { id: "magnolie-bridge@magnolie-organizer.org" }), undefined);
  const sender = { id: "magnolie-bridge@magnolie-organizer.org" };
  const status = await listener({ protocol: 1, op: "status" }, sender);
  assert.equal(status.ready, true);
  assert.equal(status.accounts[0].folders[0].target, "book1");
  assert.ok(!JSON.stringify(status).includes("NEVER-EXPORT-THIS"));
  assert.ok(!JSON.stringify(status).includes("custom"));
  await listener({ protocol: 1, op: "login" }, sender);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls.map(call => call.name), ["addAccount", "setAccountEnabled", "setAutoSyncInterval"]);
  assert.equal(calls[0].args.providerId, "eas");
  assert.equal((await listener({ protocol: 1, op: "status" }, sender)).login.pending, false);
  console.log("Managed account adapter: caller scope, provider-owned sign-in and credential-free status passed.");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
