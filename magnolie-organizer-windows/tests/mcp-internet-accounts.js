"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP Internet accounts timed out"); process.exit(1); }, 15000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      let sequence = 0, onNative;
      const status = { ready: true, google_pending: false, microsoft_pending: false, error_present: false, google_tasks_available: false, microsoft_tasks_available: true,
        refreshToken: "owned-private-helper-token", accounts: Array.from({ length: 129 }, (_, i) => ({ provider: i % 2 ? "microsoft" : "google", id: "owned-" + i, name: "Account " + i,
          enabled: true, error_present: false, accessToken: "owned-private-account-token" })) };
      const revision = "e".repeat(64);
      const reply = (message, extra = {}) => b.w.App.internetKontenMcp({ requestId: message.requestId, ok: true, action: message.action, revision, status,
        accepted: message.action !== "read", verified: ["rename", "remove"].includes(message.action), ...extra });
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern") queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true }));
        if (message.cmd === "baum_briefkasten_status") queueMicrotask(() => b.w.App.baumBriefkastenStatus({ requestId: message.requestId || "", kontoArt: "nextcloud", davAktiv: false,
          briefkastenAktiv: false, url: "https://owned.example.test", benutzer: "owned-reader", kennwortVorhanden: false, zustand: "inaktiv", fehler: "", fehlerCode: "none" }));
        if (message.cmd === "internet_konten_mcp") { if (onNative) onNative(message); else reply(message); }
      };
      async function rpc(method, params, id) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method,
          ...(!method.startsWith("notifications/") ? { id: id ?? sequence } : {}), ...(params === undefined ? {} : { params }) } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
      }
      const tool = async (name, args, id) => (await rpc("tools/call", { name, arguments: args }, id)).result;
      const read = (args = {}, id) => tool("organizer_internet_accounts_read", args, id);
      const change = (args = {}, id) => tool("organizer_internet_account_action", { action: "rename", provider: "google", account_id: "owned-0", name: "Renamed", expected_revision: revision, ...args }, id);
      const ok = result => { assert.equal(result?.isError, false, JSON.stringify(result)); return result.structuredContent; };
      const fail = (result, code) => { assert.equal(result?.isError, true, JSON.stringify(result)); assert.equal(result.structuredContent.code, code); };
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-managed-probe", version: "1" } }); await rpc("notifications/initialized", {});
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
      const page = ok(await read()); assert.equal(page.entries.length, 100); assert.equal(page.total, 129); assert.equal(page.next_offset, 100);
      assert.equal(page.authentication_verified, false); assert.equal(page.operation_accepted, false); assert.ok(!JSON.stringify(page).includes("owned-private"));
      assert.equal(ok(await read({ offset: 125, limit: 2 })).next_offset, 127);
      let held, completed = false;
      const started = new Promise(resolve => { onNative = message => { held = message; resolve(); }; });
      const changing = change().then(result => { completed = true; return result; }); await started;
      assert.equal(held.expectedRevision, revision); assert.equal(held.account, "owned-0"); assert.equal(held.name, "Renamed");
      reply({ ...held, requestId: "wrong-account-request" }); await tick(); assert.equal(completed, false);
      reply(held); onNative = null; assert.equal(ok(await changing).change_verified, true);
      assert.equal(ok(await change({ action: "remove" })).change_verified, true);
      assert.equal(ok(await change({ action: "edit" })).change_verified, false);
      assert.equal(ok(await change({ action: "sign_in", provider: "office365", email: "owned@example.test" })).change_verified, false);
      for (const bad of [{ verified: false }, { accepted: false }, { revision: "invalid" }, { status: { ...status, google_tasks_available: "owned-private" } },
        { status: { ...status, accounts: [{ ...status.accounts[0], enabled: "invalid" }] } }]) {
        onNative = message => reply(message, bad); fail(await change(), "invalid_result");
      }
      for (const code of ["conflict", "not_found", "native_busy", "native_timeout", "locked_or_cancelled", "unsupported_feature", "profile_locked"]) {
        onNative = message => reply(message, { ok: false, code }); fail(await change(), code === "profile_locked" ? "locked_or_cancelled" : code);
      }
      onNative = null;
      const invalid = await rpc("tools/call", { name: "organizer_internet_account_action", arguments: { action: "sign_in", expected_revision: revision, provider: "microsoft", email: "owned@example.test" } });
      assert.equal(invalid.error.code, -32602);
      const readStarted = new Promise(resolve => { onNative = message => { held = message; resolve(); }; });
      const cancelled = read({}, 9000); await readStarted;
      b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-sync").click(); await tick();
      const draft = b.w.document.querySelector("#briefkasten-url"), secret = b.w.document.querySelector("#briefkasten-kennwort");
      draft.value = "https://owned-draft.example.test"; secret.value = "owned-unsaved-secret";
      fail(await change(), "dialog_busy");
      await rpc("notifications/cancelled", { requestId: 9000 }); fail(await cancelled, "cancelled");
      const sourceReads = b.messages.filter(message => message.cmd === "eds_status").length, toast = b.w.document.querySelector("#zettel").textContent;
      reply(held); await tick();
      assert.equal(draft.value, "https://owned-draft.example.test"); assert.equal(secret.value, "owned-unsaved-secret");
      assert.equal(b.w.document.querySelector("#zettel").textContent, toast); assert.equal(b.messages.filter(message => message.cmd === "eds_status").length, sourceReads);
      const section = b.w.document.querySelector("#internet-konten");
      if (section) {
        const reads = b.messages.filter(message => message.cmd === "internet_konten_status").length;
        const starts = b.messages.filter(message => message.cmd === "internet_konto_anmelden").length;
        b.w.App.internetKontoAnmeldung({ ok: false, runtime_updating: true });
        assert.equal(b.w.document.querySelector("#internet-konten-status").textContent, b.w.MagnolieI18n.gettext("Please wait …"));
        assert.ok(Array.from(section.querySelectorAll("button")).every(button => button.disabled));
        assert.equal(b.w.document.querySelector("#zettel").textContent, toast, "Normal component preparation opened a failure toast");
        const poll = b.timers.findLast(timer => timer.delay === 3000 && !timer.cancelled);
        assert.ok(poll, "Component preparation did not schedule its bounded readiness poll");
        poll.fn();
        assert.equal(b.messages.filter(message => message.cmd === "internet_konten_status").length, reads + 1, "Component preparation did not poll for readiness");
        assert.equal(b.messages.filter(message => message.cmd === "internet_konto_anmelden").length, starts, "Preparation silently queued/replayed sign-in");
        b.w.App.internetKontenStatus({ bereit: true, google: { accounts: [], pending: false }, microsoft: { accounts: [], login: { pending: false } } });
        assert.equal(b.w.document.querySelector("#internet-konten-status").textContent, "");
        assert.ok(Array.from(section.querySelectorAll("button")).every(button => !button.disabled));
        assert.equal(draft.value, "https://owned-draft.example.test"); assert.equal(secret.value, "owned-unsaved-secret");
      }
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves);
      console.log("MCP INTERNET ACCOUNTS PASS: real receipt projection, pagination, action mapping, native ACK/errors, draft gates and silent cancellation " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
