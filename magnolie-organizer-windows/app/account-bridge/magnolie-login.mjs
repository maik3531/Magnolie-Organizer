/* SPDX-License-Identifier: MPL-2.0
 * Provider-owned setup page, using EAS-4-TbSync's unchanged sign-in handlers.
 * The flow corresponds to its dialogs/setup/setup.mjs; no token leaves this
 * provider except through its existing TbSync setup-completion protocol.
 */
const setupToken = new URLSearchParams(location.search).get("setupToken");
try {
  if (!setupToken) throw new Error("Missing provider setup session");
  const stored = await browser.storage.local.get(["magnolie.setupType", "magnolie.loginHint"]);
  const type = stored["magnolie.setupType"];
  const email = stored["magnolie.loginHint"];
  if (!["personal-ms", "office365"].includes(type)) throw new Error("Invalid account type");
  const auth = await browser.runtime.sendMessage({ type: "eas.startOAuth", servertype: type, loginHint: email });
  if (!auth?.ok) { const error = new Error("Sign-in was not completed"); error.code = auth?.code; throw error; }
  const reply = await browser.runtime.sendMessage({ type: "eas.createAccount", servertype: type,
    label: auth.result.authenticatedUserEmail || email, refreshToken: auth.result.refreshToken,
    authenticatedUserEmail: auth.result.authenticatedUserEmail, loginHint: email });
  if (!reply?.ok) throw new Error("Account setup was not completed");
  await browser.runtime.sendMessage({ type: "tbsync-setup-completed", setupToken,
    accountName: reply.result.accountName, icon: reply.result.icon ?? null,
    initialFolders: reply.result.initialFolders, custom: reply.result.custom });
  window.close();
} catch (error) {
  if (error.code === "E:CANCELLED") window.close();
  else document.body.textContent = browser.i18n.getMessage("setup.oauth.error.signInFailed") || "Sign-in failed";
}
