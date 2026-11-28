"use strict";
// Refs #855: real MCP protocol, native response routing and durable SaveACK gate.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const plain = value => JSON.parse(JSON.stringify(value));
const old = (id, country = "DE", region = "DE-SN", art = "public-holiday") => ({ id, country, region, regions: [region], art,
  von: "2026-11-01", bis: "2026-11-01", name: "MCP cache fixture", nationwide: false });
const results = [];
(async () => {
  for (const web of harness.exports.roots) {
    for (const mode of ["success", "failed HTTP", "failed save"]) {
      const b = await harness.exports.boot(web, { einstellungen: { ort: { land: "DE", region: "DE-SN", ferien: false } },
        feiertage: [old("local"), old("foreign", "AT", "AT-9"), old("school", "DE", "DE-SN", "school-holiday")] });
      const watchdog = setTimeout(() => { console.error(`Holiday MCP timeout: ${web}/${mode}`); process.exit(1); }, 20000);
      try {
        b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
        const session = "c".repeat(48); let sequence = 0;
        const request = (id, method, params) => ({ jsonrpc: "2.0", id, method, ...(params === undefined ? {} : { params }) });
        const call = async message => {
          const invocation = (++sequence).toString(16).padStart(48, "0");
          await b.w.App.mcpRequest({ session, invocation, message });
          const reply = b.messages.find(item => item.cmd === "mcp_antwort" && item.invocation === invocation);
          assert.ok(reply, "MCP invocation settles"); return reply.response;
        };
        await call(request(1, "initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "holiday-fixture", version: "1" } }));
        await call({ jsonrpc: "2.0", method: "notifications/initialized" });
        const revision = (await call(request(2, "tools/call", { name: "organizer_holidays_read" }))).result.structuredContent.revision;
        const before = plain(b.t.daten().feiertage), settings = plain(b.t.daten().einstellungen.ort);
        const post = b.w.webkit.messageHandlers.regression.postMessage;
        let nativeRequest, saves = 0;
        b.w.webkit.messageHandlers.regression.postMessage = text => {
          post(text); const message = JSON.parse(text);
          if (message.cmd === "feiertage") {
            nativeRequest = message;
            b.w.App.feiertageErgebnis(mode === "failed HTTP" ? { requestId: message.requestId, fehler: "Fixture unavailable" } : {
              requestId: message.requestId, jahre: message.jahre, feiertage: [],
              abrufbereiche: [{ country: "DE", region: "DE-SN", art: "public-holiday", von: "2026-01-01", bis: "2026-12-31" }] });
          }
          if (message.cmd === "speichern") {
            saves++;
            queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: mode !== "failed save", fehler: mode === "failed save" ? "Fixture save rejected" : "" }));
          }
        };
        const response = await call(request(3, "tools/call", { name: "organizer_holidays_retrieve", arguments: { expected_revision: revision, years: [2026] } }));
        assert.deepEqual(nativeRequest.jahre, [2026]); assert.equal(nativeRequest.region, "DE-SN"); assert.equal(nativeRequest.ferien, false);
        if (mode === "success") {
          assert.equal(response.result.isError, false, JSON.stringify(response)); assert.equal(response.result.structuredContent.persisted, true);
          assert.equal(response.result.structuredContent.imported_count, 0); assert.ok(saves > 0);
          assert.deepEqual(plain(b.t.daten().feiertage).map(item => item.id), ["foreign", "school"]);
        } else if (mode === "failed HTTP") {
          assert.equal(response.result.isError, true, JSON.stringify(response));
          assert.deepEqual(plain(b.t.daten().feiertage), before, "Failed fetch retains original cache");
          assert.deepEqual(plain(b.t.daten().einstellungen.ort), settings, "Failed operation retains retrieval metadata");
        } else {
          // Existing MCP contract keeps a pending in-memory mutation after a
          // failed save; it must report save_failed, never persisted success.
          assert.equal(response.result.isError, true, JSON.stringify(response));
          assert.equal(response.result.structuredContent.code, "save_failed");
          assert.notEqual(response.result.structuredContent.persisted, true);
          assert.ok(saves > 0);
          assert.deepEqual(plain(b.t.daten().feiertage).map(item => item.id), ["foreign", "school"],
            "Even the pending mutation preserves unrelated cache areas");
          const save = b.saves().at(-1); assert.deepEqual(JSON.parse(save.text).feiertage.map(item => item.id), ["foreign", "school"]);
        }
        results.push({ web: path.relative(path.resolve(__dirname, "../.."), web), mode, passed: true });
      } finally { clearTimeout(watchdog); b.close(); }
    }
  }
  console.log(`Holiday MCP: ${results.length}/6 actual-protocol/SaveACK cases passed.`);
  if (process.env.MAGNOLIE_HOLIDAY_REPORT) fs.writeFileSync(process.env.MAGNOLIE_HOLIDAY_REPORT, JSON.stringify({ node: process.version, results }, null, 2) + "\n");
})().catch(error => { console.error(error); process.exitCode = 1; });
