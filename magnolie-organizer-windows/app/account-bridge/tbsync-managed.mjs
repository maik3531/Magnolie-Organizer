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
  return { protocol: 1, ready: isProviderConnected(provider), login: { ...login }, accounts: visible };
}

browser.runtime.onMessageExternal.addListener((message, sender) => {
  if (sender.id !== caller || message?.protocol !== 1) return;
  if (message.op === "ping") return Promise.resolve({ protocol: 1, ready: isProviderConnected(provider) });
  if (message.op === "status") return status();
  if (message.op !== "login") return;
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
