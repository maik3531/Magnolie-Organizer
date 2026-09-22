"use strict";

function connect() {
  const port = browser.runtime.connectNative("org.magnolie.thunderbird");
  let queue = Promise.resolve();
  port.onMessage.addListener(message => {
    queue = queue.then(async () => {
      let response;
      try {
        response = { ...(await browser.magnolie.request(message)), ok: true };
      } catch (_) {
        // Provider exceptions can contain contact data or account URLs.
        response = { ok: false };
      }
      port.postMessage({ ...response, version: 1, id: message.id });
    }).catch(() => port.disconnect());
  });
  port.onDisconnect.addListener(() => {
    void port.error;
    setTimeout(connect, 30000);
  });
}
connect();
