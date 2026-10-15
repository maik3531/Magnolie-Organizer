/* JSON-RPC/MCP session core. Product adapters own authorization and operations. */
"use strict";
(function (global) {
  const versions = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  class ProtocolError extends Error {
    constructor(code, message, data) { super(message); this.code = code; this.data = data; }
  }
  class ToolError extends Error {
    constructor(code, message, details) { super(message); this.code = code; this.details = details; }
  }
  function validate(value, schema, path = "$", depth = 0) {
    if (depth > 32) throw new ProtocolError(-32602, "Arguments exceed maximum nesting");
    const fail = () => { throw new ProtocolError(-32602, "Invalid tool arguments", { path }); };
    if (schema.anyOf) {
      let matched = false;
      for (const alternative of schema.anyOf) {
        try { validate(value, alternative, path, depth + 1); matched = true; break; }
        catch (error) { if (!(error instanceof ProtocolError)) throw error; }
      }
      if (!matched) fail();
    }
    const type = value === null ? "null" : Array.isArray(value) ? "array" : typeof value;
    const allowed = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (schema.type && !allowed.includes(type) && !(allowed.includes("integer") && Number.isSafeInteger(value))) fail();
    if (typeof value === "number" && (!Number.isFinite(value) ||
        (schema.minimum !== undefined && value < schema.minimum) ||
        (schema.maximum !== undefined && value > schema.maximum))) fail();
    if (schema.enum && !schema.enum.some(candidate => JSON.stringify(candidate) === JSON.stringify(value))) fail();
    if (typeof value === "string" && ((schema.minLength !== undefined && value.length < schema.minLength) ||
        (schema.maxLength !== undefined && value.length > schema.maxLength) ||
        (schema.pattern && !new RegExp(schema.pattern, "u").test(value)))) fail();
    if (Array.isArray(value)) {
      if ((schema.minItems !== undefined && value.length < schema.minItems) ||
          (schema.maxItems !== undefined && value.length > schema.maxItems)) fail();
      value.forEach((item, index) => validate(item, schema.items || {}, `${path}[${index}]`, depth + 1));
    }
    if (object(value)) {
      for (const key of schema.required || []) if (!own(value, key)) fail();
      for (const key of Object.keys(value)) {
        if (["__proto__", "prototype", "constructor"].includes(key)) fail();
        if (own(schema.properties || {}, key)) validate(value[key], schema.properties[key], `${path}.${key}`, depth + 1);
        else if (schema.additionalProperties === false) fail();
        else if (object(schema.additionalProperties)) validate(value[key], schema.additionalProperties, `${path}.${key}`, depth + 1);
        else validate(value[key], {}, `${path}.${key}`, depth + 1);
      }
    }
  }
  function createSession({ tools, serverInfo, authorize = async () => {}, timeoutMs = 30000 }) {
    const registry = new Map();
    for (const tool of tools) {
      if (!/^[A-Za-z0-9_.-]{1,128}$/.test(tool.name) || registry.has(tool.name) ||
          !object(tool.inputSchema) || tool.inputSchema.type !== "object" || typeof tool.call !== "function")
        throw new Error("Invalid MCP tool registration");
      registry.set(tool.name, tool);
    }
    if (!object(serverInfo) || typeof serverInfo.name !== "string" || typeof serverInfo.version !== "string")
      throw new Error("Invalid MCP server information");
    const ordered = [...registry.values()].sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    const pending = new Map();
    let state = "new";
    const invalid = message => { throw new ProtocolError(-32602, message); };
    async function dispatch(message) {
      const hasId = object(message) && own(message, "id");
      const id = hasId && (typeof message.id === "string" || Number.isSafeInteger(message.id)) ? message.id : null;
      const reply = error => ({ jsonrpc: "2.0", id, error: { code: error.code, message: error.message,
        ...(error.data === undefined ? {} : { data: error.data }) } });
      if (!object(message) || message.jsonrpc !== "2.0" || typeof message.method !== "string" ||
          (hasId && id === null) || (own(message, "params") && !object(message.params)))
        return reply(new ProtocolError(-32600, "Invalid Request"));
      const params = message.params || {};
      if (!hasId) {
        if (message.method === "notifications/initialized" && state === "initializing") state = "ready";
        if (message.method === "notifications/cancelled" &&
            (typeof params.requestId === "string" || Number.isSafeInteger(params.requestId)))
          pending.get(params.requestId)?.abort();
        return null;
      }
      try {
        if (state === "closed") throw new ProtocolError(-32000, "Session closed");
        if (message.method === "initialize") {
          if (state !== "new") throw new ProtocolError(-32600, "Session already initialized");
          if (typeof params.protocolVersion !== "string" || !object(params.capabilities) ||
              !object(params.clientInfo) || typeof params.clientInfo.name !== "string" ||
              typeof params.clientInfo.version !== "string") invalid("Invalid initialization parameters");
          state = "initializing";
          return { jsonrpc: "2.0", id, result: {
            protocolVersion: versions.includes(params.protocolVersion) ? params.protocolVersion : versions[0],
            capabilities: { tools: { listChanged: false } }, serverInfo: { ...serverInfo }
          } };
        }
        if (message.method === "ping") return { jsonrpc: "2.0", id, result: {} };
        if (state !== "ready") throw new ProtocolError(-32002, "Session not initialized");
        if (message.method === "tools/list") {
          if (Object.keys(params).some(key => !["cursor", "_meta"].includes(key))) invalid("Invalid list parameters");
          const cursor = params.cursor === undefined ? "0" : params.cursor;
          if (typeof cursor !== "string" || !/^(0|[1-9]\d*)$/.test(cursor)) invalid("Invalid cursor");
          const offset = Number(cursor);
          if (!Number.isSafeInteger(offset) || offset > ordered.length) invalid("Invalid cursor");
          const selected = ordered.slice(offset, offset + 100);
          const descriptors = selected.map(({ name, title, description, inputSchema, outputSchema, annotations }) => ({
            name, ...(title ? { title } : {}), ...(description ? { description } : {}), inputSchema,
            ...(outputSchema ? { outputSchema } : {}), ...(annotations ? { annotations } : {})
          }));
          return { jsonrpc: "2.0", id, result: { tools: descriptors,
            ...(offset + selected.length < ordered.length ? { nextCursor: String(offset + selected.length) } : {}) } };
        }
        if (message.method !== "tools/call") throw new ProtocolError(-32601, "Method not found");
        if (Object.keys(params).some(key => !["name", "arguments", "_meta"].includes(key)) ||
            typeof params.name !== "string") invalid("Invalid tool call");
        const tool = registry.get(params.name);
        if (!tool) invalid("Unknown tool");
        const args = params.arguments === undefined ? {} : params.arguments;
        validate(args, tool.inputSchema);
        if (pending.has(id)) throw new ProtocolError(-32600, "Request ID already pending");
        if (pending.size >= 8) throw new ProtocolError(-32000, "Too many pending requests");
        const controller = new AbortController();
        pending.set(id, controller);
        let timer, abortListener;
        try {
          const interrupted = new Promise((_, reject) => {
            abortListener = () => reject(new ToolError("cancelled", "Operation cancelled; check current state before retrying"));
            controller.signal.addEventListener("abort", abortListener, { once: true });
            timer = setTimeout(() => controller.abort(), timeoutMs);
          });
          const operation = (async () => {
            await authorize(tool.name, args, controller.signal);
            if (controller.signal.aborted) throw new ToolError("cancelled", "Operation cancelled");
            return tool.call(args, controller.signal);
          })();
          const result = await Promise.race([operation, interrupted]);
          await authorize(tool.name, args, controller.signal);
          if (controller.signal.aborted) throw new ToolError("cancelled", "Operation cancelled; check current state before retrying");
          if (!object(result)) throw new ToolError("invalid_result", "Tool did not return a structured result");
          if (tool.outputSchema) validate(result, tool.outputSchema);
          return { jsonrpc: "2.0", id, result: { content: [{ type: "text", text: JSON.stringify(result) }], structuredContent: result, isError: false } };
        } catch (error) {
          if (!(error instanceof ToolError)) error = new ToolError("operation_failed", "Operation failed");
          const result = { code: error.code, message: error.message,
            ...(error.details === undefined ? {} : { details: error.details }) };
          return { jsonrpc: "2.0", id, result: { content: [{ type: "text", text: JSON.stringify(result) }], structuredContent: result, isError: true } };
        } finally {
          clearTimeout(timer);
          controller.signal.removeEventListener("abort", abortListener);
          pending.delete(id);
        }
      } catch (error) {
        return reply(error instanceof ProtocolError ? error : new ProtocolError(-32603, "Internal error"));
      }
    }
    return { dispatch, close() { state = "closed"; for (const controller of pending.values()) controller.abort(); } };
  }
  global.MagnolieMcp = Object.freeze({ createSession, ToolError, ProtocolError, validate });
})(typeof window === "undefined" ? globalThis : window);
