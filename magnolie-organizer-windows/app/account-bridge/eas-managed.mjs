/* SPDX-License-Identifier: MPL-2.0
 * Setup metadata only. Never expose provider credentials to another extension.
 */
browser.runtime.onMessageExternal.addListener((message, sender) => {
  if (sender.id !== "magnolie-bridge@magnolie-organizer.org" || message?.protocol !== 1) return;
  if (message.op === "setup" && ["personal-ms", "office365"].includes(message.type)) {
    if (typeof message.email !== "string" || message.email.length > 254 || !message.email.includes("@") || /[\r\n]/.test(message.email)) return Promise.resolve({ ok: false });
    return browser.storage.local.set({ "magnolie.setupType": message.type, "magnolie.loginHint": message.email }).then(() => ({ ok: true }));
  }
});
