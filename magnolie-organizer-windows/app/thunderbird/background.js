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
        if (message.op === "login" && environment.managed) {
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
            const status = await accountControl("tbsync@jobisoft.de", { protocol: 1, op: "ping" });
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
