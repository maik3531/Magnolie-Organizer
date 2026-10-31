/* SPDX-License-Identifier: MPL-2.0
 * Magnolie's explicitly scoped control adapter for the bundled TbSync host.
 * Account credentials remain in the host/provider; public replies are projected.
 */
import * as accounts from "./accounts.mjs";
import * as folders from "./folders.mjs";
import * as ui from "./messaging-ui.mjs";
import { isProviderConnected } from "./router.mjs";

const caller = "magnolie-bridge@magnolie-organizer.org";
// TbSync indexes providers by their announced shortName, not their add-on ID.
const provider = "eas";
let login = { pending: false, error: false };
const sourceTickets = new Map();
let sourceBusy = false;
const sourceText = (value, maximum = 256) => typeof value === "string" && value.length > 0 && value.length <= maximum &&
  value === value.trim().normalize("NFC") && !/[\x00-\x1f\x7f\uD800-\uDFFF]/u.test(value);
async function sourceDigest(value) {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), byte => byte.toString(16).padStart(2, "0")).join("");
}
async function sourceFolder(accountId, folderId) {
  if (!sourceText(accountId) || !sourceText(folderId) || !isProviderConnected(provider)) throw new Error("source_folder_unavailable");
  const account = await accounts.get(accountId);
  if (!account || account.provider !== provider || account.enabled !== true || account.error) throw new Error("source_folder_unavailable");
  const configuration = account.custom || {};
  // Bind to provider-owned, non-secret account identity, never display labels,
  // access/refresh tokens or a local target ID that can change on re-selection.
  if (![configuration.user, configuration.server, configuration.servertype].every(value => sourceText(value, 2048)))
    throw new Error("source_folder_identity_unavailable");
  const matches = (await folders.listForAccount(accountId)).filter(row => row.folderId === folderId);
  if (matches.length !== 1 || !["contacts", "calendars"].includes(matches[0].targetType)) throw new Error("source_folder_unavailable");
  const row = matches[0];
  if (row.targetID != null && row.targetID !== "" && !sourceText(row.targetID, 1024)) throw new Error("source_folder_unavailable");
  if (row.custom?.serverID != null && !sourceText(row.custom.serverID, 2048)) throw new Error("source_folder_identity_unavailable");
  const identity = await sourceDigest([provider, accountId, configuration.servertype, configuration.server, configuration.user,
    folderId, row.targetType, row.custom?.serverID ?? null]);
  const selected = row.selected === true, target = row.targetID || null;
  return { protocol: 1, version: 1, account_id: accountId, folder_id: folderId, kind: row.targetType,
    source_identity: identity, revision: await sourceDigest([identity, selected, target]), selected, target_id: target,
    // This API confirms folder setup only. A materialized cache or empty queue
    // is NOT a successful EAS data synchronization or remote write receipt.
    provider_sync_confirmed: false };
}
async function sourceControl(message) {
  const apply = message.op === "source-folder-enable";
  const expected = ["protocol", "op", "accountId", "folderId", ...(apply ? ["token", "revision"] : [])];
  if (Object.keys(message).length !== expected.length || Object.keys(message).some(key => !expected.includes(key))) throw new Error("invalid_source_folder_request");
  if (login.pending || sourceBusy && message.op !== "source-folder-inspect") throw new Error("source_folder_busy");
  const now = Date.now();
  for (const [token, ticket] of sourceTickets) if (ticket.expires <= now) sourceTickets.delete(token);
  if (message.op === "source-folder-inspect") return { ...(await sourceFolder(message.accountId, message.folderId)), state: "current" };
  if (!apply) {
    if (sourceTickets.size >= 16) throw new Error("source_folder_busy");
    const current = await sourceFolder(message.accountId, message.folderId), token = crypto.randomUUID();
    if (sourceTickets.size >= 16 || sourceBusy || login.pending) throw new Error("source_folder_busy");
    sourceTickets.set(token, { current, expires: Date.now() + 25000 });
    return { ...current, state: "prepared", token };
  }
  const ticket = sourceTickets.get(message.token);
  sourceTickets.delete(message.token); // One use, including rejected/uncertain attempts.
  if (!ticket || ticket.expires <= now || ticket.current.account_id !== message.accountId || ticket.current.folder_id !== message.folderId ||
      ticket.current.revision !== message.revision) throw new Error("source_folder_preparation_changed");
  sourceBusy = true;
  try {
    const current = await sourceFolder(message.accountId, message.folderId);
    if (current.revision !== ticket.current.revision || ticket.expires <= Date.now()) throw new Error("source_folder_preparation_changed");
    // Lost-result recovery inspects first. Never recreate an already selected
    // target, never deselect/delete one, and retain upstream's normal guards.
    if (!current.selected) await ui.invokeRpc("setFolderSelected", { accountId: message.accountId, folderId: message.folderId, selected: true });
    const saved = await sourceFolder(message.accountId, message.folderId);
    if (saved.source_identity !== current.source_identity || !saved.selected || !saved.target_id ||
        current.selected && current.target_id !== saved.target_id) throw new Error("source_folder_setup_unconfirmed");
    return { ...saved, state: "selected" };
  } finally { sourceBusy = false; }
}

async function status() {
  const visible = [];
  for (const account of await accounts.list()) {
    if (account.provider !== provider) continue;
    const rows = await folders.listForAccount(account.accountId);
    visible.push({ id: account.accountId, name: account.accountName,
      enabled: account.enabled === true, error: !!account.error,
      lastSync: account.lastSyncTime || 0,
      folders: rows.map(row => ({ id: row.folderId, name: row.displayName,
        type: row.targetType, selected: row.selected === true,
        target: row.targetID || "", error: !!row.error, lastSync: row.lastSyncTime || 0 })) });
  }
  // EAS folders may exist in TbSync, but this control adapter does not expose
  // their task data to Magnolie's CalDAV transport.
  return { protocol: 1, ready: isProviderConnected(provider), login: { ...login },
    tasks: { available: false, transport: "eas" }, accounts: visible };
}

browser.runtime.onMessageExternal.addListener((message, sender) => {
  if (sender.id !== caller || message?.protocol !== 1) return;
  if (["source-folder-inspect", "source-folder-prepare", "source-folder-enable"].includes(message.op)) return sourceControl(message);
  if (message.op === "ping") return Promise.resolve({ protocol: 1, ready: isProviderConnected(provider) });
  if (message.op === "status") return status();
  if (["rename", "remove", "edit"].includes(message.op)) return (async () => {
    if (login.pending || sourceBusy) throw new Error("busy");
    const account = await accounts.get(message.accountId);
    if (!account || account.provider !== provider) throw new Error("unknown account");
    if (message.op === "rename") {
      if (typeof message.name !== "string" || !message.name.trim() || message.name.length > 254 || /[\r\n]/.test(message.name)) throw new Error("name");
      await accounts.update(account.accountId, { accountName: message.name.trim() });
      ui.broadcast({ type: "accounts-changed" });
    } else if (message.op === "remove") {
      await ui.invokeRpc("deleteAccount", { accountId: account.accountId });
    } else {
      login = { pending: true, error: false };
      ui.invokeRpc("editAccount", { accountId: account.accountId })
        .catch(error => { login.error = error?.code !== "E:CANCELLED"; })
        .finally(() => { login.pending = false; });
    }
    return { ok: true };
  })();
  if (message.op !== "login") return;
  if (sourceBusy) return Promise.reject(new Error("source_folder_busy"));
  if (!login.pending) {
    login = { pending: true, error: false };
    // Invoke the same controller as the account-manager button. The provider
    // owns its sign-in popup and passes its own credentials to TbSync internally.
    ui.invokeRpc("addAccount", { providerId: provider }).then(async result => {
      if (!result?.accountId) return;
      await ui.invokeRpc("setAccountEnabled", { accountId: result.accountId, enabled: true });
      await ui.invokeRpc("setAutoSyncInterval", { accountId: result.accountId, minutes: 10 });
    }).catch(error => {
      login.error = error?.code !== "E:CANCELLED";
    }).finally(() => { login.pending = false; });
  }
  return Promise.resolve({ opened: true });
});
