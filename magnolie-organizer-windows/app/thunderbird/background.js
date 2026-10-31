"use strict";

async function accountControl(id, message) {
  let timer;
  try {
    return await Promise.race([browser.runtime.sendMessage(id, message, {}),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Account control timed out")), 10000); })]);
  } finally { clearTimeout(timer); }
}

async function connect() {
  const environment = await browser.magnolie.request({ version: 1, id: "0".repeat(32), op: "environment" });
  const port = browser.runtime.connectNative(environment.managed ? "org.magnolie.accounts" : "org.magnolie.thunderbird");
  const trace = async phase => {
    if (environment.probe) try {
      await browser.magnolie.request({ version: 1, id: "0".repeat(32), op: "probe-phase", phase });
    } catch (_) { /* Diagnostic output must never interrupt the protocol. */ }
  };
  let queue = Promise.resolve();
  port.onMessage.addListener(message => {
    queue = queue.then(async () => {
      await trace("received");
      let response;
      try {
        if (["eas-source-list", "eas-source-inspect", "eas-source-prepare", "eas-source-enable"].includes(message.op) && environment.managed) {
          const list = message.op === "eas-source-list", apply = message.op === "eas-source-enable";
          const allowed = ["version", "id", "op", ...(list ? [] : ["account_id", "folder_id"]), ...(apply ? ["token", "revision"] : [])];
          if (message.version !== 1 || !/^[a-f0-9]{32}$/.test(message.id || "") || Object.keys(message).length !== allowed.length ||
              Object.keys(message).some(key => !allowed.includes(key))) throw new Error("protocol");
          const scope = await browser.magnolie.request({ version: 1, id: message.id, op: "managed-source-scope" });
          if (!/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(scope.profile_id || "")) throw new Error("scope");
          response = await accountControl("tbsync@jobisoft.de", { protocol: 1,
            op: list ? "source-folder-list" : message.op.replace("eas-source-", "source-folder-"),
            ...(list ? {} : { accountId: message.account_id, folderId: message.folder_id }),
            ...(apply ? { token: message.token, revision: message.revision } : {}) });
          if (response?.protocol !== 1 || response?.version !== 1 ||
              list && (response.complete !== true || !Array.isArray(response.folders) || response.folders.length > 256) ||
              !list && (response.account_id !== message.account_id || response.folder_id !== message.folder_id)) throw new Error("source");
          const currentScope = await browser.magnolie.request({ version: 1, id: message.id, op: "managed-source-scope" });
          if (currentScope.profile_id !== scope.profile_id) throw new Error("scope");
          response = { ...response, profile_id: scope.profile_id };
        } else if (message.op === "manage-account" && environment.managed) {
          if (!["rename", "remove", "edit"].includes(message.action)) throw new Error("action");
          if (message.provider === "microsoft") {
            response = await accountControl("tbsync@jobisoft.de", { protocol: 1, op: message.action,
              accountId: message.accountId, name: message.name });
            if (!response?.ok) throw new Error("Account change failed");
          } else if (message.provider === "google") {
            response = await browser.magnolie.request(message);
          } else throw new Error("provider");
        } else if (message.op === "login" && environment.managed) {
          const google = await browser.magnolie.request({ ...message, op: "status" });
          const microsoft = await accountControl("tbsync@jobisoft.de", { protocol: 1, op: "status" });
          if (google.google.pending || microsoft?.login?.pending) throw new Error("Sign-in is already running");
          if (!microsoft?.ready) throw new Error("Account provider is not ready");
          if (message.provider === "google") {
            response = await browser.magnolie.request({ ...message, op: "login-google" });
          } else {
            if (!["personal-ms", "office365"].includes(message.provider)) throw new Error("provider");
            const setup = await accountControl("eas4tbsync@jobisoft.de", { protocol: 1, op: "setup", type: message.provider, email: message.email });
            if (!setup?.ok) throw new Error("EAS helper is unavailable");
            response = await accountControl("tbsync@jobisoft.de", { protocol: 1, op: "login" });
            if (!response?.opened) throw new Error("Account helper is unavailable");
          }
        } else {
          response = await browser.magnolie.request(message);
          await trace("native-api-done");
          if (message.op === "environment" && environment.managed) {
            await trace("tb-status-start");
            let status;
            try { status = await accountControl("tbsync@jobisoft.de", { protocol: 1, op: "ping" }); }
            catch (_) { status = null; }
            await trace("tb-status-done");
            response.ready = status?.protocol === 1 && status.ready === true;
            response.providerReady = status?.protocol === 1 && status.ready === true;
          }
          if (message.op === "status" && environment.managed) {
            response.microsoft = await accountControl("tbsync@jobisoft.de", { protocol: 1, op: "status" });
          }
        }
        response = { ...response, ok: true };
      } catch (_) {
        // Provider exceptions can contain contact data or account URLs.
        response = { ok: false };
      }
      port.postMessage({ ...response, version: 1, id: message.id });
      await trace("reply-sent");
    }).catch(() => port.disconnect());
  });
  port.onDisconnect.addListener(() => {
    void port.error;
    setTimeout(connect, 30000);
  });
}
connect().catch(() => setTimeout(connect, 30000));
