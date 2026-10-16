"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../..");
const protocol = path.join(root, "magnolie-organizer/web/mcp-protocol.js");
assert.equal(fs.readFileSync(protocol, "utf8"), fs.readFileSync(path.join(root, "magnolie-organizer-windows/app/web/mcp-protocol.js"), "utf8"),
  "Both desktop products must ship the same protocol implementation");
vm.runInThisContext(fs.readFileSync(protocol, "utf8"), { filename: protocol });
const { createSession, ToolError } = global.MagnolieMcp;
assert.throws(() => global.MagnolieMcp.validate({ text: "x", extra: true }, {
  type: "object", properties: { text: { type: "string" } }, additionalProperties: false,
  anyOf: [{ required: ["text"] }]
}), error => error.code === -32602, "anyOf must not bypass outer schema restrictions");
const schema = { type: "object", properties: { text: { type: "string", minLength: 1, maxLength: 100 } }, required: ["text"], additionalProperties: false };
const request = (id, method, params) => ({ jsonrpc: "2.0", id, method, ...(params === undefined ? {} : { params }) });
async function ready(session) {
  const reply = await session.dispatch(request(1, "initialize", {
    protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "fixture", version: "1" }
  }));
  assert.equal(reply.result.protocolVersion, "2025-06-18");
  assert.equal(await session.dispatch({ jsonrpc: "2.0", method: "notifications/initialized" }), null);
}
(async () => {
  let calls = 0, authorized = true, release;
  const session = createSession({ serverInfo: { name: "fixture", version: "1" },
    authorize: async () => { if (!authorized) throw new ToolError("locked", "Organizer locked"); },
    tools: [{ name: "save", inputSchema: schema, call: async ({ text }, signal) => {
      calls++;
      await new Promise(resolve => { release = resolve; });
      if (signal.aborted) throw new ToolError("cancelled", "Cancelled before commit");
      return { saved: text };
    } }]
  });
  assert.equal((await session.dispatch(request(2, "tools/call", { name: "save", arguments: { text: "x" } }))).error.code, -32002);
  assert.equal(calls, 0);
  assert.equal((await session.dispatch([])).error.code, -32600);
  assert.equal((await session.dispatch(request(null, "ping"))).error.code, -32600);
  await ready(session);
  assert.equal((await session.dispatch(request(3, "initialize", {}))).error.code, -32600);
  const listed = await session.dispatch(request(4, "tools/list"));
  assert.equal(listed.result.tools.length, 1);
  assert.equal(listed.result.tools[0].call, undefined);
  for (const args of [{}, { text: 42 }, { text: "x", extra: true }, { text: "" }])
    assert.equal((await session.dispatch(request(5, "tools/call", { name: "save", arguments: args }))).error.code, -32602);
  assert.equal((await session.dispatch(request(5, "tools/call", { name: "missing" }))).error.code, -32602);
  assert.equal(calls, 0);
  authorized = false;
  assert.equal((await session.dispatch(request(6, "tools/call", { name: "save", arguments: { text: "x" } }))).result.structuredContent.code, "locked");
  assert.equal(calls, 0);
  authorized = true;
  let replied = false;
  const saved = session.dispatch(request(7, "tools/call", { name: "save", arguments: { text: "fixture" } })).then(value => { replied = true; return value; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 1);
  assert.equal(replied, false, "acceptance must not masquerade as a persisted result");
  assert.equal((await session.dispatch(request(7, "tools/call", { name: "save", arguments: { text: "other" } }))).error.code, -32600);
  release();
  const result = await saved;
  assert.deepEqual(result.result.structuredContent, { saved: "fixture" });
  assert.equal(result.result.isError, false);
  const cancelled = session.dispatch(request("cancel-me", "tools/call", { name: "save", arguments: { text: "cancelled" } }));
  await new Promise(resolve => setImmediate(resolve));
  await session.dispatch({ jsonrpc: "2.0", method: "notifications/cancelled", params: { requestId: "cancel-me" } });
  assert.equal((await cancelled).result.structuredContent.code, "cancelled");
  release();
  session.close();
  assert.equal((await session.dispatch(request(8, "tools/list"))).error.code, -32000);
  let next = 0;
  const paginated = createSession({ serverInfo: { name: "fixture", version: "1" }, tools:
    Array.from({ length: 103 }, () => ({ name: "tool_" + next++, inputSchema: { type: "object" }, call: async () => ({}) })) });
  await ready(paginated);
  const first = (await paginated.dispatch(request(9, "tools/list"))).result;
  const second = (await paginated.dispatch(request(10, "tools/list", { cursor: first.nextCursor }))).result;
  assert.equal(first.tools.length + second.tools.length, 103);
  assert.equal(new Set([...first.tools, ...second.tools].map(tool => tool.name)).size, 103);
  assert.equal(second.nextCursor, undefined);
  assert.equal((await paginated.dispatch(request(11, "tools/list", { cursor: "1e2" }))).error.code, -32602);
  paginated.close();
  const bounded = createSession({ serverInfo: { name: "fixture", version: "1" }, timeoutMs: 20,
    tools: [{ name: "wait", inputSchema: { type: "object" }, call: async () => new Promise(() => {}) }] });
  await ready(bounded);
  const timeout = await bounded.dispatch(request(12, "tools/call", { name: "wait" }));
  assert.equal(timeout.result.isError, true);
  assert.equal(timeout.result.structuredContent.code, "cancelled");
  bounded.close();
  const failed = createSession({ serverInfo: { name: "fixture", version: "1" },
    tools: [{ name: "fail", inputSchema: { type: "object" }, call: async () => { throw new Error("PRIVATE fixture path and credential"); } }] });
  await ready(failed);
  const failure = await failed.dispatch(request(13, "tools/call", { name: "fail" }));
  assert.equal(failure.result.isError, true);
  assert.equal(failure.result.structuredContent.code, "operation_failed");
  assert.ok(!JSON.stringify(failure).includes("PRIVATE"));
  failed.close();
  const malformedResult = createSession({ serverInfo: { name: "fixture", version: "1" }, tools: [{
    name: "wrong_result", inputSchema: { type: "object" },
    outputSchema: { type: "object", properties: { value: { type: "integer" } }, required: ["value"], additionalProperties: false },
    call: async () => ({ value: "PRIVATE invalid provider result" })
  }] });
  await ready(malformedResult);
  const invalidResult = await malformedResult.dispatch(request(14, "tools/call", { name: "wrong_result" }));
  assert.equal(invalidResult.result.isError, true);
  assert.equal(invalidResult.result.structuredContent.code, "invalid_result");
  assert.ok(!JSON.stringify(invalidResult).includes("PRIVATE"));
  malformedResult.close();
  console.log("MCP protocol PASS: lifecycle, typed validation, authorization, durable reply, cancellation, pagination, timeout");
})().catch(error => { console.error(error); process.exitCode = 1; });
