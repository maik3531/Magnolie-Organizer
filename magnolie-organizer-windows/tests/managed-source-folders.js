"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const { webcrypto } = require("node:crypto");
const sender = { id: "magnolie-bridge@magnolie-organizer.org" };
function boot() {
  const account = { provider: "eas", accountId: "a1", enabled: true, accountName: "Synthetic account", custom: {
    user: "synthetic@example.invalid", server: "https://outlook.office365.com/Microsoft-Server-ActiveSync", servertype: "office365",
    refreshToken: "NEVER-EXPORT-TOKEN", password: "NEVER-EXPORT-PASSWORD" } };
  const folder = { folderId: "f1", targetType: "contacts", displayName: "Contacts", selected: false, targetID: null,
    custom: { serverID: "native-server-folder", secret: "NEVER-EXPORT-FOLDER-SECRET" } };
  const state = { account, folder, rows: [folder], connected: true, now: 1000, calls: [], beforeApply: null, beforeAccountRead: null };
  let listener;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../app/account-bridge/tbsync-managed.mjs"), "utf8").replace(/^import .*;\r?\n/gm, ""), {
    crypto: webcrypto, TextEncoder, Date: { now: () => state.now },
    browser: { runtime: { onMessageExternal: { addListener(fn) { listener = fn; } } } },
    accounts: { get: async id => { if (state.beforeAccountRead) await state.beforeAccountRead(); return state.account?.accountId === id ? state.account : null; },
      list: async () => state.account ? [state.account] : [] },
    folders: { listForAccount: async id => id === "a1" ? state.rows : [] },
    isProviderConnected: id => id === "eas" && state.connected,
    ui: { broadcast() {}, invokeRpc: async (op, args) => {
      state.calls.push({ op, args: JSON.parse(JSON.stringify(args)) });
      if (state.beforeApply) await state.beforeApply();
      assert.equal(op, "setFolderSelected"); assert.equal(args.selected, true);
      state.folder.selected = true; state.folder.targetID = "native-target";
    } }
  });
  state.call = (op, extra = {}, caller = sender) => listener({ protocol: 1, op, accountId: "a1", folderId: "f1", ...extra }, caller);
  state.prepare = () => state.call("source-folder-prepare");
  state.apply = prepared => state.call("source-folder-enable", { token: prepared.token, revision: prepared.revision });
  return state;
}
async function success(kind) {
  const b = boot(); b.folder.targetType = kind;
  const before = await b.call("source-folder-inspect");
  assert.equal(before.state, "current"); assert.equal(before.selected, false); assert.equal(before.target_id, null);
  assert.ok(!JSON.stringify(before).includes("NEVER-EXPORT"));
  assert.ok(!JSON.stringify(before).includes("synthetic@example.invalid"));
  assert.ok(!JSON.stringify(before).includes("office365.com"));
  const prepared = await b.prepare(); assert.match(prepared.source_identity, /^[a-f0-9]{64}$/);
  assert.match(prepared.revision, /^[a-f0-9]{64}$/); assert.equal(b.calls.length, 0);
  // Labels, sync timestamps and refreshed credentials are not source identity.
  b.account.accountName = "Changed label"; b.account.lastSyncTime = 2000;
  b.account.custom.refreshToken = "ANOTHER-SECRET";
  const saved = await b.apply(prepared);
  assert.equal(saved.state, "selected"); assert.equal(saved.selected, true); assert.equal(saved.target_id, "native-target");
  assert.equal(saved.provider_sync_confirmed, false, "Folder materialization was misrepresented as remote data synchronization");
  assert.equal(saved.source_identity, before.source_identity); assert.notEqual(saved.revision, before.revision);
  assert.equal(b.calls.length, 1); await assert.rejects(b.apply(prepared));
  const retry = await b.prepare(); await b.apply(retry);
  assert.equal(b.calls.length, 1, "An already selected target was recreated");
}
async function invalid(mode) {
  const b = boot(), prepared = await b.prepare();
  if (mode === "user") b.account.custom.user = "another@example.invalid";
  if (mode === "server") b.account.custom.server = "https://another.example.invalid/EAS";
  if (mode === "provider") b.account.provider = "foreign";
  if (mode === "account") b.account = null;
  if (mode === "disabled") b.account.enabled = false;
  if (mode === "error") b.account.error = true;
  if (mode === "offline") b.connected = false;
  if (mode === "kind") b.folder.targetType = "tasks";
  if (mode === "server-folder") b.folder.custom.serverID = "replacement-folder";
  if (mode === "missing") b.rows = [];
  if (mode === "ambiguous") b.rows.push({ ...b.folder });
  if (mode === "target") b.folder.targetID = "other-target";
  if (mode === "selection") b.folder.selected = true;
  if (mode === "expired") b.now += 25000;
  if (mode === "revision") prepared.revision = "f".repeat(64);
  await assert.rejects(b.apply(prepared)); assert.equal(b.calls.length, 0, mode);
  // A failed authorization cannot leave a replayable write ticket.
  await assert.rejects(b.apply(prepared));
}
async function recovery() {
  const b = boot(), prepared = await b.prepare();
  b.beforeApply = async () => { b.folder.selected = true; b.folder.targetID = "native-target"; throw new Error("lost-result"); };
  await assert.rejects(b.apply(prepared)); assert.equal(b.calls.length, 1);
  await assert.rejects(b.apply(prepared));
  const observed = await b.call("source-folder-inspect"); assert.equal(observed.selected, true);
  assert.equal(observed.source_identity, prepared.source_identity); assert.equal(observed.provider_sync_confirmed, false);
  b.beforeApply = null; await b.apply(await b.prepare()); assert.equal(b.calls.length, 1);
}
async function boundedAndScoped() {
  const b = boot();
  assert.equal(b.call("source-folder-prepare", {}, { id: "foreign@example.invalid" }), undefined);
  for (const extra of [{ accountId: "" }, { folderId: "f\u0000" }, { selected: false }, { password: "forbidden" }])
    await assert.rejects(b.call("source-folder-prepare", extra));
  for (let n = 0; n < 16; n++) await b.prepare();
  await assert.rejects(b.prepare()); b.now += 25001; await b.prepare();
  assert.equal(b.calls.length, 0);
  const bad = boot(); delete bad.account.custom.user; await assert.rejects(bad.prepare());
  const calendar = boot(); calendar.folder.targetType = "tasks"; await assert.rejects(calendar.prepare());
}
async function lateFailures() {
  const expired = boot(), ticket = await expired.prepare();
  expired.beforeAccountRead = async () => { expired.now += 25001; };
  await assert.rejects(expired.apply(ticket)); assert.equal(expired.calls.length, 0, "Ticket expired during preflight but still mutated the provider");
  const rebound = boot(), prepared = await rebound.prepare();
  rebound.beforeApply = async () => { rebound.account.custom.user = "rebound@example.invalid"; };
  await assert.rejects(rebound.apply(prepared)); assert.equal(rebound.calls.length, 1);
  assert.equal(rebound.folder.selected, true, "An uncertain setup was blindly rolled back");
  await assert.rejects(rebound.apply(prepared));
}
async function busy() {
  const b = boot(); let release, started;
  const waiting = new Promise(resolve => { release = resolve; }), entered = new Promise(resolve => { started = resolve; });
  b.beforeApply = async () => { started(); await waiting; };
  const p = await b.prepare(), apply = b.apply(p); await entered;
  await assert.rejects(b.prepare());
  await assert.rejects(b.call("remove"));
  await assert.rejects(b.call("login"));
  const observed = await b.call("source-folder-inspect"); assert.equal(observed.state, "current");
  release(); await apply; assert.equal(b.calls.length, 1);
}
(async () => {
  for (const kind of ["contacts", "calendars"]) await success(kind);
  for (const mode of ["user", "server", "provider", "account", "disabled", "error", "offline", "kind", "server-folder", "missing", "ambiguous", "target", "selection", "expired", "revision"])
    await invalid(mode);
  await recovery(); await boundedAndScoped(); await lateFailures(); await busy();
  console.log("PASS managed source folders: scoped prepare/enable/inspect, native identity, one-use/TTL, lost-result recovery, no target recreation and no false provider-sync receipt");
})().catch(error => { console.error(error); process.exitCode = 1; });
